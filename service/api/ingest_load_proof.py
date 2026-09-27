"""Evidence-producing concurrent ingest/read and fault-recovery experiment.

Requires an already-running, disposable Compose project whose name starts with
``tram-load-``. Never run against the default ``service`` project or real data.
The script writes only its local report directory and the isolated project's
ingest volume; it does not remove Docker volumes.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "service/docker-compose.yml"),
           "-f", str(ROOT / "service/docker-compose.loadproof.yml")]


def command(*args, timeout=10):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout.strip()


def pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[int((len(values) - 1) * q)], 1)


def phase(rows, start, end):
    x = [r for r in rows if start <= r["at"] < end]
    return {"requests": len(x), "failures": sum(r["failed"] for r in x),
            "rps": round(len(x) / max(end - start, .001), 1),
            "p95_ms": pct([r["ms"] for r in x], .95),
            "p99_ms": pct([r["ms"] for r in x], .99)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="isolated Compose project, e.g. tram-load-20260927")
    parser.add_argument("--base-url", default="http://127.0.0.1:8124")
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--duration", type=int, default=180)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"tram-load-[a-z0-9-]+", args.project):
        parser.error("project must start with tram-load- and contain only lowercase letters, digits, hyphens")
    if args.duration < args.warmup + 45:
        parser.error("duration must leave at least 45 seconds after warmup")
    args.out.mkdir(parents=True, exist_ok=False)
    container = command(*COMPOSE, "-p", args.project, "ps", "-q", "api")
    if not container:
        raise RuntimeError("isolated API container not running")
    label = command("docker", "inspect", "--format", '{{ index .Config.Labels "com.docker.compose.project" }}', container)
    if label != args.project:
        raise RuntimeError(f"refusing fault injection: project label is {label!r}")

    base = args.base_url.rstrip("/")
    ready = requests.get(base + "/ready", timeout=5)
    ready.raise_for_status()
    old_version = ready.json()["version"]
    session = requests.Session()
    token = session.post(base + "/auth/token", data={"username": "demo", "password": "demo2025"}, timeout=10)
    token.raise_for_status()
    session.headers["Authorization"] = "Bearer " + token.json()["access_token"]
    info = session.get(base + "/model/info", timeout=10).json()
    if info["data_until"] != "2025-10-31":
        raise RuntimeError("test needs a fresh isolated project with data_until=2025-10-31")
    day = info["horizon"]["start"]
    response = session.get(base + "/forecast", params={"date_from": day, "date_to": day}, timeout=10)
    response.raise_for_status()
    routes = set(session.get(base + "/routes", timeout=10).json()["routes"])
    facts = [r for r in response.json()["rows"] if r["route"] in routes]
    if len(facts) < 100:
        raise RuntimeError(f"too few synthetic facts: {len(facts)}")
    body = "route;date;hour;boardings\n" + "".join(
        f"{r['route']};{day};{r['hour']};{max(0, round(r['prediction']))}\n" for r in facts)

    samples = []
    shared = {"published_at": None}
    stop = threading.Event()

    def sample():
        previous_cpu, previous_at = None, None
        while not stop.is_set():
            row = {"at": time.time(), "ready_status": None, "version": "", "cpu_percent": None,
                   "memory_usage": "", "memory_bytes": None, "swap_bytes": None}
            try:
                cgroup = command("docker", "exec", container, "sh", "-c",
                                 "cat /sys/fs/cgroup/cpu.stat /sys/fs/cgroup/memory.current "
                                 "/sys/fs/cgroup/memory.swap.current", timeout=3).splitlines()
                cpu_usec = int(next(line.split()[1] for line in cgroup if line.startswith("usage_usec ")))
                row["memory_bytes"], row["swap_bytes"] = map(int, cgroup[-2:])
                row["memory_usage"] = f"{row['memory_bytes'] / 1048576:.1f} MiB"
                measured_at = time.time()
                if previous_cpu is not None and cpu_usec >= previous_cpu:
                    row["cpu_percent"] = round(100 * (cpu_usec - previous_cpu) / (1e6 * (measured_at - previous_at)), 2)
                previous_cpu, previous_at = cpu_usec, measured_at
            except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
                pass  # expected while the container restarts during fault injection
            try:
                r = requests.get(base + "/ready", timeout=2)
                row["ready_status"] = r.status_code
                if r.ok:
                    row["version"] = r.json().get("version", "")
                    if row["version"] != old_version and shared["published_at"] is None:
                        shared["published_at"] = row["at"]
            except requests.RequestException:
                pass
            samples.append(row)
            stop.wait(max(0, 1 - (time.time() - row["at"])))

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    log = args.out / "locust.log"
    prefix = args.out / "locust"
    request_log = args.out / "requests.csv"
    env = os.environ.copy()
    env["TRAM_REQUEST_LOG"] = str(request_log)
    env["TRAM_FORECAST_DAY_MIN"] = "12"  # still in horizon after ingest of Nov 1
    locust = [sys.executable, "-m", "locust", "-f", str(ROOT / "service/api/loadtest_dispatcher.py"),
              "--headless", "-u", str(args.users), "-r", "10", "-t", f"{args.duration}s",
              "--host", base, "--csv", str(prefix), "--only-summary"]
    with log.open("w", encoding="utf-8") as output:
        load = subprocess.Popen(locust, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        started = time.time()
        try:
            time.sleep(args.warmup)
            sent_at = time.time()
            post = session.post(base + "/ingest/hourly", data=body.encode(), timeout=30)
            accepted_at = time.time()
            post.raise_for_status()
            ingest = post.json()
            print(f"ingest accepted: {len(facts)} rows; version {old_version}; waiting for publication", flush=True)
            try:
                rc = load.wait(timeout=args.duration + 90)
            except subprocess.TimeoutExpired:
                load.terminate()
                rc = load.wait(timeout=10)
            ended = time.time()
        finally:
            if load.poll() is None:
                load.terminate()
                load.wait(timeout=10)

    # Fault injection is AFTER the clean load measurement. Verify the exact
    # isolated project label again, then kill only the engine child, not Docker.
    expected_version = next((s["version"] for s in samples if s["version"] and s["version"] != old_version), None)
    if expected_version is None:
        raise RuntimeError("new forecast version was not observed; refusing fault injection")
    restart_before = int(command("docker", "inspect", "--format", "{{.RestartCount}}", container))
    fault_at = time.time()
    killer = ("import os,signal; "
              "matches=[int(p) for p in os.listdir('/proc') if p.isdigit() and int(p)!=os.getpid() "
              "and b'-m\\x00service.engine.refresher\\x00' in "
              "open('/proc/'+p+'/cmdline','rb').read()]; "
              "assert len(matches)==1,matches; print(matches[0]); os.kill(matches[0],signal.SIGKILL)")
    label = command("docker", "inspect", "--format", '{{ index .Config.Labels "com.docker.compose.project" }}', container)
    if label != args.project:
        raise RuntimeError("project label changed before fault injection")
    killed_pid = command("docker", "exec", container, "python", "-c", killer)
    recovered_at, restart_after, recovered_version, recovered_data_until = None, None, None, None
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            restart_after = int(command("docker", "inspect", "--format", "{{.RestartCount}}", container))
            r = requests.get(base + "/ready", timeout=2)
            if restart_after > restart_before and r.ok and r.json().get("version") == expected_version:
                recovered_version = r.json()["version"]
                recovered_data_until = session.get(base + "/model/info", timeout=2).json().get("data_until")
                if recovered_data_until == day:
                    recovered_at = time.time()
                    break
        except (requests.RequestException, ValueError, subprocess.SubprocessError):
            pass
        time.sleep(1)
    stop.set()
    sampler.join(timeout=15)

    with (args.out / "resources.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]) if samples else ["at"])
        writer.writeheader()
        writer.writerows(samples)
    with request_log.open(newline="", encoding="utf-8") as handle:
        rows = [{"at": float(r["completed_at_unix"]), "ms": float(r["response_time_ms"]),
                 "failed": r["failed"] == "True"} for r in csv.DictReader(handle)]
    published_at = shared["published_at"]
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "project": args.project,
        "note": "synthetic complete-day boardings copied from forecast; performance proof, not accuracy proof",
        "users": args.users, "duration_requested_s": args.duration, "locust_exit_code": rc,
        "ingest": ingest, "facts_rows": len(facts), "ingest_http_seconds": round(accepted_at - sent_at, 3),
        "old_version": old_version, "new_version": expected_version,
        "publish_delay_from_request_s": round(published_at - sent_at, 2) if published_at else None,
        "publish_delay_after_accepted_s": round(published_at - accepted_at, 2) if published_at else None,
        "phases": {"before_ingest": phase(rows, started, sent_at),
                   "during_refresh": phase(rows, sent_at, published_at or ended),
                   "after_publish": phase(rows, published_at, ended) if published_at and published_at < ended else None},
        "resources": {"samples": len(samples),
                      "cpu_max_percent_of_one_core": max((s["cpu_percent"] or 0 for s in samples), default=0),
                      "memory_max_bytes": max((s["memory_bytes"] or 0 for s in samples), default=0),
                      "swap_max_bytes": max((s["swap_bytes"] or 0 for s in samples), default=0)},
        "fault": {"killed_engine_pid": int(killed_pid), "restart_count_before": restart_before,
                  "restart_count_after": restart_after,
                  "recovered_version": recovered_version, "recovered_data_until": recovered_data_until,
                  "recovery_seconds": round(recovered_at - fault_at, 2) if recovered_at else None},
    }
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if rc or not published_at or not recovered_at:
        raise RuntimeError("experiment failed; inspect the report directory")


if __name__ == "__main__":
    main()
