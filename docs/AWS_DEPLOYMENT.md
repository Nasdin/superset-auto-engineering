# AWS deployment preparation

For the preferred small Lightsail VM, use the [low-cost deployment runbook](LOW_COST_AWS.md) and [Lightsail CloudFormation template](../infra/cloudformation/lightsail.yaml). The requested region is **us-east-1**. The EC2 alternative below remains available.

Target: **https://superset-devin.nasrudinsalim.com**, with Superset under `/bi`. Local Postgres and embedded Superset are implemented. AWS provisioning, public DNS, certificates and public browser acceptance have **not** been performed. The intended AWS account/profile, region and monthly budget must be selected first; the existing `nextvestment` profile is not assumed to be the intended account.

## CloudFormation host template

Use [infra/cloudformation/demo-host.yaml](../infra/cloudformation/demo-host.yaml) and the [README deployment walkthrough](../README.md#5-aws-with-cloudformation-and-the-custom-domain). The template provisions a host in an existing public subnet, with encrypted disk, Elastic IP, SSM role and ports 80/443. It does not deploy application code, RDS, DNS or backups. CloudFormation completion is not application readiness. Local linting is the current validation boundary; no stack has been deployed.

Instance termination retains its root disk; replacement does not migrate volumes or secrets to the new host. Review replacements and backups before executing a change set. Retained disks need deliberate cleanup to stop storage charges.

## Four-day demo topology

Use one EC2 host with Docker Compose, an encrypted persistent EBS volume, a stable public address and the optional Caddy ingress. Postgres is containerized on that durable disk. This keeps the take-home small; it is a single-host demo without high availability. For an enduring deployment, move both databases to private RDS Postgres with managed backups, introduce versioned application migrations, and use managed application hosting. Postgres database separation already avoids an SQLite redesign at that point.

Choose the instance and disk after confirming the account and budget. Allow inbound 80/443 only; administration should use SSM. Ports 8000, 8189 and 55432 are loopback-bound and must not be exposed. Store `.env` with mode 0600 on the host, outside Git. Retain independent off-host database and artifact backups, and verify a restore before claiming durable operation. A Docker volume alone is not a backup.

## Domain and HTTPS

1. Provision the selected host and encrypted storage. Clone the reviewed public repository, install Docker with Compose, copy `.env.example`, and generate fresh host credentials with `scripts/configure_local_postgres.py`. Keep paid automation disabled until live provider scopes and limits are verified.
2. Set these ignored environment values:

   ```dotenv
   PUBLIC_HOST=superset-devin.nasrudinsalim.com
   SUPERSET_PUBLIC_URL=https://superset-devin.nasrudinsalim.com/bi
   SUPERSET_ALLOWED_ORIGINS=https://superset-devin.nasrudinsalim.com
   REVIEWER_USER=reviewer
   # Single-quote the hash in .env to preserve literal dollar signs.
   REVIEWER_PASSWORD_HASH='<generated bcrypt hash>'
   ```

   Generate the hash interactively using `docker run --rm -it caddy:2.10-alpine caddy hash-password`. Superset's internal URL stays `http://analytics-superset:8088/bi`. Reviewers use the outer HTTPS login; operator commands run through SSM against loopback port 8000 with the application Bearer token, since the reviewer gateway uses HTTP Basic authentication. Share credentials privately.
3. Add a DNS-only Cloudflare A record for the subdomain to the host's public address. The existing domain uses Cloudflare nameservers. No DNS record was changed during local implementation.
4. Run `docker compose -f compose.yaml -f compose.public.yaml up --build -d`. Caddy obtains TLS certificates once public DNS and ports resolve correctly. Never expose the unauthenticated local dashboard directly.
5. Verify anonymous dashboard/BI requests require login, authenticated embedding loads all six charts, upstream/fork selections remain isolated, incomplete windows remain honest and public database ports are unreachable. Verify restart persistence and restore a backup into an isolated database. Only then switch the GitHub webhook to the exact signed endpoint `/api/live/webhooks/github`, send a real signed test delivery and read back its durable receipt.

Only the signed GitHub POST endpoint bypasses reviewer authentication. Caddy retains the `/bi` prefix for Superset's application-root middleware. The browser receives only a short-lived guest token; the service issuer password remains in FastAPI. API health does not imply a successful BI query or completed Devin validation.

## Backup / recovery

Use `pg_dump -Fc` for both `cognition` and `superset_metadata`, preserve database role definitions securely, and back up the artifact volume and deployment secrets separately. Encrypt off-host backups and limit their access: the ledger contains private workflow details. Rehearse restoration into separate databases/volumes with automation disabled; verify job/publication counts, receipt readback and six guest charts before cutover. Never publish live SQL dumps or `.env` in the public repository.

References: [Superset embedding](https://superset.apache.org/user-docs/using-superset/embedding/), [Caddy authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth), [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
