# Superset Auto Engineering

Superset analyzing Superset: a FastAPI + React/TypeScript control plane for GitHub history, bounded Devin engineering workflows, and independent validation evidence. **Postgres is the default runtime database.** Apache Superset renders the analytics dashboard from read-only Postgres reporting views. SQLite is supported for a smaller local workflow/API setup.

Issues and Dependabot PRs → Devin implementation → exact candidate SHA → a fresh validation session → screenshots, API transcripts, logs and test evidence → GitHub/Slack report → human review.

## Where it runs

| Environment | Address | Status |
| --- | --- | --- |
| Current local dashboard | [http://127.0.0.1:8000](http://127.0.0.1:8000) | Running locally; open **Analytics** for embedded Superset |
| Local BI Superset | [http://127.0.0.1:8189/bi](http://127.0.0.1:8189/bi) | Separate from candidate-validation Superset |
| Planned AWS dashboard | `https://superset-devin.nasrudinsalim.com` | **Not deployed**; DNS did not resolve when checked September 20, 2026 |
| Planned public Superset | `https://superset-devin.nasrudinsalim.com/bi` | Prepared routing; not a live public service |
| Public source | [Nasdin/superset-auto-engineering](https://github.com/Nasdin/superset-auto-engineering) | Application code, documentation and CI |

The local addresses above refer to the computer running Docker. No AWS account/region has been selected for this project. A [CloudFormation template](infra/cloudformation/demo-host.yaml) and deployment steps below prepare the AWS host; they do not imply a deployed application.

[Live analytics screenshot](docs/images/superset-analytics-live.png) · [architecture and migration](docs/POSTGRES_SUPERSET.md) · [product story/slides](docs/README.md)

## 1. Clone and configure `.env`

Prerequisites: Git, Python 3 for the credential helper, Docker Engine or Docker Desktop, and the Docker Compose plugin **2.20 or newer** (the default stack uses `include`). Node and local Python packages are not needed for Docker builds. The full stack runs several containers; allow sufficient Docker memory for Superset, Postgres and a frontend build.

```sh
git clone https://github.com/Nasdin/superset-auto-engineering.git
cd superset-auto-engineering
cp .env.example .env
python3 scripts/configure_local_postgres.py
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
| `OPERATOR_TOKEN` | Generated token for local operator commands |
| `DEVIN_MAX_ACU`, `DEVIN_MAX_SESSIONS` | Defaults: 10 ACU per session, 6 sessions across the ledger's lifetime |
| `SESSION_TIMEOUT_SECONDS` | Default: 7200 seconds per session |
| `POLL_SECONDS`, `BATCH_WINDOW_SECONDS` | Default polling/batching: 30/60 seconds |
| `SCAN_INTERVAL_SECONDS` | Default: 86400; `0` disables scheduled discovery |
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

Open [the dashboard](http://127.0.0.1:8000) and choose **Analytics**. No Superset admin login is needed for embedding. Initial image downloads and Superset metadata migrations can take several minutes. `analytics-superset-init` exiting with code **0** is expected; its job is to provision the datasets and six charts.

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

Expose **only port 8001** through a development tunnel. In the fork's GitHub Settings → Webhooks, use `https://your-tunnel/api/live/webhooks/github`, content type `application/json`, and the `.env` value of `GITHUB_WEBHOOK_SECRET`. Subscribe to **Issues and Pull requests**. Signed events are deduplicated; polling provides recovery. The gateway rejects other paths. Do not tunnel unauthenticated dashboard port 8000. Temporary tunnels are not permanent hosting.

For Slack, install a bot in the intended workspace, grant the posting/readback permissions required by your channel type, invite it to the channel, and set `SLACK_BOT_TOKEN` plus `SLACK_CHANNEL_ID`. The take-home destination is Nasrudin's **Tech** channel `C0C2NTYCPTR`; use that only with credentials for that workspace. Recreate API/worker after configuring. Reports persist an outbox receipt and confirm delivery before claiming success. Leaving Slack unconfigured does not prevent GitHub evidence delivery.

## 5. AWS with CloudFormation and the custom domain

### Low-cost deployment (preferred)

Use [the Lightsail template](infra/cloudformation/lightsail.yaml) for a low-traffic installation on one VM: FastAPI/React, Postgres, Superset and Redis. The 2 GiB Linux bundle includes 60 GB disk and public IPv4 at **US$12/month**, before snapshots, taxes, excess transfer and Devin usage. Daily snapshots cost extra; no free-tier credits are assumed. A 4 GiB bundle costs US$24/month if measured load needs more headroom. [AWS pricing](https://aws.amazon.com/lightsail/pricing/).

Target region: **us-east-1 (Northern Virginia)** for US reviewers. Verify account access first: AWS's simplified project experience may restrict all projects to a single region. Creating another project does not remove that organization policy. Do not silently deploy in another region or activate irreversible account features to bypass the restriction.

The template installs Docker/Compose, 4 GiB swap and a pinned source revision. [compose.small.yaml](compose.small.yaml) bounds memory and logs; [the host scripts](infra/host/) provide startup, logical backups and local health checks. The daily AWS snapshot captures those dumps off-host. This is a single-server deployment, with downtime during host failure/recovery, not high availability. Public deployment remains pending until the account/region and live acceptance checks are complete.

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
docker run --rm -it caddy:2.10-alpine caddy hash-password
```

Put the generated reviewer password hash and these values in the host's ignored `.env`:

```dotenv
PUBLIC_HOST=superset-devin.nasrudinsalim.com
SUPERSET_PUBLIC_URL=https://superset-devin.nasrudinsalim.com/bi
SUPERSET_ALLOWED_ORIGINS=https://superset-devin.nasrudinsalim.com
REVIEWER_USER=reviewer
REVIEWER_PASSWORD_HASH='<paste the generated hash; preserve single quotes>'
```

Create a **DNS-only Cloudflare A record** for `superset-devin` pointing to `PublicIPv4` from the stack outputs. Then, from `/opt/cognition`:

```sh
docker compose -f compose.yaml -f compose.public.yaml up --build -d
docker compose -f compose.yaml -f compose.public.yaml logs --tail=100 ingress
```

Caddy obtains HTTPS certificates once DNS and ports 80/443 work. The reviewer login protects the dashboard and `/bi`; only the signed GitHub POST endpoint bypasses that login. Keep database/API/BI diagnostic ports loopback-only. Run operator commands through SSM against local port 8000 with the separate operator token.

Verify public HTTPS, reviewer login, all six guest charts, repository filters, restart persistence and a restored backup before updating the permanent GitHub webhook URL. [Full deployment/recovery guide](docs/AWS_DEPLOYMENT.md). Host replacement does **not** migrate Docker volumes. The root disk is retained after instance termination, so stack deletion is not a full data cleanup; retained disks continue to incur charges. Back up both databases/artifacts and plan recovery before replacing a host.

## Development, tests and architecture

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

Analytics supports upstream/fork selection, rolling 7–180 day windows, six-month/previous/custom baselines, author/label/branch/work-type filters and tracked-work attribution. Time to merge is elapsed creation-to-merge time grouped by merge date; incomplete/small cohorts remain visible and do not establish a causal Devin improvement. [Metric definitions and SQL](docs/POSTGRES_SUPERSET.md) · [code boundaries and tests](docs/CODE_QUALITY.md).

The latest local BI/storage verification is [recorded here](docs/analysis/superset-postgres-verification.json). It is distinct from repaired-candidate acceptance: the previously observed independent Devin validation was blocked at its configured usage limit. See [the continuation checkpoint](docs/CONTINUE.md) for that workflow's evidence and remaining work.
