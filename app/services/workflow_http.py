
"""HTTP helpers: structured JSON errors + simple in-process rate limit for floor API."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import Request, jsonify, request
from flask_limiter.util import get_remote_address

LOGGER = logging.getLogger(__name__)

_floor_buckets: Dict[str, List[float]] = defaultdict(list)
_FLOOR_WINDOW_SEC = 60.0
_FLOOR_MAX = 120


def workflow_json(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: Optional[Dict[str, Any]] = None,
):
    body: Dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return jsonify(body), status


def rate_limit_floor(f: Callable) -> Callable:
    """Per-IP sliding window (not security identity — abuse throttle)."""

    @wraps(f)
    def wrapped(*args, **kwargs):
        ip = get_remote_address() or "unknown"
        now = time.time()
        bucket = _floor_buckets[ip]
        bucket[:] = [t for t in bucket if now - t < _FLOOR_WINDOW_SEC]
        if len(bucket) >= _FLOOR_MAX:
            LOGGER.warning("WORKFLOW_RATE_LIMITED ip=%s", ip)
            return workflow_json(
                "WORKFLOW_RATE_LIMITED",
                "Too many requests. Please slow down.",
                status=429,
            )
        bucket.append(now)
        return f(*args, **kwargs)

    return wrapped


def read_json_body(req: Request) -> Dict[str, Any]:
    data = req.get_json(silent=True)
    return data if isinstance(data, dict) else {}
