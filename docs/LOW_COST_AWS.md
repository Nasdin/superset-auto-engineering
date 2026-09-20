# Low-cost AWS deployment

Target: `https://superset-devin.nasrudinsalim.com`, region **ap-southeast-2 (Sydney)**, approved for this demo because the current AWS project is region-restricted. The VM and application are provisioned; DNS, public HTTPS, embedded-chart browser acceptance and webhook cutover remain pending. See [current evidence](analysis/sydney-deployment.json). A created project or a completed CloudFormation stack is not evidence of a live application.

## Capacity and cost

The preferred starting point is Lightsail `small_3_2`: 2 GiB RAM, 2 burstable CPUs, 60 GB SSD and public IPv4, US$12/month before taxes and transfer overages. Scheduled backups and snapshots are disabled for this demo. The 4 GiB `medium_3_2` option is US$24/month. Verify the available bundle and price in the target account/region before execution. [AWS pricing](https://aws.amazon.com/lightsail/pricing/).

One VM avoids a load balancer, NAT gateway, managed database and a serverless rewrite. The running Compose memory ceilings total 1,536 MiB; host swap is 4 GiB. The initial BI migration has a separate 768 MiB limit and image builds must run serially. These are a starting capacity budget, not a throughput guarantee. Real charts, concurrent requests, swap pressure and OOM events must be checked on the deployed VM. A bundle upgrade requires a replacement instance and data migration; CloudFormation cannot change the bundle in place.

No automatic snapshots or database backup timers are enabled. Host failure can lose the database and evidence stored on that host. Monitor actual storage and transfer charges. Stopping the VM does not end its bundle charges. The template retains the VM and static IP on stack deletion to protect data; those retained resources continue billing. Delete them deliberately when the demo is finished; export data first if it needs to be preserved.

## Provision the reviewed revision

Use a dedicated AWS profile with temporary console sign-in. Never use an unrelated profile or create a permanent root access key.

```sh
aws login --profile cognition-production --region ap-southeast-2
export AWS_PROFILE=cognition-production AWS_REGION=ap-southeast-2
aws sts get-caller-identity
aws lightsail get-bundles --query 'bundles[?bundleId==`small_3_2`].[bundleId,price,ramSizeInGb,diskSizeInGb]'
aws cloudformation validate-template --template-body file://infra/cloudformation/lightsail.yaml
aws cloudformation deploy \
  --stack-name superset-devin \
  --template-file infra/cloudformation/lightsail.yaml \
  --parameter-overrides AdminCidr=YOUR_PUBLIC_IPV4/32 ReleaseSha=REVIEWED_40_CHARACTER_SHA \
  --no-execute-changeset
```

Review the exact account, region, resources and cost before executing the change set. The template allows web ports 80/443 and SSH only from the selected IPv4 plus AWS's browser SSH service. Database/API/BI ports remain loopback-only. It creates no IAM users or access keys and places no credentials in user data.

After creation, read `InstanceName` and `PublicIPv4` from stack outputs. Connect through Lightsail's browser SSH or the scoped SSH path. Wait for `sudo cloud-init status --wait`, check `/var/log/cloud-init-output.log`, and verify `/opt/cognition/bootstrap-ready`, Docker Compose and swap. Source lives in `/opt/cognition/app`. The bootstrap installs units but intentionally does **not** start the application before configuration and migration.

Changing `ReleaseSha` in CloudFormation does not redeploy an existing VM. Updates must explicitly check out the reviewed revision, rebuild and restart, with a reviewed rollback plan. An optional manual export can preserve data before risky updates.

## Configure and migrate

1. Keep `AUTOMATION_ENABLED=false`. Stop or disable the old worker before transferring execution history. A fresh ledger resets session accounting and discards holds; it must not be used to restart paid work.
2. Transfer the ignored configuration over authenticated SSH, preserving the Superset encryption key if metadata is migrated. Update public URLs below. Keep the file owned by root with mode 0600, under the root-only `/opt/cognition` directory. Never paste secrets into CloudFormation, GitHub, logs or user data.
3. If this is a genuinely new install, copy `.env.example` and run `python3 scripts/configure_local_postgres.py`. Review repository, branch, organization and session limits **before** first startup. Existing installs must restore both Postgres databases and artifacts using the migration/recovery procedure; merely copying `.env` does not transfer history.
4. Run `python3 scripts/configure_login.py` to set the reviewer password privately. It writes only a salted scrypt hash into ignored `.env`; there is no universal password in source.

```dotenv
AUTOMATION_ENABLED=false
ENABLE_DEMO=false
PUBLIC_HOST=superset-devin.nasrudinsalim.com
SUPERSET_PUBLIC_URL=https://superset-devin.nasrudinsalim.com/bi
SUPERSET_ALLOWED_ORIGINS=https://superset-devin.nasrudinsalim.com
AUTH_ENABLED=true
AUTH_COOKIE_SECURE=true
REVIEWER_PASSWORD_HASH=<generated by configure_login.py>
```

Build from the root shell, serially to reduce peak RAM:

```sh
cd /opt/cognition/app
COMPOSE_PARALLEL_LIMIT=1 cognition-compose build
# Start Postgres, restore databases/history if migrating, then initialize BI and start the app.
cognition-compose up -d postgres
# Restore procedure below; omit only for a new install.
systemctl enable --now cognition-app.service
cognition-compose ps -a
systemctl enable --now cognition-check.timer
systemctl list-timers 'cognition-*'
```

Do not enable the paid worker during deployment verification. Read-only GitHub history import and charts can run while automated execution is disabled. Preserve `needs_attention` holds and budget receipts during migration.

## Domain and acceptance

Create only the `superset-devin` DNS-only A record in Cloudflare, pointing to the new static IPv4. Leave other domain records and zone-wide TLS settings unchanged. Caddy obtains a valid HTTPS certificate; the dashboard and Superset require reviewer login. Login/session routes and minimal health checks stay public. The GitHub POST webhook verifies its own signature.

Acceptance requires all of:

- Valid HTTPS; anonymous dashboard and `/bi` require authentication; diagnostic ports are inaccessible externally.
- All six embedded charts load, agree with the Postgres-backed API, and respect upstream/fork and sliding-window filters.
- Service and host restart persistence; no OOM kills, disk exhaustion or sustained swap thrashing under the expected low concurrent load.
- Existing job/publication/memory/audit counts and budget holds survive migration.
- Automatic snapshots and scheduled database backups remain disabled as requested for the demo.
- GitHub webhook delivery is signed, deduplicated and read back from the durable ledger; move it only after acceptance.

Only after these checks record the deployed SHA, stack/region, public URL and evidence in the deployment status. A single VM remains a single point of failure. This setup does not claim high availability or an uptime SLA.

## Optional manual migration and recovery

The demo deployment does not install or enable `cognition-backup.timer`, and the template explicitly disables Lightsail automatic snapshots. The retained backup scripts are optional manual migration tools, not active schedules. To export data manually, run `infra/host/backup.sh` from the root shell. The script uses `pg_dump -Fc` for both databases, saves roles, artifacts, configuration and revision with checksums, and retains two local generations. Failed dumps do not replace the last completed backup. These files contain secrets and private workflow history; keep them private. They are not off-host protection by themselves.

Automatic snapshots are disabled. If you choose to create a **manual** snapshot before host replacement or deletion, verify it separately; automatic snapshots are deleted when their source instance is deleted. [AWS snapshot retention](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-configuring-automatic-snapshots.html).

For a logical restore, use a clean isolated host with automation disabled, original configuration/encryption key, matching database roles and the reviewed release. Start only Postgres. Verify `sha256sum -c SHA256SUMS` in the backup directory, then restore `cognition.dump` and `superset_metadata.dump` to their corresponding empty databases using `pg_restore --exit-on-error`. Restore the artifact archive to `/app/data/artifacts`, preserve application user ownership, initialize the BI grants and verify ledger counts and charts. Do not run the worker until scope, receipt history and session limits have been checked.

A snapshot clone includes Docker restart policies and saved environment. If automation was enabled when it was captured, booting the clone may immediately resume paid work. Before restoring such a snapshot, revoke/disable provider execution credentials or ensure network quarantine; stop all cloned containers, set automation false, and inspect history before permitting outbound provider calls. Keep the original and restored worker from running concurrently.

`cognition-check.timer` checks API, BI and root-disk pressure every five minutes, with failures in the system journal. It is **not external alerting**, an automatic repair system, or proof of successful AWS snapshots. Configure an external notification destination before unattended production operation; do not equate a healthy local check with a verified recovery path.
