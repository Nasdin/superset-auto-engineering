"""Optional chart-result cache; never use this backend for security state."""

import logging

from flask_caching.backends.rediscache import RedisCache
from redis import Redis, RedisError

logger = logging.getLogger(__name__)


class ResilientChartCache(RedisCache):
    @classmethod
    def factory(cls, app, config, args, kwargs):
        # Flask-Caching's standard URL factory drops socket CACHE_OPTIONS when
        # constructing its Redis client. Supply the bounded client explicitly.
        client = Redis.from_url(
            config["CACHE_REDIS_URL"],
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=False,
        )
        return cls(
            host=client,
            key_prefix=config["CACHE_KEY_PREFIX"],
            default_timeout=config["CACHE_DEFAULT_TIMEOUT"],
        )

    def get(self, key):
        try:
            return super().get(key)
        except RedisError as error:
            logger.warning("Chart cache read unavailable (%s); querying source", type(error).__name__)
            return None

    def set(self, key, value, timeout=None):
        try:
            return super().set(key, value, timeout=timeout)
        except RedisError as error:
            # noeviction rejects writes when memory is full. A successful query
            # still renders; do not evict rate-limit counters to make cache room.
            logger.warning("Chart cache write skipped (%s)", type(error).__name__)
            return False
