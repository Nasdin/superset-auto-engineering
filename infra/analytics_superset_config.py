"""Dedicated BI service; independent of candidate-validation Superset instances."""

import hashlib
import os
from sqlalchemy.engine import URL
from superset.config import TALISMAN_CONFIG as DEFAULT_TALISMAN_CONFIG
from superset.config import WTF_CSRF_EXEMPT_LIST as DEFAULT_CSRF_EXEMPT_LIST
from flask import request
from flask_jwt_extended import verify_jwt_in_request

SECRET_KEY = os.environ["ANALYTICS_SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = URL.create(
    "postgresql+psycopg2",
    username="superset_metadata",
    password=os.environ["POSTGRES_SUPERSET_PASSWORD"],
    host=os.getenv("POSTGRES_HOST", "postgres"),
    database="superset_metadata",
).render_as_string(hide_password=False)
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True, "ENABLE_TEMPLATE_PROCESSING": False}
GUEST_ROLE_NAME = "CognitionGuest"
GUEST_TOKEN_JWT_SECRET = hashlib.sha256(("guest:" + SECRET_KEY).encode()).hexdigest()
GUEST_TOKEN_JWT_AUDIENCE = "cognition-superset"
GUEST_TOKEN_JWT_EXP_SECONDS = 300
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_port": 0, "x_prefix": 0}
PUBLIC_HTTPS = os.environ["SUPERSET_PUBLIC_URL"].startswith("https://")
SESSION_COOKIE_SECURE = PUBLIC_HTTPS
SESSION_COOKIE_HTTPONLY = True
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    **DEFAULT_TALISMAN_CONFIG,
    "force_https": False,  # Caddy enforces public HTTPS; private service traffic uses Docker networking.
    "frame_options": None,
    "content_security_policy": {
        **DEFAULT_TALISMAN_CONFIG["content_security_policy"],
        "frame-ancestors": os.environ["SUPERSET_ALLOWED_ORIGINS"].split(","),
    },
}
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60,
    "CACHE_KEY_PREFIX": "cognition_bi_",
    "CACHE_REDIS_URL": "redis://analytics-redis:6379/0",
}
DATA_CACHE_CONFIG = CACHE_CONFIG
FILTER_STATE_CACHE_CONFIG = {
    **CACHE_CONFIG,
    "CACHE_KEY_PREFIX": "cognition_filters_",
    "CACHE_DEFAULT_TIMEOUT": 86400,
}
EXPLORE_FORM_DATA_CACHE_CONFIG = {
    **CACHE_CONFIG,
    "CACHE_KEY_PREFIX": "cognition_explore_",
}
ENABLE_CORS = False
PREVENT_UNSAFE_DB_CONNECTIONS = True
SQL_MAX_ROW = 10000
SQLLAB_TIMEOUT = 60
APP_NAME = "Superset · Engineering intelligence"

RATELIMIT_STORAGE_URI = "redis://analytics-redis:6379/1"

# Only the server-to-server token endpoint is exempt. It MUST authenticate via JWT,
# never ambient browser cookies. Other Superset forms retain CSRF protection.
WTF_CSRF_EXEMPT_LIST = [*DEFAULT_CSRF_EXEMPT_LIST, "superset.security.api.guest_token"]


def require_guest_issuer_jwt(app):
    @app.before_request
    def authenticate_guest_issuer():
        if request.endpoint == "SecurityRestApi.guest_token":
            verify_jwt_in_request(locations=["headers"])


FLASK_APP_MUTATOR = require_guest_issuer_jwt
