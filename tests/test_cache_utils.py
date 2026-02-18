"""Tests for cache utilities."""
import unittest
from app.utils.cache_utils import get, set as cache_set, get_or_set, clear


class TestCacheUtils(unittest.TestCase):
    def setUp(self):
        clear()

    def tearDown(self):
        clear()

    def test_get_miss(self):
        self.assertIsNone(get('nonexistent'))

    def test_set_and_get(self):
        cache_set('k', 'v', 60.0)
        self.assertEqual(get('k'), 'v')

    def test_get_expired(self):
        cache_set('k', 'v', 0.0001)  # 0.1ms TTL
        import time
        time.sleep(0.002)
        self.assertIsNone(get('k'))

    def test_get_or_set_builds_once(self):
        calls = [0]
        def builder():
            calls[0] += 1
            return 42
        self.assertEqual(get_or_set('key', builder, 60.0), 42)
        self.assertEqual(get_or_set('key', builder, 60.0), 42)
        self.assertEqual(calls[0], 1)

    def test_clear(self):
        cache_set('a', 1, 60.0)
        clear()
        self.assertIsNone(get('a'))
