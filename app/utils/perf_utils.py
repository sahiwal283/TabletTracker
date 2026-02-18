"""
Lightweight performance instrumentation for baseline and post-refactor comparison.

- Request-level timing (path, duration_ms) for dashboard and API routes.
- Optional query-level timing for heavy SQL blocks.
- Server-Timing response header when enabled for frontend visibility.
"""
import time
import logging
from contextlib import contextmanager
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Paths we care about for baseline (dashboard + report APIs)
PERF_TRACKED_PREFIXES = ("/dashboard", "/api/reports", "/api/po", "/api/receiving", "/api/submission", "/api/receives", "/api/bag")


def should_log_perf(path: Optional[str]) -> bool:
    """Return True if we should log timing for this path."""
    if not path:
        return False
    return any(path.startswith(prefix) for prefix in PERF_TRACKED_PREFIXES)


@contextmanager
def query_timer(label: str, log_fn: Optional[Callable[[str, float], None]] = None):
    """
    Context manager that logs elapsed time for a block (e.g. a DB query).
    Use from views to establish per-query baselines.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        if log_fn:
            log_fn(label, elapsed_ms)
        else:
            logger.info("perf_query %s %.2f ms", label, elapsed_ms)


def _perf_enabled(app) -> bool:
    return bool(app.config.get("PERF_LOGGING", app.config.get("DEBUG", False)))


def log_request_duration(path: str, duration_ms: float, app) -> None:
    """Log request duration for tracked paths. Call from after_request."""
    if not should_log_perf(path) or not _perf_enabled(app):
        return
    app.logger.info("perf_request path=%s duration_ms=%.2f", path, duration_ms)


def add_server_timing_header(response, path: str, duration_ms: float, app) -> None:
    """Add Server-Timing header for frontend baseline capture. Call from after_request."""
    if not should_log_perf(path) or not _perf_enabled(app):
        return
    # Server-Timing: total;dur=123.45
    response.headers.setdefault("Server-Timing", f"total;dur={duration_ms:.2f}")
