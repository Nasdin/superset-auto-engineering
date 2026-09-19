## Scope

Implement a real release-branch repair in **Nasdin/superset**, targeting **cognition-release-6.1**, baseline **c37118edd0146019ab0ae4ae1a97a597cb56c88e**. Do not target Apache's repository and do not merge.

This is a take-home release-maintenance scenario based on an existing upstream report, not a claim of a newly discovered master-branch bug. Attribution: https://github.com/apache/superset/issues/44412 and https://github.com/apache/superset/pull/38617 . Current master already uses different expressions; the pinned release branch still contains the affected implementation.

## Observed behavior (independently reproduced)

The release's MySQL SECOND/MINUTE/HOUR templates in `superset/db_engine_specs/mysql.py` depend on `DATE(timestamp)` truncation. SQLGlot 28.10.0 (the pinned release dependency) removes this truncation when rewriting the DATE_ADD expression.

I extracted the expressions from the exact baseline AST, passed each through `sqlglot.parse_one(..., read='mysql').sql(dialect='mysql')`, and executed the emitted SQL in a real MySQL 8.0.46 container. Six of nine input/grain checks failed. Midnight checks passed; non-midnight and end-of-day checks failed.

| Input | Grain | Expected | Actual |
|---|---|---|---|
| 2026-09-18 08:15:30 | HOUR | 2026-09-18 08:00:00 | 2026-09-18 16:15:30 |
| 2026-09-18 08:15:30 | MINUTE | 2026-09-18 08:15:00 | 2026-09-18 16:30:30 |
| 2026-09-18 08:15:30 | SECOND | 2026-09-18 08:15:30 | 2026-09-18 16:31:00 |
| 2026-09-18 23:59:59 | HOUR | 2026-09-18 23:00:00 | 2026-09-19 22:59:59 |

This qualification is at the engine-expression/SQLGlot/MySQL boundary. A full Superset browser reproduction has not yet been performed and is explicitly required in final validation.

## Minimal reproduction

Install the release-pinned SQLGlot version in an isolated environment, then:

```python
import sqlglot
original = "SELECT DATE_ADD(DATE(CAST('2026-09-18 08:15:30' AS DATETIME)), INTERVAL HOUR(CAST('2026-09-18 08:15:30' AS DATETIME)) HOUR) AS bucket"
print(sqlglot.parse_one(original, read='mysql').sql(dialect='mysql'))
```

Execute the output in MySQL 8.0. It returns `2026-09-18 16:15:30` rather than the required hour bucket `2026-09-18 08:00:00`.

## Acceptance criteria (do not weaken)

1. Verify the baseline SHA and reproduce the failure before changing code.
2. Implement the smallest release-compatible repair for SECOND, MINUTE and HOUR; retain upstream attribution where relevant.
3. Tests must exercise the SQLGlot round trip, not only compare source strings. Cover midnight, 08:15:30 and 23:59:59. All three grains must return the correct bucket without moving to the following day.
4. Run the relevant existing engine-spec tests and changed-file pre-commit checks. Preserve unrelated behavior.
5. Open a PR into `Nasdin/superset:cognition-release-6.1` with exact baseline/candidate SHAs and actual commands/results. Never open an upstream PR or merge.
6. A separate fresh validator must boot Superset from the candidate, inspect real query/chart results through browser controls, and capture screenshots, a video, service/database logs and test evidence. Implementation completion alone is not final validation.
