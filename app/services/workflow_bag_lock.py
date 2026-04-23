"""Process-local lock to serialize finalize vs force-release per bag."""

from __future__ import annotations

import threading

_lock_guard = threading.Lock()
_bag_locks: dict[int, threading.Lock] = {}


def bag_write_lock(workflow_bag_id: int) -> threading.Lock:
    with _lock_guard:
        if workflow_bag_id not in _bag_locks:
            _bag_locks[workflow_bag_id] = threading.Lock()
        return _bag_locks[workflow_bag_id]
