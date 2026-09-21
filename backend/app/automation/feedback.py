"""Versioned, operator-attributed corrections. Provider delivery stays in the worker."""

import json
import time


class FeedbackConflict(ValueError):
    pass


class FeedbackService:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def save(self, command):
        identity = command["request_id"]
        group = command.get("feedback_id") or identity
        expected = command.get("expected_revision")
        job = self.store.get(command["source_job_id"])
        if not job:
            raise ValueError("Choose an existing source run")
        with self.store.connect() as c:
            c.lock()
            prior = c.execute("SELECT body FROM lessons WHERE id=:id", {"id": identity}).fetchone()
            if prior:
                observation = json.loads(prior["body"])
                if observation.get("feedback_command") != command:
                    raise FeedbackConflict(
                        "Request identity was already used for different feedback"
                    )
                return {"id": identity, "feedback_id": group, "replayed": True}
            if c.execute(
                "SELECT 1 FROM learning_guard WHERE expires>:now", {"now": time.time()}
            ).fetchone():
                raise FeedbackConflict("Knowledge sync is in progress. Retry this edit shortly")
            head = c.execute("SELECT * FROM feedback_heads WHERE id=:id", {"id": group}).fetchone()
            if head:
                if head["lesson_id"] != expected or head["source_job_id"] != job["id"]:
                    raise FeedbackConflict(
                        "This memory changed. Reload its latest revision before editing"
                    )
                previous = json.loads(
                    c.execute("SELECT body FROM lessons WHERE id=:id", {"id": expected}).fetchone()[
                        "body"
                    ]
                )
                if command.get("source_lesson_id") != previous.get("source_lesson_id"):
                    raise ValueError("An edit cannot change the original observation")
            elif command.get("feedback_id") or expected or command["retired"]:
                raise FeedbackConflict("The memory to edit does not exist")
            source_lesson = command.get("source_lesson_id")
            if source_lesson:
                source = c.execute(
                    "SELECT * FROM lessons WHERE id=:id", {"id": source_lesson}
                ).fetchone()
                if not source or source["job_id"] != job["id"]:
                    raise ValueError("Source observation must belong to the selected run")
            created = time.time()
            observation = {
                "job_id": job["id"],
                "kind": "human_feedback",
                "status": "retired" if command["retired"] else "corrected",
                "title": command["title"],
                "summary": command["correction"],
                "candidate_sha": previous.get("candidate_sha")
                if head
                else job.get("candidate_sha"),
                "pr_number": previous.get("pr_number") if head else job.get("pr_number"),
                "session_url": previous.get("session_url") if head else job.get("session_url"),
                "feedback_id": group,
                "previous_revision": expected,
                "source_lesson_id": source_lesson,
                "author": command["author"],
                "original_author": previous.get("original_author", previous["author"])
                if head
                else command["author"],
                "attribution": "operator_reported",
                "reason": command["reason"],
                "feedback_command": command,
                "repository": self.settings.repo,
                "branch": self.settings.branch,
            }
            c.execute(
                "INSERT INTO lessons(id,job_id,body,created) VALUES(:id,:job,:body,:at)",
                {
                    "id": identity,
                    "job": "feedback:" + group,
                    "body": json.dumps(observation, sort_keys=True),
                    "at": created,
                },
            )
            c.execute(
                "INSERT INTO feedback_heads(id,source_job_id,lesson_id) VALUES(:id,:job,:lesson) ON CONFLICT(id) DO UPDATE SET lesson_id=:lesson",
                {"id": group, "job": job["id"], "lesson": identity},
            )
            c.execute(
                "INSERT INTO audit(job_id,kind,detail,created) VALUES(:job,:kind,:detail,:at)",
                {
                    "job": job["id"],
                    "kind": "human_feedback",
                    "detail": json.dumps(
                        {
                            "feedback_id": group,
                            "revision": identity,
                            "previous_revision": expected,
                            "author": command["author"],
                            "attribution": "operator_reported",
                        }
                    ),
                    "at": created,
                },
            )
        return {"id": identity, "feedback_id": group, "replayed": False}
