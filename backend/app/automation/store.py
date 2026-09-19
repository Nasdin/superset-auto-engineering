from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, dedup TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
              state TEXT NOT NULL, payload TEXT NOT NULL, session_id TEXT, session_url TEXT,
              parent_id TEXT, candidate_sha TEXT, pr_number INTEGER, result TEXT,
              error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
              next_poll REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
              acu REAL NOT NULL DEFAULT 0, started REAL);
            CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, received REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, job_id TEXT, kind TEXT, detail TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS publications (key TEXT PRIMARY KEY, state TEXT NOT NULL, url TEXT, error TEXT, updated REAL NOT NULL, payload TEXT);
            CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, sha TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL);
            """)
            for table, column, declaration in [
                ("jobs", "started", "REAL"),
                ("publications", "payload", "TEXT"),
            ]:
                if column not in {
                    r[1] for r in c.execute(f"PRAGMA table_info({table})")
                }:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=20)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        d = dict(row)
        for k in ("payload", "result"):
            if d.get(k):
                d[k] = json.loads(d[k])
        return d

    def enqueue(
        self, key, kind, payload, parent_id=None, candidate_sha=None, pr_number=None
    ):
        now = time.time()
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO jobs(id,dedup,kind,state,payload,parent_id,candidate_sha,pr_number,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    key,
                    kind,
                    "queued",
                    json.dumps(payload),
                    parent_id,
                    candidate_sha,
                    pr_number,
                    now,
                    now,
                ),
            )
            return self.decode(
                c.execute("SELECT * FROM jobs WHERE dedup=?", (key,)).fetchone()
            )

    def claim(self):
        now = time.time()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            # One worker holds one job; expired dispatch cannot be retried blindly.
            c.execute(
                "UPDATE jobs SET state='unknown_effect', error='Worker stopped during provider creation; reconcile session before retrying', lease_until=0 WHERE state='dispatching' AND lease_until<?",
                (now,),
            )
            row = c.execute(
                "SELECT * FROM jobs WHERE state IN ('queued','running') AND next_poll<=? AND lease_until<? ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,created LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            # Single flight: don't start another job while another live/uncertain job exists.
            if (
                row["state"] == "queued"
                and c.execute(
                    "SELECT 1 FROM jobs WHERE state IN ('running','dispatching','unknown_effect','needs_attention') LIMIT 1"
                ).fetchone()
            ):
                return None
            c.execute(
                "UPDATE jobs SET lease_until=?,state=CASE WHEN state='queued' THEN 'dispatching' ELSE state END WHERE id=?",
                (now + 180, row["id"]),
            )
            return self.decode(row)

    def update(self, jid, **values):
        allowed = {
            "state",
            "session_id",
            "session_url",
            "result",
            "error",
            "next_poll",
            "lease_until",
            "acu",
            "pr_number",
            "candidate_sha",
            "started",
        }
        if not set(values) <= allowed:
            raise ValueError("Invalid update fields")
        if "result" in values and values["result"] is not None:
            values["result"] = json.dumps(values["result"])
        values["updated"] = time.time()
        with self.connect() as c:
            c.execute(
                "UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                (*values.values(), jid),
            )

    def by_key(self, key):
        with self.connect() as c:
            return self.decode(
                c.execute("SELECT * FROM jobs WHERE dedup=?", (key,)).fetchone()
            )

    def get(self, jid):
        with self.connect() as c:
            return self.decode(
                c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            )

    def jobs(self):
        with self.connect() as c:
            return [
                self.decode(r)
                for r in c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100")
            ]

    def audit(self, jid, kind, detail):
        with self.connect() as c:
            c.execute(
                "INSERT INTO audit(job_id,kind,detail,created) VALUES(?,?,?,?)",
                (jid, kind, json.dumps(detail), time.time()),
            )

    def remember(self, key, value):
        with self.connect() as c:
            c.execute(
                "INSERT INTO memory VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                (key, json.dumps(value), time.time()),
            )

    def recall(self, key, default=None):
        with self.connect() as c:
            row = c.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
            return json.loads(row["value"]) if row else default

    def queue_publication(self, key, payload):
        with self.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO publications(key,state,updated,payload) VALUES(?,'pending',?,?)",
                (key, time.time(), json.dumps(payload)),
            )

    def claim_publication(self):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "UPDATE publications SET state='unknown_effect',error='Worker stopped during send; reconcile provider receipt' WHERE state='sending' AND updated<?",
                (time.time() - 180,),
            )
            row = c.execute(
                "SELECT * FROM publications WHERE state='pending' ORDER BY updated LIMIT 1"
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE publications SET state='sending',updated=? WHERE key=?",
                (time.time(), row["key"]),
            )
            return {**dict(row), "payload": json.loads(row["payload"])}

    def begin_publication(self, key):
        with self.connect() as c:
            return (
                c.execute(
                    "INSERT OR IGNORE INTO publications(key,state,updated) VALUES(?,'sending',?)",
                    (key, time.time()),
                ).rowcount
                == 1
            )

    def finish_publication(self, key, state, url=None, error=None):
        with self.connect() as c:
            c.execute(
                "UPDATE publications SET state=?,url=?,error=?,updated=? WHERE key=?",
                (state, url, error, time.time(), key),
            )

    def publications(self):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT key,state,url,error,updated FROM publications ORDER BY updated DESC LIMIT 100"
                )
            ]
