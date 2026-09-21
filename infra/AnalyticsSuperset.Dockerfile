FROM apache/superset:6.1.0
USER root
RUN . /app/.venv/bin/activate && uv pip install psycopg2-binary==2.9.10
COPY infra/analytics_superset_config.py /app/cognition/superset_config.py
COPY infra/chart_cache.py /app/chart_cache.py
COPY infra/bootstrap_analytics.py /app/cognition/bootstrap_analytics.py
COPY backend/app/analytics/reporting.sql /app/cognition/reporting.sql
USER superset
ENV SUPERSET_CONFIG_PATH=/app/cognition/superset_config.py

# Bootstrap runs by absolute script path; expose the adapter to it and Gunicorn.
ENV PYTHONPATH=/app/pythonpath:/app:/app/cognition
