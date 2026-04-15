
"""SQLite transaction helpers: BEGIN IMMEDIATE + bounded SQLITE_BUSY retries."""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from contextlib import contextmanager
from typing import Callable, Generator, Optional, TypeVar

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

SQLITE_BUSY = "SQLITE_BUSY"
MAX_BUSY_ATTEMPTS = 5
BACKOFF_MIN_MS = 50
BACKOFF_MAX_MS = 150


def _jitter_ms() -> float:
    return random.uniform(BACKOFF_MIN_MS, BACKOFF_MAX_MS) / 1000.0


def _is_retryable_sqlite_busy(exc: sqlite3.OperationalError) -> bool:
    """True when SQLite reports contention that may clear after a short wait."""
    code = getattr(exc, "sqlite_errorcode", None)
    if code == sqlite3.SQLITE_BUSY:
        return True
    msg = str(exc).lower()
    if "database is locked" in msg or "locked" in msg:
        return True
    # Some builds / WAL paths surface busy without the word "locked" (e.g. "database is busy").
    if "busy" in msg:
        return True
    return False


def is_sqlite_busy_retryable(exc: BaseException) -> bool:
    """Public helper for user-facing messages (matches ``run_with_busy_retry`` detection)."""
    return isinstance(exc, sqlite3.OperationalError) and _is_retryable_sqlite_busy(exc)


def run_with_busy_retry(
    fn: Callable[[], T],
    *,
    op_name: str = "workflow_write",
) -> T:
    """Run fn(); on SQLITE_BUSY retry up to MAX_BUSY_ATTEMPTS with jitter."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, MAX_BUSY_ATTEMPTS + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            last_exc = e
            if not _is_retryable_sqlite_busy(e):
                raise
            if attempt >= MAX_BUSY_ATTEMPTS:
                LOGGER.error("%s SQLITE_BUSY exhausted after %s attempts", op_name, attempt)
                raise
            if attempt > 1:
                LOGGER.warning("%s retry %s/%s after SQLITE_BUSY", op_name, attempt, MAX_BUSY_ATTEMPTS)
            time.sleep(_jitter_ms())
    assert last_exc is not None
    raise last_exc


@contextmanager
def immediate_transaction(conn: sqlite3.Connection) -> Generator[None, None, None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise
