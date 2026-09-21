import json
import time
import uuid

from ..database import Database
from ..schema import automation


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.database = Database(path)
        self.database.initialize(automation)

    def connect(self):
        return self.database.connect()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        d = dict(row)
        for k in ("payload", "result", "receipt"):
            if d.get(k):
                d[k] = json.loads(d[k])
        return d

    def enqueue(self, key, kind, payload, parent_id=None, candidate_sha=None, pr_number=None):
        with self.connect() as c:
            return self._enqueue(c, key, kind, payload, parent_id, candidate_sha, pr_number)

    def _enqueue(self, c, key, kind, payload, parent_id=None, candidate_sha=None, pr_number=None):
        now = time.time()
        c.execute(
            "INSERT INTO jobs(id,dedup,kind,state,payload,parent_id,candidate_sha,pr_number,created,updated) VALUES(:p0,:p1,:p2,:p3,:p4,:p5,:p6,:p7,:p8,:p9) ON CONFLICT DO NOTHING",
            {
                "p0": str(uuid.uuid4()),
                "p1": key,
                "p2": kind,
                "p3": "queued",
                "p4": json.dumps(payload),
                "p5": parent_id,
                "p6": candidate_sha,
                "p7": pr_number,
                "p8": now,
                "p9": now,
            },
        )
        return self.decode(c.execute("SELECT * FROM jobs WHERE dedup=:p0", {"p0": key}).fetchone())

    def claim(self, allow_dispatch=True):
        now = time.time()
        with self.connect() as c:
            c.lock()
            # One worker holds one job; expired dispatch cannot be retried blindly.
            c.execute(
                "UPDATE jobs SET state='unknown_effect', error='Worker stopped during provider creation; reconcile session before retrying', lease_until=0 WHERE state='dispatching' AND lease_until<:p0",
                {"p0": now},
            )
            row = c.execute(
                "SELECT * FROM jobs WHERE (state='running' OR (state='queued' AND :dispatch=1)) AND next_poll<=:p0 AND lease_until<:p1 ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,created LIMIT 1",
                {"p0": now, "p1": now, "dispatch": int(allow_dispatch)},
            ).fetchone()
            if not row:
                return None
            # Single flight: don't start another job while another live/uncertain job exists.
            if (
                row["state"] == "queued"
                and c.execute(
                    "SELECT 1 FROM jobs WHERE state IN ('running','dispatching','unknown_effect','needs_attention') OR (session_id IS NOT NULL AND state IN ('blocked','dead_letter')) LIMIT 1"
                ).fetchone()
            ):
                return None
            c.execute(
                "UPDATE jobs SET lease_until=:p0,state=CASE WHEN state='queued' THEN 'dispatching' ELSE state END WHERE id=:p1",
                {"p0": now + 180, "p1": row["id"]},
            )
            return self.decode(row)

    def update(self, jid, **values):
        with self.connect() as c:
            self._update(c, jid, values)

    @staticmethod
    def _update(c, jid, values, *, unless_stale=False):
        values = dict(values)
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
            "parent_id",
        }
        if not set(values) <= allowed:
            raise ValueError("Invalid update fields")
        if "result" in values and values["result"] is not None:
            values["result"] = json.dumps(values["result"])
        values["updated"] = time.time()
        return c.execute(
            "UPDATE jobs SET "
            + ",".join(k + "=:" + k for k in values)
            + " WHERE id=:id"
            + (" AND state!='stale'" if unless_stale else ""),
            {**values, "id": jid},
        ).rowcount

    def commit_handoff(self, jid, *, values, publications=(), followups=()):
        """Commit state, follow-up jobs and reports together; never call providers here.

        Stable job/publication keys make replay safe. Superseded jobs cannot publish
        or enqueue new work. A serialization/DB error rolls back the whole handoff.
        """
        with self.connect() as c:
            c.lock()
            if not self._update(c, jid, values, unless_stale=True):
                return False
            for job in followups:
                self._enqueue(c, **job)
            for item in publications:
                self._queue_publication(c, **item)
            return True

    def commit_validation(self, jid, state, result, error, publications=()):
        return self.commit_handoff(
            jid,
            values={"state": state, "result": result, "error": error},
            publications=publications,
        )

    def by_key(self, key):
        with self.connect() as c:
            return self.decode(
                c.execute("SELECT * FROM jobs WHERE dedup=:p0", {"p0": key}).fetchone()
            )

    def get(self, jid):
        with self.connect() as c:
            return self.decode(c.execute("SELECT * FROM jobs WHERE id=:p0", {"p0": jid}).fetchone())

    def bind_scope(self, repository: str, branch: str, organization: str) -> None:
        """A durable ledger must never be repurposed for a different execution scope."""
        scope = {"repository": repository, "branch": branch, "organization": organization}
        with self.connect() as connection:
            connection.lock()
            row = connection.execute(
                "SELECT value FROM memory WHERE key='execution_scope'"
            ).fetchone()
            if row and json.loads(row["value"]) != scope:
                raise ValueError("Ledger execution scope changed; use a separate database")
            if not row:
                # Legacy keys carry repository identity; scan keys also carry the branch.
                # Preserve exact spelling because durable deduplication keys are case-sensitive.
                for job in connection.execute("SELECT dedup FROM jobs"):
                    parts = job["dedup"].split(":")
                    if len(parts) >= 3 and parts[0] in {
                        "issue",
                        "scan",
                        "validation",
                        "dependency",
                    }:
                        if parts[1] != repository:
                            raise ValueError(
                                "Ledger execution scope changed; use a separate database"
                            )
                        if parts[0] == "scan" and len(parts) >= 4 and parts[2] != branch:
                            raise ValueError(
                                "Ledger execution scope changed; use a separate database"
                            )
                connection.execute(
                    "INSERT INTO memory VALUES('execution_scope',:p0,:p1)",
                    {"p0": json.dumps(scope), "p1": time.time()},
                )

    def session_count(self, excluding: str) -> int:
        with self.connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) AS count FROM jobs WHERE id!=:p0 AND kind!='integration' AND (session_id IS NOT NULL OR state IN ('dispatching','unknown_effect'))",
                {"p0": excluding},
            ).fetchone()["count"]

    def has_delivery(self, delivery: str) -> bool:
        with self.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM deliveries WHERE id=:p0", {"p0": delivery}
                ).fetchone()
                is not None
            )

    def record_delivery(self, delivery: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO deliveries VALUES(:p0,:p1) ON CONFLICT DO NOTHING",
                {"p0": delivery, "p1": time.time()},
            )

    def operational_jobs(self):
        """Complete history for workflow decisions; never use dashboard pagination."""
        with self.connect() as connection:
            return [
                self.decode(row)
                for row in connection.execute("SELECT * FROM jobs ORDER BY created DESC")
            ]

    def metrics(self):
        with self.connect() as connection:
            row = connection.execute("""SELECT
                COUNT(session_id) AS sessions, COALESCE(SUM(acu),0) AS acu,
                COALESCE(SUM(CASE WHEN state='review_ready' THEN 1 ELSE 0 END),0) AS review_ready,
                COALESCE(SUM(CASE WHEN state IN ('blocked','needs_attention','unknown_effect','validation_failed','dead_letter') THEN 1 ELSE 0 END),0) AS attention
                FROM jobs""").fetchone()
            return dict(row)

    def jobs(self):
        with self.connect() as c:
            return [
                self.decode(r)
                for r in c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100")
            ]

    def supersede_validation(self, job, replacement_sha: str | None, repository: str) -> None:
        """Invalidate old evidence and schedule its replacement in one transaction."""
        now = time.time()
        with self.connect() as connection:
            connection.lock()
            current = connection.execute(
                "SELECT state FROM jobs WHERE id=:p0", {"p0": job["id"]}
            ).fetchone()
            if current is None or current["state"] == "stale":
                return  # The atomic transition already happened; delayed observations cannot revive it.
            if replacement_sha:
                key = f"validation:{repository}:{job['pr_number']}:{replacement_sha}"
                previous = connection.execute(
                    "SELECT state FROM jobs WHERE dedup=:p0", {"p0": key}
                ).fetchone()
                if previous and previous["state"] == "stale":
                    # A -> B -> A needs a fresh session; preserve the original A evidence.
                    # The superseded job makes retries deterministic without reusing old evidence.
                    key += f":after:{job['id']}"
                connection.execute(
                    "INSERT INTO jobs\n                    (id,dedup,kind,state,payload,parent_id,candidate_sha,pr_number,created,updated)\n                    SELECT :p0,:p1,'validation','queued',payload,parent_id,:p2,pr_number,:p3,:p4 FROM jobs WHERE id=:p5 ON CONFLICT DO NOTHING",
                    {
                        "p0": str(uuid.uuid4()),
                        "p1": key,
                        "p2": replacement_sha,
                        "p3": now,
                        "p4": now,
                        "p5": job["id"],
                    },
                )
            connection.execute(
                "UPDATE jobs SET state='stale',error=:p0,updated=:p1 WHERE id=:p2",
                {"p0": "PR changed; previous evidence is stale", "p1": now, "p2": job["id"]},
            )

    def audit(self, jid, kind, detail):
        with self.connect() as c:
            c.execute(
                "INSERT INTO audit(job_id,kind,detail,created) VALUES(:p0,:p1,:p2,:p3)",
                {"p0": jid, "p1": kind, "p2": json.dumps(detail), "p3": time.time()},
            )

    def has_audit(self, job_id, kind):
        with self.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM audit WHERE job_id=:p0 AND kind=:p1 LIMIT 1",
                    {"p0": job_id, "p1": kind},
                ).fetchone()
                is not None
            )

    def remember(self, key, value):
        with self.connect() as c:
            c.execute(
                "INSERT INTO memory VALUES(:p0,:p1,:p2) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                {"p0": key, "p1": json.dumps(value), "p2": time.time()},
            )

    def recall(self, key, default=None):
        with self.connect() as c:
            row = c.execute("SELECT value FROM memory WHERE key=:p0", {"p0": key}).fetchone()
            return json.loads(row["value"]) if row else default

    def queue_publication(self, key, payload):
        with self.connect() as c:
            self._queue_publication(c, key, payload)

    @staticmethod
    def _queue_publication(c, key, payload):
        c.execute(
            "INSERT INTO publications(key,state,updated,payload) VALUES(:p0,'pending',:p1,:p2) ON CONFLICT DO NOTHING",
            {"p0": key, "p1": time.time(), "p2": json.dumps(payload)},
        )

    def claim_publication(self):
        with self.connect() as c:
            c.lock()
            c.execute(
                "UPDATE publications SET state='unknown_effect',error='Worker stopped during send; reconcile provider receipt' WHERE state='sending' AND updated<:p0",
                {"p0": time.time() - 180},
            )
            c.execute(
                "UPDATE publications SET state='delivered' WHERE state='confirming' AND receipt IS NOT NULL AND updated<:p0",
                {"p0": time.time() - 180},
            )
            row = c.execute(
                "SELECT p.* FROM publications p LEFT JOIN recovery r ON r.key='publication:' || p.key "
                "WHERE p.state IN ('pending','delivered') AND COALESCE(r.next_retry,0)<=:now ORDER BY p.updated LIMIT 1",
                {"now": time.time()},
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE publications SET state=:p0,updated=:p1 WHERE key=:p2",
                {
                    "p0": "confirming" if row["receipt"] else "sending",
                    "p1": time.time(),
                    "p2": row["key"],
                },
            )
            return self.decode(row)

    def finish_publication(self, key, state, url=None, error=None, receipt=None):
        with self.connect() as c:
            c.execute(
                "UPDATE publications SET state=:p0,url=:p1,error=:p2,receipt=COALESCE(:p3,receipt),updated=:p4 WHERE key=:p5",
                {
                    "p0": state,
                    "p1": url,
                    "p2": error,
                    "p3": json.dumps(receipt) if receipt else None,
                    "p4": time.time(),
                    "p5": key,
                },
            )

    def publications(self):
        with self.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT key,state,url,error,updated FROM publications ORDER BY updated DESC LIMIT 100"
                )
            ]

    def all_publications(self):
        """Public delivery metadata only; never expose bodies, secrets or provider receipts."""
        with self.connect() as c:
            return [
                dict(row)
                for row in c.execute(
                    "SELECT key,state,url,error,updated FROM publications ORDER BY updated DESC"
                )
            ]
