"""Read-focused reporting helpers for Telegram bot commands."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from app.services import workflow_constants as WC
from app.services.reporting_analytics_service import _submission_report_rows
from app.services.submission_calculator import calculate_submission_total_with_fallback

_NY = ZoneInfo("America/New_York")


def _ny_window_for_day(target_day: date) -> tuple[int, int]:
    start_local = datetime.combine(target_day, time.min).replace(tzinfo=_NY)
    end_local = start_local + timedelta(days=1)
    start_ms = int(start_local.astimezone(timezone.utc).timestamp() * 1000)
    end_ms = int(end_local.astimezone(timezone.utc).timestamp() * 1000)
    return start_ms, end_ms


def _parse_target_day(day_iso: Optional[str]) -> date:
    if day_iso:
        return datetime.strptime(day_iso[:10], "%Y-%m-%d").date()
    return datetime.now(_NY).date()


def _parse_date_text(value: object) -> Optional[date]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_created_at_to_ny_date(value: object) -> Optional[date]:
    dt = _parse_created_at_to_ny_datetime(value)
    return dt.date() if dt else None


def _parse_created_at_to_ny_datetime(value: object) -> Optional[datetime]:
    """Parse warehouse_submissions.created_at (UTC-naive) to America/New_York."""
    if value is None:
        return None
    raw = str(value).strip().replace("T", " ")
    if not raw:
        return None
    raw = raw.split(".", 1)[0]
    parsed: Optional[datetime] = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(raw[:19], fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    dt_utc = parsed.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(_NY)


def _submission_effective_ny_datetime(sub: Dict[str, object], target_day: date) -> datetime:
    """Wall-clock instant in NY used for intraday cutoffs (created_at preferred)."""
    created = _parse_created_at_to_ny_datetime(sub.get("created_at"))
    if created is not None:
        return created
    sd = _parse_date_text(sub.get("submission_date"))
    if sd is not None:
        return datetime.combine(sd, time.min).replace(tzinfo=_NY)
    fd = _parse_date_text(sub.get("filter_date"))
    if fd is not None:
        return datetime.combine(fd, time.min).replace(tzinfo=_NY)
    return datetime.combine(target_day, time.min).replace(tzinfo=_NY)


def _is_submission_on_target_day(sub: Dict[str, object], target_day: date) -> bool:
    submission_day = _parse_date_text(sub.get("submission_date"))
    if submission_day is not None:
        return submission_day == target_day
    created_day = _parse_created_at_to_ny_date(sub.get("created_at"))
    if created_day is not None:
        return created_day == target_day
    filter_day = _parse_date_text(sub.get("filter_date"))
    return filter_day == target_day


def _submission_included_through(
    sub: Dict[str, object], target_day: date, as_of_ny: Optional[datetime]
) -> bool:
    if not _is_submission_on_target_day(sub, target_day):
        return False
    if as_of_ny is None:
        return True
    return _submission_effective_ny_datetime(sub, target_day) <= as_of_ny


def _tablets_per_display_by_product(conn: sqlite3.Connection) -> Dict[str, float]:
    rows = conn.execute(
        """
        SELECT product_name, packages_per_display, tablets_per_package
        FROM product_details
        WHERE product_name IS NOT NULL
          AND TRIM(product_name) != ''
          AND COALESCE(packages_per_display, 0) > 0
          AND COALESCE(tablets_per_package, 0) > 0
        ORDER BY id ASC
        """
    ).fetchall()
    out: Dict[str, float] = {}
    for row in rows:
        key = str(row["product_name"]).strip().lower()
        if key in out:
            continue
        out[key] = float(row["packages_per_display"] * row["tablets_per_package"])
    return out


def _daily_product_rollup(
    conn: sqlite3.Connection, target_day: date, as_of_ny: Optional[datetime] = None
) -> List[Dict[str, object]]:
    # Query a small surrounding range, then apply NY-local day matching.
    range_start = (target_day - timedelta(days=1)).isoformat()
    range_end = (target_day + timedelta(days=1)).isoformat()
    submissions = _submission_report_rows(conn, date_from=range_start, date_to=range_end)
    tpd_by_product = _tablets_per_display_by_product(conn)
    rollup: Dict[str, Dict[str, object]] = {}

    for sub in submissions:
        if not _submission_included_through(sub, target_day, as_of_ny):
            continue
        st = (sub.get("submission_type") or "packaged").lower()
        if st in ("bag", "machine"):
            continue
        product_name = (sub.get("product_name") or "Unknown").strip() or "Unknown"
        key = product_name.lower()
        if key not in rollup:
            rollup[key] = {
                "product_name": product_name,
                "displays_made": 0,
                "tablets_total": 0,
                "display_equivalent": 0.0,
            }
        row = rollup[key]
        row["displays_made"] = int(row["displays_made"]) + int(sub.get("displays_made") or 0)
        tablets_total = int(
            calculate_submission_total_with_fallback(
                sub,
                {
                    "packages_per_display": sub.get("packages_per_display"),
                    "tablets_per_package": sub.get("tablets_per_package"),
                },
                {"tablets_per_package": sub.get("tablets_per_package_final")},
            )
        )
        row["tablets_total"] = int(row["tablets_total"]) + tablets_total
        tpd = tpd_by_product.get(key)
        if tpd and tpd > 0:
            row["display_equivalent"] = float(row["display_equivalent"]) + (tablets_total / tpd)

    out = list(rollup.values())
    out.sort(key=lambda x: (-(float(x.get("display_equivalent") or 0.0)), x["product_name"]))
    return out


def build_daily_summary(
    conn: sqlite3.Connection,
    day_iso: Optional[str] = None,
    *,
    full_day: bool = False,
) -> Dict[str, object]:
    """
    Production summary for one America/New_York calendar day.

    For *today*, defaults to partial day (submissions through "now" in NY) unless
    ``full_day`` is True. For past dates, always the full calendar day.
    """
    target_day = _parse_target_day(day_iso)
    today_ny = datetime.now(_NY).date()
    if full_day or target_day != today_ny:
        as_of_ny: Optional[datetime] = None
    else:
        as_of_ny = datetime.now(_NY)

    rows = _daily_product_rollup(conn, target_day, as_of_ny=as_of_ny)
    total_displays = sum(int(r.get("displays_made") or 0) for r in rows)
    total_display_equivalent = round(sum(float(r.get("display_equivalent") or 0.0) for r in rows), 2)
    through_label: Optional[str] = None
    if as_of_ny is not None:
        through_label = as_of_ny.strftime("%Y-%m-%d %I:%M %p %Z")

    return {
        "day": target_day.isoformat(),
        "total_displays_made": total_displays,
        "total_display_equivalent": total_display_equivalent,
        "through_ny": through_label,
        "is_partial_day": as_of_ny is not None,
        "products": [
            {
                "product_name": r["product_name"],
                "displays_made": int(r.get("displays_made") or 0),
                "display_equivalent": round(float(r.get("display_equivalent") or 0.0), 2),
                "tablets_total": int(r.get("tablets_total") or 0),
            }
            for r in rows
        ],
    }


def get_station_current_bag(conn: sqlite3.Connection, station_kind: str) -> Optional[Dict[str, object]]:
    if station_kind not in ("blister", "sealing", "packaging"):
        return None
    row = conn.execute(
        """
        SELECT we.workflow_bag_id, we.occurred_at, ws.id AS station_id, ws.label AS station_label, ws.station_kind
        FROM workflow_events we
        JOIN workflow_stations ws ON ws.id = we.station_id
        WHERE ws.station_kind IN (?, 'combined')
          AND we.event_type = 'BAG_CLAIMED'
        ORDER BY we.occurred_at DESC, we.id DESC
        LIMIT 1
        """,
        (station_kind,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def count_bags_blistered_today(conn: sqlite3.Connection, day_iso: Optional[str] = None) -> Dict[str, object]:
    target_day = _parse_target_day(day_iso)
    start_ms, end_ms = _ny_window_for_day(target_day)
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT workflow_bag_id) AS c
        FROM workflow_events
        WHERE event_type = ?
          AND occurred_at >= ?
          AND occurred_at < ?
        """,
        (WC.EVENT_BLISTER_COMPLETE, start_ms, end_ms),
    ).fetchone()
    return {
        "day": target_day.isoformat(),
        "bags_blistered": int(row["c"] or 0) if row else 0,
    }
