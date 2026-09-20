"""Read-only worker heartbeat probe; never creates sessions or provider requests."""

import time

from .config import Settings
from .store import Store


def main():
    store = Store(Settings.from_env().database)
    try:
        at = store.recall("worker_status", {}).get("at", 0)
        raise SystemExit(0 if time.time() - at < 600 else 1)
    finally:
        store.database.close()


if __name__ == "__main__":
    main()
