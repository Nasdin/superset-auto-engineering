FROM postgres:17
COPY infra/postgres-init.sh /docker-entrypoint-initdb.d/10-cognition.sh
RUN chmod 0644 /docker-entrypoint-initdb.d/10-cognition.sh
