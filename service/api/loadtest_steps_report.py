import csv, re, sys
from pathlib import Path

OUT = Path(sys.argv[1])
def mib(s):
    v, u = re.match(r"([\d.]+)\s*([KMG]i?B)", s).groups()
    return float(v) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "KB": 1 / 1024, "MB": 1, "GB": 1024}[u]

print("польз | RPS | p50 | p95 | p99 | макс | ошибки | CPU сред/макс (% от 4 vCPU) | RAM макс")
for u in sorted(int(p.stem[1:].split("_")[0]) for p in OUT.glob("u*_stats.csv")):
    rows = list(csv.DictReader(open(OUT / f"u{u}_stats.csv")))
    a = next(r for r in rows if r["Name"] == "Aggregated")
    cpu, mem = [], []
    f = OUT / f"res_{u}.txt"
    if f.exists():
        for line in f.read_text().splitlines():
            try:
                c, m = line.split(";"); cpu.append(float(c.rstrip("%")) / 4); mem.append(mib(m.split("/")[0].strip()))
            except (ValueError, AttributeError):
                pass
    n, fails = int(a["Request Count"]), int(a["Failure Count"])
    print(f"{u} | {float(a['Requests/s']):.0f} | {a['50%']} | {a['95%']} | {a['99%']} | {float(a['Max Response Time']):.0f} | "
          f"{fails}/{n} ({100 * fails / max(n, 1):.2f}%) | {sum(cpu) / max(len(cpu), 1):.0f}/{max(cpu, default=0):.0f} | {max(mem, default=0):.0f} МиБ")
    if u in (100, 200):
        print("   по запросам:", "; ".join(f"{r['Name']}: p95 {r['95%']}" for r in rows if r["Name"] != "Aggregated"))
