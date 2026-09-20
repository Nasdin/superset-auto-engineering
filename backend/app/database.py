"""Small SQLAlchemy transaction boundary shared by the workflow and analytics stores.

Postgres is the deployed database. SQLite paths remain supported for isolated unit
fixtures and reading the legacy ledger during migration; no SQL dialect rewriting.
"""

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text


class Result:
    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        self.rows = cursor.mappings() if cursor.returns_rows else None

    def fetchone(self):
        return self.rows.fetchone() if self.rows is not None else None

    def fetchall(self):
        return self.rows.fetchall() if self.rows is not None else []

    def __iter__(self):
        return iter(self.rows) if self.rows is not None else iter(())


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=None):
        return Result(self.connection.execute(text(statement), parameters or {}))

    def executemany(self, statement, records):
        if records:
            return Result(self.connection.execute(text(statement), records))
        return None

    def lock(self):
        """Serialize short claim/schema transactions, including across AWS workers."""
        if self.connection.dialect.name == "postgresql":
            self.execute("SELECT pg_advisory_xact_lock(684032194)")
        else:
            self.execute("BEGIN IMMEDIATE")


class Database:
    def __init__(self, location):
        location = str(location)
        if "://" not in location:
            Path(location).parent.mkdir(parents=True, exist_ok=True)
            location = "sqlite:///" + location
        if location.startswith("postgresql://"):
            location = location.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(
            location,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 20} if location.startswith("sqlite:") else {},
        )

    @contextmanager
    def connect(self):
        with self.engine.begin() as connection:
            yield Transaction(connection)

    def initialize(self, metadata):
        with self.connect() as transaction:
            transaction.lock()
            metadata.create_all(transaction.connection)

    def close(self):
        self.engine.dispose()
