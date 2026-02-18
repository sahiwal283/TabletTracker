"""
Simple in-memory TTL cache for expensive read-only data (dashboard, report summaries).
Reduces repeated DB load when users refresh or switch tabs.
"""
import time
import threading
from typing import Any, Callable, Optional

_lock = threading.Lock()
_store: dict = {}  # key -> (value, expiry_ts)


def _now() -> float:
    return time.monotonic()


def get(key: str) -> Optional[Any]:
    """Return cached value if present and not expired, else None."""
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return None
        val, expiry = entry
        if _now() >= expiry:
            del _store[key]
            return None
        return val


def set(key: str, value: Any, ttl_seconds: float) -> None:
    """Store value with TTL in seconds."""
    with _lock:
        _store[key] = (value, _now() + ttl_seconds)


def get_or_set(key: str, builder: Callable[[], Any], ttl_seconds: float) -> Any:
    """Return cached value or call builder(), cache and return. Builder must be side-effect free for caching."""
    val = get(key)
    if val is not None:
        return val
    val = builder()
    set(key, val, ttl_seconds)
    return val


def clear() -> None:
    """Clear all cached entries (e.g. for tests)."""
    with _lock:
        _store.clear()
