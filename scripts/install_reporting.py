"""Install version-controlled, read-only Superset views after the database migration."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.database import Database
from app.schema import automation, analytics


def install(url):
    db = Database(url)
    db.initialize(automation)
    db.initialize(analytics)
    if db.engine.dialect.name != "postgresql":
        raise ValueError("Reporting requires Postgres")
    with db.connect() as transaction:
        transaction.lock()
        for statement in (
            (
                Path(__file__).resolve().parents[1]
                / "backend/app/analytics/reporting.sql"
            )
            .read_text()
            .split(";")
        ):
            if statement.strip():
                transaction.execute(statement)
    db.close()


if __name__ == "__main__":
    install(os.environ["DATABASE_URL"])
    print("Installed Superset reporting views.")
