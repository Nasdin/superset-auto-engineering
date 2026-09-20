# Committed demo database

`demo.sqlite3` contains synthetic dashboard fixtures (five illustrative workflows, an integration candidate and example checks) and an empty event table. It contains no credentials, live jobs, session identifiers or publication outbox.

The API opens this seed read-only and inserts its fixture into a separate local database on first use. Demo interactions persist locally. Existing local databases are preserved. Docker includes the seed automatically; use the root `.env.example` and `docker compose up --build -d` to start the demo without credentials.

Rebuild from the repository root:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.demo_seed
```

The source fixtures are in `demo_fixtures.py`; tests compare the committed database to a freshly generated seed and verify that runtime requests never change its bytes. Only this named SQLite file is allowed through the Git/Docker ignore rules. Live execution databases remain local so reviewers cannot accidentally resume someone else's work.
