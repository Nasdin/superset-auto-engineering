"""Serve the built UI against temporary databases, with all provider access disabled."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.automation.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

if __name__ == "__main__":
    with TemporaryDirectory(prefix="cognition-browser-test-") as directory:
        data = Path(directory)
        application = create_app(
            Settings(database=str(data / "live.db")),
            demo_database=data / "demo.db",
            static_directory=ROOT / "frontend" / "dist",
        )
        uvicorn.run(application, host="127.0.0.1", port=8010)
