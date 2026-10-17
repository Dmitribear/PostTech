"""Supervise reminders and integration delivery in the background container."""

import signal
import subprocess
import sys
import time


def main():
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    children = []
    try:
        for module in ("scripts.workflow_worker", "scripts.integration_worker"):
            children.append(subprocess.Popen([sys.executable, "-m", module]))
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 20
        for child in children:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
