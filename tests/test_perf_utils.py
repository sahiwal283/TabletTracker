"""Tests for performance instrumentation utilities."""
import unittest
from app.utils.perf_utils import should_log_perf, query_timer, PERF_TRACKED_PREFIXES


class TestPerfUtils(unittest.TestCase):
    def test_should_log_perf_tracked_paths(self):
        self.assertTrue(should_log_perf('/dashboard'))
        self.assertTrue(should_log_perf('/api/reports/po-summary'))
        self.assertTrue(should_log_perf('/api/po/1/details'))
        self.assertTrue(should_log_perf('/api/receiving/1/details'))
        self.assertTrue(should_log_perf('/api/submission/1/possible-receives'))
        self.assertTrue(should_log_perf('/api/receives/list'))
        self.assertTrue(should_log_perf('/api/bag/1/submissions'))

    def test_should_log_perf_ignored_paths(self):
        self.assertFalse(should_log_perf('/'))
        self.assertFalse(should_log_perf('/login'))
        self.assertFalse(should_log_perf('/api/other'))
        self.assertFalse(should_log_perf(None))
        self.assertFalse(should_log_perf(''))

    def test_query_timer_calls_log_fn(self):
        log_calls = []
        with query_timer('test_query', log_fn=lambda label, ms: log_calls.append((label, ms))):
            pass
        self.assertEqual(len(log_calls), 1)
        self.assertEqual(log_calls[0][0], 'test_query')
        self.assertIsInstance(log_calls[0][1], (int, float))
        self.assertGreaterEqual(log_calls[0][1], 0)
