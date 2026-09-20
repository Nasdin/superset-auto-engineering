#!/bin/bash
# Daily logical dumps are captured by the later Lightsail off-host snapshot.
set -euo pipefail
umask 077
exec 9>/run/cognition-backup.lock
flock -n 9 || exit 0
root=/opt/cognition/backups
install -d -m 0700 "$root"
backup_dir=$(mktemp -d "$root/.pending-XXXXXXXX")
trap 'rm -rf -- "$backup_dir"' EXIT
for database in cognition superset_metadata; do
  cognition-compose exec -T postgres pg_dump -U postgres -Fc "$database" > "$backup_dir/$database.dump"
  test -s "$backup_dir/$database.dump"
done
cognition-compose exec -T postgres pg_dumpall -U postgres --globals-only > "$backup_dir/roles.sql"
cp /opt/cognition/app/.env "$backup_dir/config.env"
cognition-compose exec -T cognition sh -c 'mkdir -p /app/data/artifacts && tar -C /app/data -czf - artifacts' > "$backup_dir/artifacts.tar.gz"
git -C /opt/cognition/app rev-parse HEAD > "$backup_dir/revision.txt"
(cd "$backup_dir" && sha256sum ./* > SHA256SUMS)
# Retain one complete generation to keep snapshots incremental and disk use bounded.
rm -rf -- "$root/previous"
if [ -d "$root/latest" ]; then mv "$root/latest" "$root/previous"; fi
mv "$backup_dir" "$root/latest"
date -u +%FT%TZ > "$root/last-success"
echo 'Cognition logical backup completed; off-host protection requires a successful Lightsail snapshot.'
