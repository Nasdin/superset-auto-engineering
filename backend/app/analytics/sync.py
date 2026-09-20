"""Bounded, paginated, read-only import. Run independently of paid Devin jobs."""

import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from ..automation.config import Settings
from .enrichment import enrich_repository
from .store import AnalyticsStore

HISTORY_DAYS = 730


def sync_repository(store, repository, client, *, now=None, max_pages=300):
    now = now or datetime.now(UTC)
    previous = store.status(repository)
    horizon = now - timedelta(days=HISTORY_DAYS)
    # A failed or truncated first import must retry the full horizon.
    incremental = bool(
        previous.get("complete")
        and datetime.fromisoformat(previous["last_success"]) - timedelta(days=1) >= horizon
    )
    cutoff = (
        max(horizon, datetime.fromisoformat(previous["last_success"]) - timedelta(days=1))
        if incremental
        else horizon
    )
    status = {
        **previous,
        "state": "syncing",
        "started_at": now.isoformat(),
        "pages": 0,
        "error": None,
    }
    store.set_status(repository, status)
    try:
        for page in range(1, max_pages + 1):
            response = client.get(
                f"https://api.github.com/repos/{repository}/pulls",
                params={
                    "state": "all",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            response.raise_for_status()
            pulls = response.json()
            if not isinstance(pulls, list):
                raise ValueError("Invalid GitHub PR collection")
            store.upsert(repository, pulls)
            status["pages"] = page
            store.set_status(repository, status)
            crossed = (
                bool(pulls)
                and min(
                    datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00")) for pr in pulls
                )
                < cutoff
            )
            if len(pulls) < 100 or crossed:
                # Coverage refers to event dates, not PR creation dates; old PRs
                # merged recently are retained because their updated_at is recent.
                store.set_status(
                    repository,
                    {
                        **status,
                        "state": "ready",
                        "complete": True,
                        "coverage_from": previous["coverage_from"]
                        if incremental
                        else (horizon.date() + timedelta(days=1)).isoformat(),
                        "last_success": now.isoformat(),
                        "finished_at": datetime.now(UTC).isoformat(),
                    },
                )
                return
        store.set_status(
            repository,
            {**status, "state": "partial", "error": "Page limit reached; history is incomplete"},
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        # Never persist response bodies or authorization headers.
        detail = (
            f"GitHub HTTP {error.response.status_code}"
            if isinstance(error, httpx.HTTPStatusError)
            else type(error).__name__
        )
        store.set_status(repository, {**status, "state": "error", "error": detail})


def main():
    settings = Settings.from_env()
    store = AnalyticsStore(
        settings.analytics_database,
        seed=Path(__file__).resolve().parents[1] / "seeds" / "github-history.sqlite3",
    )
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    logging.basicConfig(level=logging.INFO)
    with httpx.Client(headers=headers, timeout=45) as client:
        while True:
            for repository in dict.fromkeys([settings.repo, "apache/superset"]):
                sync_repository(store, repository, client)
                logging.info("Analytics %s: %s", repository, store.status(repository)["state"])
                progress = enrich_repository(store, repository, client)
                logging.info("Analytics detail enrichment %s: %s", repository, progress)
            time.sleep(3600)


if __name__ == "__main__":
    main()
