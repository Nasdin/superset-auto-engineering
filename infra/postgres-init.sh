#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres --set=ON_ERROR_STOP=1 \
  --set=app_password="$POSTGRES_APP_PASSWORD" \
  --set=metadata_password="$POSTGRES_SUPERSET_PASSWORD" \
  --set=reader_password="$POSTGRES_READER_PASSWORD" <<'SQL'
CREATE ROLE cognition_app LOGIN PASSWORD :'app_password';
CREATE DATABASE cognition OWNER cognition_app;
REVOKE ALL ON DATABASE cognition FROM PUBLIC;
CREATE ROLE superset_metadata LOGIN PASSWORD :'metadata_password';
CREATE DATABASE superset_metadata OWNER superset_metadata;
REVOKE ALL ON DATABASE superset_metadata FROM PUBLIC;
CREATE ROLE cognition_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE cognition TO cognition_reader;
ALTER ROLE cognition_reader SET default_transaction_read_only = on;
SQL
