"""Keep the forecast refresher and API in one failure domain.

If either exits unexpectedly, stop its peer and let Docker restart the container.
"""
import os
import signal
import subprocess
import sys
import time

children = []
stopping = False


def stop(_signum=None, _frame=None):
    global stopping
    stopping = True
    for child in children:
        if child.poll() is None:
            child.terminate()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def main():
    import store  # create metadata tables once before uvicorn forks workers
    children.append(subprocess.Popen([sys.executable, "-m", "service.engine.refresher"]))
    children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000",
                                      "--workers", os.environ.get("WORKERS", "4")]))
    try:
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1
            time.sleep(1)
        return 0
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
