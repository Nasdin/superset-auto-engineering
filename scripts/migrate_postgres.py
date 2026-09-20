"""Offline, atomic migration. Stop all writers first. Refuse a nonempty target.

DATABASE_URL is read from the environment; never pass credentials on argv.
SQLite sources stay untouched and each copied table is verified before commit.
"""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import insert, select, text
from app.database import Database
from app.schema import automation, analytics


def migrate(database_url, ledger, history):
    database = Database(database_url)
    try:
        if database.engine.dialect.name != "postgresql":
            raise ValueError("Target must be Postgres")
        database.initialize(automation)
        database.initialize(analytics)
        counts = {}
        with database.engine.begin() as target:
            target.execute(text("SELECT pg_advisory_xact_lock(684032194)"))
            tables = [*automation.sorted_tables, *analytics.sorted_tables]
            if any(
                target.execute(select(t).limit(1)).first() is not None for t in tables
            ):
                raise ValueError(
                    "Target is not empty; migration refused. Use a new database, never overwrite live records."
                )
            for source_path, metadata in ((ledger, automation), (history, analytics)):
                with sqlite3.connect(
                    Path(source_path).resolve().as_uri() + "?mode=ro", uri=True
                ) as source:
                    source.row_factory = sqlite3.Row
                    for table in metadata.sorted_tables:
                        if not source.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table.name,),
                        ).fetchone():
                            continue
                        rows = [
                            dict(row)
                            for row in source.execute(f'SELECT * FROM "{table.name}"')
                        ]
                        if rows:
                            target.execute(insert(table), rows)
                        copied = [
                            dict(row._mapping) for row in target.execute(select(table))
                        ]
                        canonical = lambda data: sorted(
                            json.dumps(row, sort_keys=True) for row in data
                        )
                        # Optional legacy columns can gain NULL defaults, so compare source columns.
                        narrowed = (
                            [{key: row[key] for key in rows[0]} for row in copied]
                            if rows
                            else copied
                        )
                        if canonical(rows) != canonical(narrowed):
                            raise ValueError("Readback differs for " + table.name)
                        counts[table.name] = len(rows)
            target.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('audit','id'), COALESCE(MAX(id),1), MAX(id) IS NOT NULL) FROM audit"
                )
            )
        return counts
    finally:
        database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "verified_rows": migrate(
                    os.environ["DATABASE_URL"], args.ledger, args.history
                )
            },
            indent=2,
        )
    )
