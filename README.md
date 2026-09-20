# Superset Auto Engineering

Superset analyzing Superset: a FastAPI + React/TypeScript control plane for GitHub history, bounded Devin engineering workflows, and independent validation evidence. **Postgres is the default runtime database.** Apache Superset renders the analytics dashboard from read-only Postgres reporting views. SQLite is supported for a smaller local workflow/API setup.

Issues and Dependabot PRs → Devin implementation → exact candidate SHA → a fresh validation session → screenshots, API transcripts, logs and test evidence → GitHub/Slack report → human review.

## Where it runs

| Environment | Address | Status |
| --- | --- | --- |
| Current local dashboard | [http://127.0.0.1:8000](http://127.0.0.1:8000) | Running locally; open **Analytics** for embedded Superset |
| Local BI Superset | [http://127.0.0.1:8189/bi](http://127.0.0.1:8189/bi) | Separate from candidate-validation Superset |
| Public AWS dashboard | [superset-devin.nasrudinsalim.com](https://superset-devin.nasrudinsalim.com) | Live in Sydney; reviewer password required |
| Public analytics | [Analytics workspace](https://superset-devin.nasrudinsalim.com/#analytics) | Six real Superset charts behind the same reviewer login |
| Public source | [Nasdin/superset-auto-engineering](https://github.com/Nasdin/superset-auto-engineering) | Application code, documentation and CI |

The public deployment uses one Lightsail VM in **ap-southeast-2 (Sydney)**, provisioned with the [Lightsail CloudFormation template](infra/cloudformation/lightsail.yaml). The local addresses refer to the computer running Docker. See the [low-cost runbook](docs/LOW_COST_AWS.md) and [verified deployment evidence](docs/analysis/sydney-deployment.json). The cloud worker is authoritative; local automatic dispatch is disabled. The first independent candidate has accepted evidence in [the PR report](https://github.com/Nasdin/superset/pull/4#issuecomment-5751674737); deployment health and each later candidate still require their own checks.

[Live analytics screenshot](docs/images/superset-analytics-live.png) · [architecture and migration](docs/POSTGRES_SUPERSET.md) · [product story/slides](docs/README.md)

## 1. Clone and configure `.env`

Prerequisites: Git, Python 3 for the credential helper, Docker Engine or Docker Desktop, and the Docker Compose plugin **2.20 or newer** (the default stack uses `include`). Node and local Python packages are not needed for Docker builds. The full stack runs several containers; allow sufficient Docker memory for Superset, Postgres and a frontend build.

```sh
git clone https://github.com/Nasdin/superset-auto-engineering.git
cd superset-auto-engineering
cp .env.example .env
python3 scripts/configure_local_postgres.py
python3 scripts/configure_login.py --local-http
docker compose version
```

Run the copy step only on a fresh clone. The helper creates missing/empty database, Superset, operator and webhook secrets, keeps existing nonempty values, and restricts `.env` to mode 0600. Do not commit `.env` or copy another installation's live database into Git.

**Before the first startup**, set these values in `.env` if using your own fork/organization:

```dotenv
GITHUB_REPOSITORY=your-github-user/superset
TARGET_BRANCH=your-release-branch
GITHUB_ALLOWED_ACTOR=your-github-user
DEVIN_ORG_ID=your-devin-organization-id
AUTOMATION_ENABLED=false
```

The checked-in example uses the take-home fork `Nasdin/superset`, branch `cognition-release-6.1`, and Asmar DE Takehome organization. Those are example scope values, not credentials. They can be used to browse the public history without starting Devin. A ledger binds its repository, branch and organization on first startup, even with automation disabled. To change scope later, use a new Compose project/database and configure that scope first; do not edit scope records or discard existing audit history.

Compose reads `.env` for interpolation and passes an explicit set of settings to each service. Superset and Postgres do not receive Devin/GitHub/Slack credentials. Changing `.env` requires container recreation with `docker compose up -d`; `docker compose restart` does not reload it. Changing a generated password in `.env` alone does not rotate an existing database or Superset account.

### Environment settings

| Setting | Purpose / default |
| --- | --- |
| `AUTOMATION_ENABLED` | `false` on a fresh setup; `true` enables paid dispatch |
| `GITHUB_REPOSITORY`, `TARGET_BRANCH` | Fork and branch that workflows may modify; never set workflow scope to `apache/superset` |
| `GITHUB_ALLOWED_ACTOR`, `TRIGGER_LABEL` | Authorized issue/validation actor and repair label; default label `cognition:repair` |
| `GITHUB_TOKEN` | Server-side GitHub credential; optional for public history, required for workflow writes |
| `DEVIN_ORG_ID`, `DEVIN_API_KEY` | Organization API v3 scope and credential; required for Devin execution |
| `GITHUB_WEBHOOK_SECRET` | Generated shared secret for signed GitHub deliveries |
| `OPERATOR_TOKEN` | Generated owner key for operator commands and the browser’s Execution access expander; never the shared reviewer password |
| `DEVIN_MAX_ACU`, `DEVIN_MAX_SESSIONS` | Fresh-install defaults: 10 ACU per new session, 6 sessions across the ledger's lifetime. Current hosted configuration: 20 ACU / 20 sessions; provider credit and organization limits still apply |
| `SESSION_TIMEOUT_SECONDS` | Default: 7200 seconds per session |
| `POLL_SECONDS`, `BATCH_WINDOW_SECONDS` | Default polling/batching: 30/60 seconds |
| `SCAN_INTERVAL_SECONDS` | Seeds the first discovery schedule (86400 daily; 0 paused). After first startup, edit the durable schedule in Workflows → Schedules & triggers |
| `EVIDENCE_PUBLIC_URL` | Optional HTTPS app origin for public, sanitized evidence copies embedded in PR comments; blank keeps authenticated Devin links |
| `DEPENDABOT_ENABLED` | Default `true`; dependency intake/dispatch remains subject to automation limits |
| `LEARNING_ENABLED` | Default `true`; syncs scoped observations to Devin Knowledge. Turning it off may retire app-owned notes |
| `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID` | Optional evidence delivery; leave both blank to omit Slack |
| `POSTGRES_ADMIN_PASSWORD`, `POSTGRES_APP_PASSWORD`, `POSTGRES_SUPERSET_PASSWORD`, `POSTGRES_READER_PASSWORD` | Generated credentials for provisioning, workflow data, BI metadata and reporting reads |
| `ANALYTICS_SUPERSET_SECRET_KEY`, `ANALYTICS_SUPERSET_ADMIN_PASSWORD`, `ANALYTICS_SUPERSET_SERVICE_PASSWORD` | Generated Superset signing/admin/token-issuer secrets |
| `SUPERSET_INTERNAL_URL` | Default `http://analytics-superset:8088/bi`; API-to-BI connection inside Docker |
| `SUPERSET_PUBLIC_URL` | Default `http://127.0.0.1:8189/bi`; address reachable by the browser |
| `SUPERSET_ALLOWED_ORIGINS` | Exact embedding origins; defaults include local port 8000 |
| `DATABASE_URL` | Directly launched backend processes accept a Postgres SQLAlchemy URL; default Compose constructs its own URL from `POSTGRES_APP_PASSWORD` |
| `AUTOMATION_DATABASE` | Bare SQLite file path for standalone/local SQLite use; `DATABASE_URL` takes precedence if nonempty |

Generated secrets are intentionally absent from `.env.example`; run the helper instead of inventing reusable passwords. Public-host settings are described under AWS below. Database, artifact and private workflow records stay outside Git; the committed public GitHub history seed contains only allowlisted public metadata.

## 2. Recommended: Docker Compose + Postgres + Superset

From the repository root, after configuring `.env`:

```sh
docker compose up --build -d
docker compose ps -a
curl --fail http://127.0.0.1:8000/api/health
curl --fail http://127.0.0.1:8189/bi/health
```

Open [the dashboard](http://127.0.0.1:8000) and choose **Analytics**. No Superset admin login is needed for embedding. Initial image downloads and Superset metadata migrations can take several minutes. `analytics-superset-init` exiting with code **0** is expected; its job is to provision the datasets and five charts per dashboard (monthly and rolling).

| Service | Role |
| --- | --- |
| `cognition` | FastAPI and built React frontend, loopback port 8000 |
| `worker` | Durable workflow processing, external delivery and reconciliation |
| `analytics` | Imports upstream/fork GitHub PR history independently of Devin |
| `postgres` | Postgres 17; `cognition` and `superset_metadata` databases; local diagnostic port 55432 |
| `analytics-redis` | Superset cache |
| `analytics-superset-init` | One-time/idempotent BI metadata and dashboard provisioning |
| `analytics-superset` | Apache Superset 6.1, loopback port 8189 under `/bi` |

A fresh installation starts with no workflow runs. The importer initializes Postgres from the committed public GitHub snapshot and refreshes it; anonymous GitHub requests can hit rate limits. Data age and import errors remain visible. The generated Superset administrator is `cognition-admin`; its password is in local `.env`, and is not required to view embedded charts.

```sh
# Inspect startup failures without dumping environment variables.
docker compose logs --tail=100 cognition analytics analytics-superset-init analytics-superset
# Stop services; named database/artifact volumes remain.
docker compose down
# Rebuild after pulling updated source.
docker compose up --build -d
```

Do not add `--volumes` to `down` unless deliberately deleting the stored data. Existing SQLite installations must use the [offline migration procedure](docs/POSTGRES_SUPERSET.md#existing-sqlite-installation-migration); changing a setting does not migrate records automatically. Back up both Postgres databases and the artifact volume before upgrades.

## 3. Optional: SQLite with Compose or Docker alone

SQLite supports the workflow ledger, memories, publication receipts and imported-history JSON API. **The embedded Superset charts require the Postgres setup above.** In SQLite mode Analytics explicitly reports BI as unavailable; it does not silently substitute fixture charts. The legacy example API is also mounted in SQLite mode and its illustrative workspace is available at `/?demo=1`; the default workspace still shows actual stored records.

Choose one stack on port 8000 at a time. After preparing `.env` and setting the execution scope:

```sh
docker compose -p cognition-sqlite -f compose.sqlite.yaml up --build -d
curl --fail http://127.0.0.1:8000/api/health
docker compose -p cognition-sqlite -f compose.sqlite.yaml down
```

This standalone Compose file starts API, worker and history importer, with a separate `cognition-sqlite-data` volume. It needs no Postgres/Superset credentials. To run alongside the Postgres stack, prefix the SQLite command with `COGNITION_PORT=8002` and visit port 8002. The supplied operator helper always targets port 8000, so use the default port for that helper.

For a single API/frontend container, without workers or Superset:

```sh
docker build -t superset-auto-engineering .
docker volume create cognition-sqlite-data
docker run --rm --name cognition-sqlite-api \
   -p 127.0.0.1:8000:8000 \
   -e AUTOMATION_ENABLED=false \
   -e AUTOMATION_DATABASE=/app/data/automation.db \
   -v cognition-sqlite-data:/app/data \
   superset-auto-engineering
```

That command uses the example fork scope and creates no Devin sessions. For live integrations use Compose, which supplies the configured credentials and separate worker. Direct Python processes support `DATABASE_URL=postgresql+psycopg://...` for Postgres or a **bare file path** in `AUTOMATION_DATABASE` for SQLite. Do not use a `sqlite://` URL here: the companion analytics filename currently expects a filesystem path.

## 4. Connect Devin API v3 and GitHub

1. In the intended Devin organization, open **Settings → Devin API**. Copy its organization ID. Create a service user/API key for shared automation, or use an authorized personal access token for a local take-home. Put the credential in `DEVIN_API_KEY` and the ID in `DEVIN_ORG_ID`. The adapter calls `https://api.devin.ai/v3/organizations/{org_id}/...` with Bearer authentication; a CLI login alone does not configure it. See [Devin authentication](https://docs.devin.ai/api-reference/authentication).
2. Grant `UseDevinSessions`, `ViewOrgSessions` and `ManageOrgSessions` for session creation, readback, attachments and lifecycle management. With learning enabled it also needs `ManageOrgKnowledge` for note read/create/update. Confirm the organization has the intended credit allocation. Consult [v3 permissions](https://docs.devin.ai/api-reference/v3/overview) and [the provider contracts](docs/providers/README.md).
3. Connect the fork in **Devin's own GitHub/repository integration**, with permission to clone, push a branch and open/update PRs. The application does **not** forward `GITHUB_TOKEN` to Devin.
4. Set `GITHUB_TOKEN` for the app separately. A token restricted to the fork needs repository contents, issues and pull-request read/write access for integration branches, issue creation and evidence reports. It needs read access to the public upstream history too. Webhook administration can be done separately in GitHub Settings; the runtime does not need webhook-administration permission. Confirm the fork and target branch exist.
5. Keep `AUTOMATION_ENABLED=false` while checking access. Recreate the API after editing `.env`, then make a read-only API check:

   ```sh
   docker compose up -d cognition
   docker compose exec -T cognition python - <<'PY'
   from app.automation.config import Settings
   from app.automation.providers import Providers
   provider = Providers(Settings.from_env())
   try:
       provider.devin("GET", "sessions", params={"limit": 1})
       print("Devin organization session access succeeded; no session created.")
   finally:
       provider.close()
   PY
   ```

   A successful read checks authentication/read permission, not session creation or an end-to-end fix. `401` usually means missing/expired credentials; `403` means access/role/scope needs checking. Never paste keys into browser code, a PR or logs.
6. When ready to spend the configured credits, set `AUTOMATION_ENABLED=true` and run `docker compose up -d cognition worker`. Existing queued work can dispatch immediately. Create a small issue in the fork, authored by `GITHUB_ALLOWED_ACTOR`, with the `cognition:repair` label. The worker polls eligible issues; to request intake explicitly, use `python3 scripts/cognition_operator.py issue --number <issue-number>`. Inspect progress with `python3 scripts/cognition_operator.py overview` and the dashboard. The application cannot bypass a provider credit limit or an unresolved `needs_attention` hold.

Session creates use a bounded `max_acu_limit`, repository context, tags and a structured result contract. Fresh independent validation must record the exact SHA and accepted provider evidence before the gate is ready. Review readiness is not automatic approval or merging. [Session API](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions) · [PR validation flow](docs/PR_VALIDATION.md) · [Dependabot setup](docs/DEPENDABOT.md).

### GitHub webhooks and optional Slack

For local event-driven intake:

```sh
docker compose -f compose.yaml -f compose.webhook.yaml up -d
```

Expose **only port 8001** through a development tunnel. In the fork's GitHub Settings → Webhooks, use `https://your-tunnel/api/live/webhooks/github`, content type `application/json`, and the `.env` value of `GITHUB_WEBHOOK_SECRET`. Subscribe to **Issues and Pull requests**. Valid signed events are saved to a durable, deduplicated inbox before acknowledgment; the worker processes them with bounded retries and polling provides recovery for eligible missed activity. The gateway rejects other paths. Do not tunnel unauthenticated dashboard port 8000. Temporary tunnels are not permanent hosting.

For Slack, install a bot in the intended workspace, grant the posting/readback permissions required by your channel type, invite it to the channel, and set `SLACK_BOT_TOKEN` plus `SLACK_CHANNEL_ID`. The take-home destination is Nasrudin's **Tech** channel `C0C2NTYCPTR`; use that only with credentials for that workspace. Recreate API/worker after configuring. Reports persist an outbox receipt and confirm delivery before claiming success. Leaving Slack unconfigured does not prevent GitHub evidence delivery.

## Workspace navigation

Five sections keep related features together:

| Section | Features |
|---|---|
| Release gates | Exact-SHA validation, PR evidence, repository lineage and evidence delivery recovery |
| Workflows | Workflow lanes, schedules/manual runs, Devin sessions, Dependabot and durable queue recovery |
| Learning | Repository observations, Devin Knowledge synchronization and later-session reuse |
| Analytics | Superset charts, repository selection, rolling-window comparisons |
| Operations | Provider status, worker health, limits and delivery receipts |

View links can be bookmarked, such as `/#learning` and `/#pull-requests`. The original [design mockup](docs/dashboard-mockup.png) informs the revision-first evidence layout.

## Workspace login

![Workspace login](docs/screenshots/login-desktop.png)

The first visit shows a password-only login page. Configure the shared reviewer password with `python3 scripts/configure_login.py --local-http` for localhost, or omit `--local-http` for HTTPS hosting. The helper stores a salted scrypt hash in ignored `.env`; the password is never built into the frontend or repository. Recreate the API container after changing it.

Sessions use HttpOnly cookies, expire after eight hours, and are stored as token hashes in Postgres or SQLite. **Sign out** revokes the session; changing the password invalidates existing sessions after API restart. Login attempts are limited to 20 per minute across the deployment. Private API data and embedded Superset are protected independently of the page. Reviewer login does not grant privileged operator actions, which still need `OPERATOR_TOKEN`. Superset is gated through the public Caddy ingress; its direct localhost development port remains available for local debugging.

Run `backend/.venv/bin/python scripts/test_login_e2e.py` after building the frontend to test login with a disposable password and isolated databases; CI runs this check automatically.

The public Compose overlay always enables authentication and Secure cookies, and refuses to start without a valid configured hash. Local-only unauthenticated development remains possible with `AUTH_ENABLED=false`; never expose that configuration publicly. `/api/health`, login/session endpoints, and the separately signed GitHub webhook remain reachable without a reviewer cookie.

## 5. AWS with CloudFormation and the custom domain

### Low-cost deployment (preferred)

Use [the Lightsail template](infra/cloudformation/lightsail.yaml) for a low-traffic installation on one VM: FastAPI/React, Postgres, Superset and Redis. The 2 GiB Linux bundle includes 60 GB disk and public IPv4 at **US$12/month**, before taxes, excess transfer and Devin usage. Scheduled snapshots and backups are disabled for this demo; no free-tier credits are assumed. A 4 GiB bundle costs US$24/month if measured load needs more headroom. [AWS pricing](https://aws.amazon.com/lightsail/pricing/).

Target region: **ap-southeast-2 (Sydney)**, approved for this demo. The current AWS project permits only Sydney; a standard AWS account is needed to choose a US region. The template defaults to the Sydney `small_3_2` bundle.

The template installs Docker/Compose, 4 GiB swap and a pinned source revision. [compose.small.yaml](compose.small.yaml) bounds memory and logs; [the host scripts](infra/host/) provide startup and local health checks. Automated backups are intentionally disabled; losing the host can lose its data. This is a single-server deployment, with downtime during host failure/recovery, not high availability. The Sydney application is live with Cloudflare DNS, valid HTTPS, reviewer authentication, embedded Superset and signed GitHub webhook delivery verified. See [deployment evidence](docs/analysis/sydney-deployment.json).

Follow [the low-cost deployment and recovery runbook](docs/LOW_COST_AWS.md), including migration of the existing execution ledger before enabling any automation. Do not run candidate-validation databases/services on this small dashboard VM.

### Alternative: EC2 in an existing VPC

[infra/cloudformation/demo-host.yaml](infra/cloudformation/demo-host.yaml) provisions an **EC2 demo host**, encrypted persistent root disk, Elastic IP, web-only security group and SSM administration role in an existing VPC/public subnet. Postgres runs in Docker on that host; this template does **not** provision RDS, high availability, backups, DNS or a ready application. Source/configuration setup remains explicit. The template is locally linted; it has not been deployed to AWS.

Use an intentionally selected AWS account/profile, region and budget. Do not assume an unrelated configured profile is the correct account. This provisions billable resources. Install AWS CLI and the Session Manager plugin, choose a public subnet with Internet routing, then review a change set:

```sh
export AWS_PROFILE=your-profile
export AWS_REGION=your-region
export COGNITION_VPC_ID=vpc-replace-me
export COGNITION_SUBNET_ID=subnet-replace-me
aws sts get-caller-identity
aws cloudformation validate-template \
   --template-body file://infra/cloudformation/demo-host.yaml
aws cloudformation deploy \
   --template-file infra/cloudformation/demo-host.yaml \
   --stack-name superset-devin \
   --capabilities CAPABILITY_IAM \
   --parameter-overrides VpcId="$COGNITION_VPC_ID" PublicSubnetId="$COGNITION_SUBNET_ID" \
   --no-execute-changeset
```

Inspect that change set in CloudFormation. Execute it only after checking the account, region, instance/disk costs and planned replacements. When creation completes, read its outputs:

```sh
aws cloudformation describe-stacks --stack-name superset-devin --query 'Stacks[0].Outputs'
aws ssm start-session --target <InstanceId-output>
```

Stack completion means infrastructure exists, not that the app or Docker bootstrap is ready. In the SSM terminal check `/var/log/cloud-init-output.log` and `sudo systemctl status docker`. Follow the [Docker Compose Linux installation instructions](https://docs.docker.com/compose/install/linux/) to install the plugin system-wide; verify `sudo docker compose version` is 2.20+. The host bootstrap installs Docker, Git and Python, but does not install the app or credentials.

On that host:

```sh
sudo -i
git clone https://github.com/Nasdin/superset-auto-engineering.git /opt/cognition
cd /opt/cognition
# Select the reviewed release/commit before deploying.
cp .env.example .env
python3 scripts/configure_local_postgres.py
# Edit scope/provider settings before first startup; initially keep automation disabled.
python3 scripts/configure_login.py
```

Put the generated reviewer password hash and these values in the host's ignored `.env`:

```dotenv
PUBLIC_HOST=superset-devin.nasrudinsalim.com
SUPERSET_PUBLIC_URL=https://superset-devin.nasrudinsalim.com/bi
SUPERSET_ALLOWED_ORIGINS=https://superset-devin.nasrudinsalim.com
AUTH_ENABLED=true
AUTH_COOKIE_SECURE=true
REVIEWER_PASSWORD_HASH=<generated by configure_login.py>
```

Create a **DNS-only Cloudflare A record** for `superset-devin` pointing to `PublicIPv4` from the stack outputs. Then, from `/opt/cognition`:

```sh
docker compose -f compose.yaml -f compose.public.yaml up --build -d
docker compose -f compose.yaml -f compose.public.yaml logs --tail=100 ingress
```

Caddy obtains HTTPS certificates once DNS and ports 80/443 work. The reviewer login protects the dashboard and `/bi`; login/session routes and minimal health checks stay public, and the GitHub POST webhook verifies its own signature. Keep database/API/BI diagnostic ports loopback-only. Run operator commands through SSM against local port 8000 with the separate operator token.

Verify public HTTPS, reviewer login, all five guest charts in each cadence, repository filters and restart persistence before updating the permanent GitHub webhook URL. [Full deployment/recovery guide](docs/AWS_DEPLOYMENT.md). Host replacement does **not** migrate Docker volumes. The root disk is retained after instance termination, so stack deletion is not a full data cleanup; retained disks continue to incur charges. Back up both databases/artifacts and plan recovery before replacing a host.

## Development, tests and architecture

The application uses FastAPI with explicit thread-pool boundaries for synchronous database/provider I/O, and React 19/TypeScript/Vite with lazy pages, error isolation and bounded requests. Database pools and query waits are bounded for the small deployment. The [architecture guide](docs/CODE_QUALITY.md) explains factories, service/provider boundaries, async usage, Superset embedding and the changes needed before distributing workers across hosts.

Python 3.12 and Node 22 are used in the Docker build. For backend-only development, the default file adapter works without Postgres; full analytics requires the Compose BI stack. Standalone Python does not automatically load `.env`: explicitly export the needed values using your development environment's dotenv loader. Use host-mapped Postgres port 55432 and BI port 8189 instead of Docker service hostnames. For Vite on port 5173, add its exact origin to `SUPERSET_ALLOWED_ORIGINS` and rerun Superset initialization to update the dashboard allowlist.

```sh
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/ruff check backend
backend/.venv/bin/ruff format --check backend
backend/.venv/bin/pytest --cov --cov-fail-under=80 -q
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend exec playwright install chromium
npm --prefix frontend run test:e2e
```

The default test suite uses isolated databases and fake providers. Real Postgres tests need an explicit disposable `TEST_DATABASE_URL` ending in `_test` and the reporting role; [test setup](docs/POSTGRES_SUPERSET.md#database-tests). CI supplies that database. The separate live embedded BI check is:

```sh
cd frontend
E2E_BASE_URL=http://127.0.0.1:8000 SUPERSET_ANALYTICS_E2E=1 npx playwright test tests/superset-analytics.spec.ts
```

Analytics compares **Fixes, Features, Bots and Other** across seven calendar months or rolling 7–180 day windows. It measures commits per PR, median merge hours, post-review commit rework and added/removed lines, with per-metric sample coverage. A dotted **21 September 2026** rollout marker separates baseline from later observations. The effort-saved calculator uses editable assumptions and completed Devin work; it never equates waiting time with engineering effort. [Design concepts and metric definitions](docs/design/ANALYTICS.md). Upstream/fork selection, six-month/previous/custom baselines, author/label/branch/work-type filters and tracked-work attribution remain available. Time to merge is elapsed creation-to-merge time grouped by merge date; incomplete/small cohorts remain visible and do not establish a causal Devin improvement. [Metric definitions and SQL](docs/POSTGRES_SUPERSET.md) · [code boundaries and tests](docs/CODE_QUALITY.md).

The local BI/storage verification is [recorded here](docs/analysis/superset-postgres-verification.json). It is distinct from repaired-candidate acceptance, which has its own [public validation report](https://github.com/Nasdin/superset/pull/4#issuecomment-5751674737). See [the continuation checkpoint](docs/CONTINUE.md) for workflow evidence and remaining presentation work.


## Schedules, manual work and release gates

Open **Workflows → Schedules & triggers**. The page shows the saved cadence, next due time, discovery history, repository triggers, worker health and session capacity. Expand **Execution access** and enter the `OPERATOR_TOKEN` from your private `.env` to run work or edit schedules. It stays only in tab memory for 15 minutes and disappears on refresh. The reviewer password grants viewing access, not paid execution.

- **Edit schedule:** hourly, every six hours, daily or weekly; enable/pause persists in Postgres or SQLite. Saving sets the next tick one full interval ahead. Missed ticks coalesce; an active scan prevents duplicates.
- **Run discovery now:** creates a separate manual intent. Network retries use the same request ID. Existing issue/PR intake uses the same scope and label checks as webhooks.
- **Repository events:** signed GitHub issues and PR events enqueue eligible repairs, Dependabot preparation and independent validation. Periodic readback recovers missed deliveries. Only the configured fork and release branch are writable.
- **Learning:** repository observations sync to Devin Knowledge. The timeline shows recorded observations and confirmed memory supplied to later sessions, linked to their validation outcome. This does not claim model retraining or causal productivity improvements.
- **Release gates:** a fresh Devin session builds the exact integration/PR SHA in its own isolated VM, starts Superset and its databases, exercises the browser and functional APIs with curl, and runs regression tests with scoped coverage. The BI Superset serving analytics is a separate runtime; it is not candidate-validation proof. No second always-on AWS VM is necessary.

For PRs to show images without a Devin login, set `EVIDENCE_PUBLIC_URL=https://YOUR_APP_DOMAIN` and recreate the app and worker. The worker downloads only provider-confirmed attachments through the organization API, redacts known credentials from text, and stores immutable PNG/MP4/plaintext copies in the shared artifact volume. These copies are deliberately public at `/public-evidence/<content-hash>.<extension>`; the dashboard and other APIs retain login protection. Use synthetic test data and sanitize captures at source. Public files are not backed up in this demo; deleting the host can break old evidence links.

The gate checks session independence, current candidate SHA, six required checks, artifact ownership and structured API/test/coverage evidence. A passing gate prepares a human review; it never merges automatically. A provider suspension or unknown outcome stays visible and blocks further paid dispatch until reconciled. **Resume same session** preserves the existing provider session and budget; it does not create a replacement.

Older sessions with an immutable v1 output schema can provide a same-SHA `evidence-report.json` attachment. It must agree with the final session verdict and pass the same v2 gate. To reassess a completed legacy session, run `PYTHONPATH=backend python scripts/recover_validation_handoff.py --job JOB_ID` in the configured runtime. This reads existing evidence; it cannot start paid work. Revised reports get distinct durable publication receipts, preserving the earlier failed-gate history.

See [challenge acceptance and five-minute demo plan](docs/CHALLENGE_ACCEPTANCE.md).


## Reliability when components fail

**Workflows** and **Release gates** show queue health, bounded retries, dead letters, provider/credit holds, uncertain outcomes and pending evidence delivery. Expand **Recovery & durability** to inspect the next retry and recover an eligible record with the owner's operator key. Validation acceptance, confirmed report delivery and human approval remain separate states.

- **Persist before proceeding:** signed GitHub intake, jobs, schedules, recovery state and publication receipts are stored in Postgres (or local SQLite). Restarting a container preserves them when the existing volumes remain.
- **Retry selectively:** safe observations and known rejected requests retry up to five failed attempts with exponential backoff and jitter. Rate limits honor `Retry-After`; circuit breakers pause repeated provider failures. Expired credentials and exhausted credits remain visible holds until repaired.
- **Protect ambiguous effects:** an unconfirmed paid session creation or report send is not automatically repeated. Recovery retains the job/session ID and checks existing receipts. Dead letters require operator attention; there is no force-replay control for uncertain writes.
- **Keep observing:** disabling `AUTOMATION_ENABLED` stops new paid dispatch while retaining observation, delivery and freshness checks. It does not cancel an already-running provider session.
- **Recover within the deployment's limits:** one worker uses a shared-volume lock; database reconnects back off and worker heartbeat is observable. This one-VM demo has no high availability or enabled backups. Database/disk loss is outside restart durability.

The hosted application now permits **20 total sessions and 20 ACU per newly created session**. Separately, the Devin provider's default **Message usage** limit was raised from **$20 to $40**, and the existing dependency session's provider cap from **$10 to $20**. Dollar caps and application ACU/session limits are independent controls; changing one does not update the others or purchase credits. Other existing session caps are not automatically increased. Fresh clones retain conservative app defaults. Check the current provider account and queue before increasing capacity.

See [the reliability design and operational recovery runbook](docs/RESILIENCE.md) for failure behavior, provider recovery, dead-letter replay, publication confirmation and explicitly unimplemented production improvements.
