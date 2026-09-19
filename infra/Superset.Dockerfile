ARG SUPERSET_IMAGE=cognition-superset:c37118ed
FROM ${SUPERSET_IMAGE}
USER root
# MySQL engine result-type decoding imports MySQLdb even with a PyMySQL URI.
# mysqlclient matches the pinned baseline's development requirements.
RUN /app/docker/apt-install.sh build-essential pkg-config default-libmysqlclient-dev \
    && uv pip install pymysql==1.1.2 mysqlclient==2.2.6
USER superset
