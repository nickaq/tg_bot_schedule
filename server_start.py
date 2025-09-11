import threading
import subprocess
import sys
import time

def _run_health():
    from health_server import start_health_server
    start_health_server()


def _run_bot():
    # Starts your existing bot entrypoint. Adjust if your main file is different.
    return subprocess.call([sys.executable, "bot.py"])  # noqa: S603,S607


if __name__ == "__main__":
    t = threading.Thread(target=_run_health, daemon=True)
    t.start()
    # Give the health server a moment to bind the port
    time.sleep(0.5)
    exit_code = _run_bot()
    sys.exit(exit_code)