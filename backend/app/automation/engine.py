import html
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlparse
from .prompts import session_payload
from .providers import ProviderError, UnknownEffect

REQUIRED_CHECKS = {"services", "database", "browser", "regression"}
REQUIRED_ARTIFACTS = {"screenshot", "video", "logs", "tests"}


def plain_report(value):
    text = html.escape(str(value)).replace("@", "@\u200b")
    for char in ["[", "]", "*", "_", "`"]:
        text = text.replace(char, "\\" + char)
    return text


def safe_link(url):
    p = urlparse(url)
    return (
        p.scheme == "https"
        and bool(p.hostname)
        and not p.username
        and not p.password
        and not any(x in url for x in ["\n", "\r", ")", "<", ">"])
    )


class Engine:
    def __init__(self, settings, store, providers):
        self.s, self.db, self.p = settings, store, providers
        settings.check_repo()

    def accept_issue(self, number, source):
        prior = self.db.by_key(f"issue:{self.s.repo}:{number}")
        if prior:
            return prior
        issue = self.p.gh("GET", f"repos/{self.s.repo}/issues/{number}")
        if issue.get("pull_request") or issue["state"] != "open":
            raise ValueError("Only open issues are eligible")
        if self.s.label not in [x["name"] for x in issue.get("labels", [])]:
            raise ValueError("Required repair label is missing")
        if issue["user"]["login"].lower() != self.s.allowed_actor.lower():
            raise ValueError("Issue author is not authorized")
        ref = self.p.gh("GET", f"repos/{self.s.repo}/commits/{self.s.branch}")
        return self.db.enqueue(
            f"issue:{self.s.repo}:{number}",
            "repair",
            {
                "issue_number": number,
                "title": issue["title"],
                "issue_url": issue["html_url"],
                "base_sha": ref["sha"],
                "source": source,
            },
        )

    def poll_issues(self):
        issues = self.p.gh(
            "GET",
            f"repos/{self.s.repo}/issues",
            params={"state": "open", "labels": self.s.label, "per_page": 50},
        )
        accepted = 0
        for issue in issues:
            try:
                self.accept_issue(issue["number"], "github_poll")
                accepted += 1
            except ValueError:
                continue
        self.db.remember("last_issue_poll", {"at": time.time(), "eligible": accepted})
        return accepted

    def schedule_scan(self):
        bucket = int(time.time() // max(self.s.scan_interval, 1))
        key = f"scan:{self.s.repo}:{self.s.branch}:{bucket}"
        prior = self.db.by_key(key)
        if prior:
            return prior
        ref = self.p.gh("GET", f"repos/{self.s.repo}/commits/{self.s.branch}")
        return self.db.enqueue(
            key,
            "scan",
            {
                "base_sha": ref["sha"],
                "source": "schedule",
                "title": "Scheduled bounded correctness scan",
            },
        )

    def tick(self):
        if not self.s.enabled:
            return None
        if not self.s.devin_key or not self.s.github_token:
            self.db.remember(
                "worker_status", {"state": "configuration_required", "at": time.time()}
            )
            return None
        job = self.db.claim()
        if not job:
            return None
        try:
            if job["state"] == "queued":
                self.dispatch(job)
            else:
                self.poll(job)
        except UnknownEffect as e:
            self.db.update(job["id"], state="unknown_effect", error=str(e))
            self.db.audit(job["id"], "unknown_effect", {"action": "provider mutation"})
        except ProviderError as e:
            # Poll errors are observations, not terminal session status.
            self.db.update(
                job["id"], error=str(e), next_poll=time.time() + self.s.poll_seconds
            )
            if job["state"] == "queued":
                self.db.update(job["id"], state="blocked")
        except (ValueError, KeyError, TypeError) as e:
            self.db.update(
                job["id"],
                state="needs_attention",
                error=f"Invalid provider result: {type(e).__name__}: {str(e)[:250]}",
            )
        finally:
            self.db.update(job["id"], lease_until=0)
        return self.db.get(job["id"])

    def dispatch(self, job):
        if job["kind"] == "integration":
            self.assemble_candidate(job)
            return
        with self.db.connect() as c:
            used = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE id!=? AND kind!='integration' AND (session_id IS NOT NULL OR state IN ('dispatching','unknown_effect'))",
                (job["id"],),
            ).fetchone()[0]
        required_slots = {"repair": 2, "scan": 3, "validation": 1}[job["kind"]]
        if used + required_slots > self.s.max_sessions:
            self.db.update(
                job["id"],
                state="blocked",
                error="Configured total session limit reached",
            )
            return
        payload = session_payload(self.s, job, self.db.recall("repository_lessons", []))
        self.db.update(job["id"], state="dispatching", started=time.time())
        self.db.audit(
            job["id"],
            "dispatch_started",
            {"kind": job["kind"], "max_acu": self.s.max_acu},
        )
        session = self.p.create_session(payload)
        if not session.get("session_id") or not safe_link(session.get("url", "")):
            raise UnknownEffect(
                "Creation response missing session identity; reconcile by job tag"
            )
        self.db.update(
            job["id"],
            state="running",
            session_id=session["session_id"],
            session_url=session["url"],
            started=time.time(),
            next_poll=time.time() + self.s.poll_seconds,
        )
        self.db.audit(
            job["id"], "session_created", {"session_id": session["session_id"]}
        )

    def poll(self, job):
        session = self.p.session(job["session_id"])
        if session.get("session_id") != job["session_id"]:
            raise ValueError("Provider returned a different session")
        self.db.update(
            job["id"],
            acu=session.get("acus_consumed", 0),
            next_poll=time.time() + self.s.poll_seconds,
            error=None,
        )
        self.db.audit(
            job["id"],
            "session_observed",
            {"status": session.get("status"), "detail": session.get("status_detail")},
        )
        result = session.get("structured_output")
        # Devin can idle awaiting another instruction after completing a task.
        # Only an explicit final handoff may enter the normal evidence checks.
        ready = session.get("status_detail") == "finished" or (
            session.get("status") == "running"
            and session.get("status_detail") == "waiting_for_user"
            and isinstance(result, dict)
            and result.get("task_complete") is True
        )
        if ready:
            if not isinstance(result, dict):
                raise ValueError("Finished session has no structured output")
            if job["kind"] == "repair":
                self.finish_repair(job, result)
            elif job["kind"] == "scan":
                self.finish_scan(job, result)
            else:
                self.finish_validation(job, result)
            return
        if session.get("status") in {"error", "exit", "suspended"} or session.get(
            "status_detail"
        ) in {"waiting_for_user", "waiting_for_approval"}:
            self.db.update(
                job["id"],
                state="needs_attention",
                error=f"Devin {session.get('status')}: {session.get('status_detail')}",
            )
        elif time.time() - (job.get("started") or time.time()) > self.s.session_timeout:
            # Archive is a real provider action; an ambiguous result is never called stopped.
            self.p.devin("POST", f"sessions/{job['session_id']}/archive", json={})
            self.db.update(
                job["id"],
                state="needs_attention",
                error="Time limit reached; archive requested. Inspect the provider session before resuming.",
            )

    def finish_repair(self, job, result):
        if result.get("blocker"):
            self.db.update(
                job["id"],
                state="needs_attention",
                error="Repair blocker: " + str(result["blocker"])[:250],
            )
            return
        pattern = rf"https://github\.com/{re.escape(self.s.repo)}/pull/(\d+)"
        match = re.fullmatch(pattern, result.get("pr_url", ""), flags=re.I)
        if not match:
            self.db.update(
                job["id"],
                state="needs_attention",
                error="No PR in the configured fork: "
                + result.get("blocker", "")[:250],
            )
            return
        number = int(match[1])
        pr = self.p.pr(number)
        if (
            pr["base"]["repo"]["full_name"].lower() != self.s.repo.lower()
            or pr["base"]["ref"] != self.s.branch
            or pr["state"] != "open"
        ):
            raise ValueError("PR target or state mismatch")
        sha = pr["head"]["sha"]
        self.publish(
            job["id"],
            job["payload"]["issue_number"],
            f"Implementation prepared: {pr['html_url']}\n\nDevin session: {job['session_url']}\n\nCandidate `{sha}` is waiting for the integration batch and independent validation. It is not yet verified.",
        )
        self.db.update(
            job["id"],
            state="implemented",
            pr_number=number,
            candidate_sha=sha,
            result=result,
        )

    def finish_scan(self, job, result):
        findings = result.get("findings", [])
        if len(findings) > 1:
            raise ValueError("Discovery exceeded one-issue scope")
        for finding in findings:
            if finding.get("base_sha") != job["payload"]["base_sha"] or not finding.get(
                "reproduction"
            ):
                raise ValueError("Discovery lacks baseline reproduction")
            fingerprint = hashlib.sha256(
                (self.s.repo + finding["title"]).encode()
            ).hexdigest()[:20]
            key = "finding:" + fingerprint
            if self.db.recall(key):
                continue
            marker = f"<!-- cognition-finding:{fingerprint} -->"
            body = f"{marker}\n\n{finding['description']}\n\n## Reproduction at `{finding['base_sha']}`\n{finding['reproduction']}\n\n## Acceptance criteria\n{finding['acceptance']}\n\nDiscovered by {job['session_url']}. This is a reported finding; independent validation is required."
            # Reconcile previously uncertain issue creation by marker before any retry.
            prior = self.p.gh(
                "GET",
                f"repos/{self.s.repo}/issues",
                params={"state": "all", "per_page": 100},
            )
            issue = next((x for x in prior if marker in (x.get("body") or "")), None)
            if not issue:
                issue = self.p.gh(
                    "POST",
                    f"repos/{self.s.repo}/issues",
                    json={
                        "title": finding["title"],
                        "body": body,
                        "labels": [self.s.label],
                    },
                )
            self.db.remember(
                key, {"issue": issue["number"], "sha": finding["base_sha"]}
            )
            self.accept_issue(issue["number"], "scheduled_scan")
        self.db.update(job["id"], state="completed")
        self.db.remember(
            "last_scan",
            {"job": job["id"], "findings": len(findings), "at": time.time()},
        )

    def finish_validation(self, job, result):
        pr = self.p.pr(job["pr_number"])
        if pr["state"] != "open" or pr["head"]["sha"] != job["candidate_sha"]:
            self.db.update(
                job["id"],
                state="stale",
                error="PR changed during validation; evidence cannot approve the new revision",
            )
            return
        attachments = self.p.attachments(job["session_id"])
        if isinstance(attachments, dict):
            attachments = attachments.get("items", attachments.get("attachments", []))
        known = {a["url"]: a for a in attachments if a.get("source") == "devin"}
        artifacts = result.get("artifacts", [])
        checks = result.get("checks", [])

        def media_matches(a):
            meta = known.get(a.get("url"), {})
            mime = (meta.get("content_type") or "").lower().split(";")[0]
            kind = a.get("kind")
            return (
                (kind == "screenshot" and mime.startswith("image/"))
                or (kind == "video" and mime.startswith("video/"))
                or (
                    kind in {"logs", "tests"}
                    and (
                        mime.startswith("text/")
                        or mime
                        in {"application/json", "application/xml", "application/zip"}
                    )
                )
            )

        valid = (
            result.get("candidate_sha") == job["candidate_sha"]
            and result.get("passed") is True
            and not str(result.get("blocker", "")).strip()
            and len({c["name"] for c in checks}) == len(checks)
            and REQUIRED_CHECKS <= {c["name"] for c in checks}
            and all(c.get("passed") is True and c.get("command") for c in checks)
            and REQUIRED_ARTIFACTS <= {a.get("kind") for a in artifacts}
            and len({a.get("url") for a in artifacts}) == len(artifacts)
            and len(
                {known.get(a.get("url"), {}).get("attachment_id") for a in artifacts}
            )
            == len(artifacts)
            and all(
                a.get("url") in known and safe_link(a["url"]) and media_matches(a)
                for a in artifacts
            )
            and all(
                self.db.get(jid)["session_id"] != job["session_id"]
                for jid in job["payload"].get("implementation_jobs", [job["parent_id"]])
            )
        )
        status = "review_ready" if valid else "validation_failed"
        # Artifacts remain provider-hosted. No request is made to an agent-selected URL.
        verified_artifacts = [
            {**a, "attachment_id": known[a["url"]]["attachment_id"]}
            for a in artifacts
            if a.get("url") in known and safe_link(a["url"])
        ]
        result = {
            **result,
            "artifacts": verified_artifacts,
            "provenance": "independent_devin_session",
            "gate": status,
        }
        report = self.report(job, result, status)
        targets = [job["pr_number"], job["payload"]["issue_number"]]
        for member in job["payload"].get("members", []):
            targets += [member["pr_number"], member["issue_number"]]
        for number in dict.fromkeys(targets):
            self.publish(job["id"], number, report)
        if self.s.slack_token and self.s.slack_channel:
            self.publish_slack(job, report)
        self.db.update(
            job["id"],
            state=status,
            result=result,
            error=(
                None
                if valid
                else "Incomplete, failing or unproven independent evidence"
            ),
        )
        lessons = self.db.recall("repository_lessons", [])
        lessons = [x for x in lessons if x["candidate_sha"] != job["candidate_sha"]]
        self.db.remember(
            "repository_lessons",
            (
                lessons
                + [
                    {
                        "candidate_sha": job["candidate_sha"],
                        "status": status,
                        "summary": result.get("summary", "")[:1000],
                    }
                ]
            )[-20:],
        )

    def report(self, job, result, status):
        lines = [
            f'## Cognition release validation — {status.replace("_"," ")}',
            f"Candidate: `{job['candidate_sha']}`",
            f"Independent Devin validator: {job['session_url']}",
            "This is independently collected agent evidence for human review, not a merge or deployment approval.",
            "",
            plain_report(result.get("summary", "")),
            "",
            "| Check | Result | Command |",
            "|---|---|---|",
        ]
        for c in result.get("checks", []):
            clean = lambda s: str(s).replace("|", "/").replace("\n", " ")[:300]
            lines.append(
                f"| {clean(c['name'])} | {'pass' if c.get('passed') else 'FAIL'} | `{clean(c.get('command',''))}` |"
            )
        lines += ["", "### Screenshots, video and execution evidence"]
        lines += [
            f"- [{a['kind']}: {plain_report(a['name'])}](<{a['url']}>)"
            for a in result["artifacts"]
        ]
        if not result["artifacts"]:
            lines.append(
                "No provider-confirmed artifacts available. The evidence gate is blocked."
            )
        if result.get("blocker"):
            lines += ["", "Blocker: " + plain_report(result["blocker"])]
        return "\n\n".join(lines)

    def publish(self, jid, number, body):
        key = f"github:{jid}:{number}"
        self.db.queue_publication(
            key,
            {
                "provider": "github",
                "repository": self.s.repo,
                "number": number,
                "body": f"<!-- {key} -->\n" + body,
            },
        )

    def publish_slack(self, job, body):
        key = f'slack:{job["id"]}'
        self.db.queue_publication(
            key,
            {
                "provider": "slack",
                "channel": self.s.slack_channel,
                "body": f"Cognition {self.s.repo} PR #{job['pr_number']}\n{body}",
            },
        )

    def flush_publication(self):
        item = self.db.claim_publication()
        if not item:
            return
        key, payload = item["key"], item["payload"]
        receipt = item.get("receipt")
        try:
            if not receipt:
                if payload["provider"] == "github":
                    result = self.p.comment(
                        payload["number"],
                        payload["body"],
                        repository=payload.get("repository", self.s.repo),
                    )
                    receipt = {"id": result["id"]}
                else:
                    result = self.p.slack(
                        payload["body"],
                        str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                        channel=payload.get("channel", self.s.slack_channel),
                    )
                    receipt = {"channel": result["channel"], "ts": result["ts"]}
                # Persist the acknowledged write BEFORE any readback. If the read
                # fails or the worker crashes, only confirmation is retried.
                self.db.finish_publication(key, "confirming", receipt=receipt)
            url = self.p.confirm_publication(payload, receipt)
            if not safe_link(url):
                raise ProviderError("Provider returned an invalid report URL")
            self.db.finish_publication(key, "sent", url=url)
        except (UnknownEffect, ProviderError, KeyError, TypeError, ValueError) as error:
            state = (
                "delivered"
                if receipt
                else "failed" if isinstance(error, ProviderError) else "unknown_effect"
            )
            self.db.finish_publication(key, state, error=str(error))

    def refresh_readiness(self):
        for job in self.db.jobs():
            if job["state"] != "review_ready":
                continue
            pr = self.p.pr(job["pr_number"])
            if pr["state"] != "open" or pr["head"]["sha"] != job["candidate_sha"]:
                self.db.update(
                    job["id"],
                    state="stale",
                    error="PR changed after validation; prior evidence is stale",
                )
                if pr["state"] == "open":
                    self.db.enqueue(
                        f"validation:{self.s.repo}:{job['pr_number']}:{pr['head']['sha']}",
                        "validation",
                        job["payload"],
                        parent_id=job["parent_id"],
                        candidate_sha=pr["head"]["sha"],
                        pr_number=job["pr_number"],
                    )

    def schedule_batch(self):
        jobs = self.db.jobs()
        taken = {
            m["job_id"]
            for j in jobs
            if j["kind"] == "integration"
            for m in j["payload"]["members"]
        }
        ready = [
            j for j in jobs if j["state"] == "implemented" and j["id"] not in taken
        ]
        # A short quiet period coalesces commits; other queued/running repairs complete first.
        if not ready or any(
            j["kind"] == "repair" and j["state"] in {"queued", "running", "dispatching"}
            for j in jobs
        ):
            return None
        if time.time() - max(j["updated"] for j in ready) < self.s.batch_seconds:
            return None
        members = [
            {
                "job_id": j["id"],
                "pr_number": j["pr_number"],
                "sha": j["candidate_sha"],
                "issue_number": j["payload"]["issue_number"],
            }
            for j in sorted(ready, key=lambda j: j["created"])
        ]
        digest = hashlib.sha256(
            json.dumps(members, sort_keys=True).encode()
        ).hexdigest()[:20]
        return self.db.enqueue(
            "integration:" + digest,
            "integration",
            {
                "members": members,
                "source": "batch",
                "title": f"Integrate {len(members)} completed workstreams",
            },
        )

    def assemble_candidate(self, job):
        members = job["payload"]["members"]
        checkpoint = job.get("result") or {}
        branch = "cognition/integration/" + job["id"][:12]
        if not checkpoint:
            base = self.p.gh("GET", f"repos/{self.s.repo}/commits/{self.s.branch}")[
                "sha"
            ]
            checkpoint = {
                "base_sha": base,
                "head_sha": base,
                "applied": 0,
                "branch": branch,
            }
            self.db.update(job["id"], result=checkpoint)
        base = checkpoint["base_sha"]
        try:
            current = self.p.gh("GET", f"repos/{self.s.repo}/git/ref/heads/{branch}")[
                "object"
            ]["sha"]
        except ProviderError as e:
            if e.status != 404:
                raise
            self.p.gh(
                "POST",
                f"repos/{self.s.repo}/git/refs",
                json={"ref": "refs/heads/" + branch, "sha": base},
            )
            current = base
        for index, member in enumerate(members):
            pr = self.p.pr(member["pr_number"])
            if (
                pr["state"] != "open"
                or pr["head"]["sha"] != member["sha"]
                or pr["base"]["ref"] != self.s.branch
                or pr["base"]["repo"]["full_name"].lower() != self.s.repo.lower()
            ):
                raise ValueError(
                    "Component PR changed before integration; rebuild from fresh component revisions"
                )
            if index < checkpoint["applied"]:
                continue
            expected = checkpoint["head_sha"]
            if current != expected:
                # Reconcile a merge whose response/checkpoint was lost. Accept only
                # the intended merge parents or an exact fast-forward component.
                commit = self.p.gh("GET", f"repos/{self.s.repo}/git/commits/{current}")
                parents = {x["sha"] for x in commit["parents"]}
                if current != member["sha"] and parents != {expected, member["sha"]}:
                    raise ValueError(
                        "Integration branch has an unexpected commit; operator review required"
                    )
                if current == member["sha"]:
                    comparison = self.p.gh(
                        "GET", f"repos/{self.s.repo}/compare/{expected}...{current}"
                    )
                    if comparison["merge_base_commit"]["sha"] != expected:
                        raise ValueError("Unexpected integration fast-forward")
            else:
                merge = self.p.gh(
                    "POST",
                    f"repos/{self.s.repo}/merges",
                    json={
                        "base": branch,
                        "head": member["sha"],
                        "commit_message": f"Integrate PR #{member['pr_number']} for independent validation",
                    },
                )
                current = (
                    merge["sha"]
                    if merge
                    else self.p.gh(
                        "GET", f"repos/{self.s.repo}/git/ref/heads/{branch}"
                    )["object"]["sha"]
                )
            checkpoint = {**checkpoint, "head_sha": current, "applied": index + 1}
            self.db.update(job["id"], result=checkpoint)
            self.db.audit(
                job["id"],
                "integration_component",
                {
                    "pr": member["pr_number"],
                    "sha": member["sha"],
                    "integrated_sha": current,
                },
            )
        if current != checkpoint["head_sha"]:
            raise ValueError("Completed integration branch changed externally")
        body = (
            "Integration candidate for independent validation. Do not merge before reviewing evidence.\n\n"
            + "\n".join(
                f"- #{m['pr_number']} at `{m['sha']}` (issue #{m['issue_number']})"
                for m in members
            )
            + f"\n\nExact candidate: `{current}`."
        )
        matches = self.p.gh(
            "GET",
            f"repos/{self.s.repo}/pulls",
            params={
                "state": "all",
                "head": self.s.repo.split("/")[0] + ":" + branch,
                "base": self.s.branch,
            },
        )
        pr = next((x for x in matches if x["head"]["ref"] == branch), None)
        if not pr:
            pr = self.p.gh(
                "POST",
                f"repos/{self.s.repo}/pulls",
                json={
                    "title": f"Cognition integration: {len(members)} workstream(s)",
                    "head": branch,
                    "base": self.s.branch,
                    "body": body,
                    "draft": True,
                },
            )
        elif pr["state"] != "open" or pr["head"]["sha"] != current:
            raise ValueError("Existing integration PR is not open at expected revision")
        payload = {
            "issue_number": members[0]["issue_number"],
            "title": job["payload"]["title"],
            "source": "integration",
            "members": members,
            "implementation_jobs": [m["job_id"] for m in members],
            "base_sha": base,
            "branch": branch,
        }
        self.db.enqueue(
            f"validation:{self.s.repo}:{pr['number']}:{current}",
            "validation",
            payload,
            parent_id=members[0]["job_id"],
            candidate_sha=current,
            pr_number=pr["number"],
        )
        self.db.update(
            job["id"],
            state="integrated",
            candidate_sha=current,
            pr_number=pr["number"],
            result={**checkpoint, "pr_url": pr["html_url"], "members": members},
        )
