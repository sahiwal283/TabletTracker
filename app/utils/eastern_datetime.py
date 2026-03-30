"""
Parse and format bag timing fields as America/New_York wall time, stored UTC-naive in DB
(consistent with to_est filter expectations in api.py).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def utc_now_naive_string() -> str:
    """Current UTC as naive YYYY-MM-DD HH:MM:SS for warehouse_submissions columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def parse_eastern_input_to_utc_naive_string(value: Optional[str]) -> Optional[str]:
    """
    Interpret user input (datetime-local or 'YYYY-MM-DD HH:MM') as Eastern local time;
    return UTC naive string for storage. None/empty -> None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace("T", " ")
    # Strip fractional seconds if present
    if "." in s:
        s = s.split(".")[0]
    naive = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(s[:19], fmt)
            break
        except ValueError:
            continue
    if naive is None:
        raise ValueError(f"Invalid datetime: {value!r}")
    aware_ny = naive.replace(tzinfo=_NY)
    utc_dt = aware_ny.astimezone(_UTC)
    return utc_dt.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def parse_optional_eastern(value: Optional[str]) -> Optional[str]:
    """Like parse_eastern_input_to_utc_naive_string but returns None on empty; raises ValueError on bad input."""
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return None
    return parse_eastern_input_to_utc_naive_string(value)
