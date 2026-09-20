"""Serve the built UI against temporary databases, with all provider access disabled."""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.automation.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.analytics.store import AnalyticsStore  # noqa: E402
from app.analytics.metrics import months_before  # noqa: E402

if __name__ == "__main__":
    with TemporaryDirectory(prefix="cognition-browser-test-") as directory:
        data = Path(directory)
        analytics = AnalyticsStore(data / "analytics.db")
        end = datetime.now(UTC).date() - timedelta(days=1)
        pulls = []
        for index in range(12):
            merged = datetime.combine(end if index < 6 else months_before(end), datetime.min.time(), UTC)
            created = merged - timedelta(days=1 if index < 6 else 2)
            pulls.append({"number": index + 1, "title": f"fix: browser analytics fixture {index}", "html_url": f"https://github.com/apache/superset/pull/{index+1}", "user": {"login": "test-engineer"}, "labels": [{"name": "bug"}], "base": {"ref": "master"}, "state": "closed", "created_at": created.isoformat(), "updated_at": merged.isoformat(), "closed_at": merged.isoformat(), "merged_at": merged.isoformat()})
        analytics.upsert("apache/superset", pulls)
        analytics.set_status("apache/superset", {"state": "ready", "complete": True, "coverage_from": "2020-01-01", "last_success": datetime.now(UTC).isoformat()})
        application = create_app(
            Settings(database=str(data / "live.db")),
            demo_database=data / "demo.db",
            static_directory=ROOT / "frontend" / "dist",
        )
        uvicorn.run(application, host="127.0.0.1", port=8010)
