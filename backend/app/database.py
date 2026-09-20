"""Small SQLAlchemy transaction boundary shared by the workflow and analytics stores.

Postgres is the deployed database. SQLite paths remain supported for isolated unit
fixtures and reading the legacy ledger during migration; no SQL dialect rewriting.
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text


@dataclass(frozen=True)
class DatabaseLimits:
    """Per-engine budgets; replicas multiply the connection ceiling."""

    pool_size: int = 2
    max_overflow: int = 1
    pool_timeout: int = 5
    connect_timeout: int = 5
    statement_timeout_ms: int = 30_000
    lock_timeout_ms: int = 5_000

    def __post_init__(self):
        for name, value in vars(self).items():
            if value < (0 if name == "max_overflow" else 1):
                raise ValueError(f"Database limit {name} must be positive (overflow may be zero)")

    @classmethod
    def from_env(cls):
        return cls(
            **{
                name: int(os.getenv("DB_" + name.upper(), str(default)))
                for name, default in vars(cls()).items()
            }
        )


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
    def __init__(self, location, *, limits: DatabaseLimits | None = None):
        location = str(location)
        if "://" not in location:
            Path(location).parent.mkdir(parents=True, exist_ok=True)
            location = "sqlite:///" + location
        if location.startswith("postgresql://"):
            location = location.replace("postgresql://", "postgresql+psycopg://", 1)
        limits = limits or DatabaseLimits.from_env()
        postgres_options = (
            {
                "pool_size": limits.pool_size,
                "max_overflow": limits.max_overflow,
                "pool_timeout": limits.pool_timeout,
                "pool_use_lifo": True,
                "connect_args": {
                    "connect_timeout": limits.connect_timeout,
                    "options": (
                        f"-c statement_timeout={limits.statement_timeout_ms} "
                        f"-c lock_timeout={limits.lock_timeout_ms} "
                        "-c idle_in_transaction_session_timeout=60000"
                    ),
                },
            }
            if location.startswith("postgresql")
            else {"connect_args": {"timeout": 20}}
        )
        self.engine = create_engine(
            location,
            pool_pre_ping=True,
            hide_parameters=True,
            **postgres_options,
        )

    @contextmanager
    def connect(self):
        with self.engine.begin() as connection:
            yield Transaction(connection)

    def initialize(self, metadata):
        try:
            with self.connect() as transaction:
                transaction.lock()
                metadata.create_all(transaction.connection)
        except Exception:
            # Store construction has not returned, so no caller owns this pool yet.
            self.close()
            raise

    def close(self):
        self.engine.dispose()
