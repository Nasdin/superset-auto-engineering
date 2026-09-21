"""Run with the analytics Superset image's Python (its real cache libraries)."""

import unittest
import uuid
from unittest.mock import patch

from flask import Flask
from flask_caching import Cache
from redis import ConnectionError, ResponseError

from chart_cache import ResilientChartCache


class ChartCacheTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "cognition_cache_test_" + uuid.uuid4().hex + "_"
        self.app = Flask(__name__)
        self.cache = Cache(self.app, config={
            "CACHE_TYPE": "chart_cache.ResilientChartCache",
            "CACHE_REDIS_URL": "redis://analytics-redis:6379/0",
            "CACHE_KEY_PREFIX": self.prefix,
            "CACHE_DEFAULT_TIMEOUT": 5,
        })

    def test_real_redis_hit_reuses_result_and_keeps_ttl(self):
        self.assertIsInstance(self.cache.cache, ResilientChartCache)
        self.assertIsNone(self.cache.get("result"))
        value = {"rows": [{"total_hours": 100.0}]}
        self.assertTrue(self.cache.set("result", value))
        try:
            self.assertEqual(self.cache.get("result"), value)
            self.assertGreater(self.cache.cache._read_client.ttl(self.prefix + "result"), 0)
            self.assertIsNone(self.cache.get("other-cohort"))
            self.assertEqual(self.cache.cache._read_client.connection_pool.connection_kwargs["socket_timeout"], 2)
        finally:
            self.cache.delete("result")

    def test_optional_cache_read_outage_and_memory_rejection_do_not_fail_query(self):
        with patch.object(self.cache.cache._read_client, "get", side_effect=ConnectionError):
            self.assertIsNone(self.cache.get("result"))
        with patch.object(self.cache.cache._write_client, "setex", side_effect=ResponseError("OOM")):
            self.assertFalse(self.cache.set("result", {"total": 3}))


if __name__ == "__main__":
    unittest.main()
