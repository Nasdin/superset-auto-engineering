"""Local-only, isolated validation environment. No production data or accounts."""

import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    + os.environ["POSTGRES_PASSWORD"]
    + "@db:5432/superset"
)
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False  # Loopback HTTP only; never expose this demo service publicly.
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "cognition_",
    "CACHE_REDIS_URL": "redis://redis:6379/0",
}
DATA_CACHE_CONFIG = CACHE_CONFIG
FEATURE_FLAGS = {"ENABLE_TEMPLATE_PROCESSING": False}


class CeleryConfig:
    broker_url = "redis://redis:6379/0"
    result_backend = "redis://redis:6379/1"
    imports = ("superset.sql_lab",)


CELERY_CONFIG = CeleryConfig
