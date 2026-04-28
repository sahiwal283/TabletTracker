"""
Serialize real workflow data for client-side command center metrics derivation.
No fabricated production numbers.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

_PAYLOAD_NUM = (
    "count_total",
    "display_count",
    "counter_start",
    "counter_end",
)


def _float_from_payload(raw: str | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {k: None for k in _PAYLOAD_NUM}
    if not raw:
        return out
    try:
        p = json.loads(raw) if isinstance(raw, str) else dict(raw) if isinstance(raw, dict) else {}
    except json.JSONDecodeError:
        return out
    if not isinstance(p, dict):
        return out
    for k in _PAYLOAD_NUM:
        v = p.get(k)
        try:
            out[k] = float(v) if v is not None else None
        except (TypeError, ValueError):
            out[k] = None
    return out


def _find_by_kind(machines: list[dict], kind: str) -> list[dict]:
    k = kind.lower()
    return [m for m in machines if str(m.get("station_kind") or "").lower() == k]


def build_slot_map(machines: list[dict]) -> list[dict[str, Any]]:
    blisters = _find_by_kind(machines, "blister")
    seal_list = _find_by_kind(machines, "sealing")
    packs = _find_by_kind(machines, "packaging")
    slot_pick: list[dict | None] = [
        blisters[0] if len(blisters) > 0 else None,
        seal_list[0] if len(seal_list) > 0 else None,
        seal_list[1] if len(seal_list) > 1 else None,
        packs[0] if len(packs) > 0 else None,
        seal_list[2] if len(seal_list) > 2 else None,
    ]
    defs = [
        {"slot": 1, "label": "M1 DPP115", "shortLabel": "M1", "canonical": "M1 DPP115", "role": None},
        {"slot": 2, "label": "M2 Heat Seal", "shortLabel": "M2", "canonical": "M2 Heat Seal", "role": None},
        {"slot": 3, "label": "M3 Heat Seal", "shortLabel": "M3", "canonical": "M3 Heat Seal", "role": None},
        {"slot": 4, "label": "M4 Stickering", "shortLabel": "M4", "canonical": "M4 Stickering", "role": None},
        {"slot": 5, "label": "M5 Bottle Sealer", "shortLabel": "M5", "canonical": "M5 Bottle Sealer", "role": "bottle_seal"},
    ]
    slots: list[dict[str, Any]] = []
    for d, picked in zip(defs, slot_pick):
        mid = picked.get("id") if isinstance(picked, dict) else None
        sk = picked.get("station_kind") if isinstance(picked, dict) else None
        slots.append(
            {
                "slot": d["slot"],
                "label": d["canonical"],
                "shortLabel": d["shortLabel"],
                "stationId": int(mid) if mid is not None else None,
                "stationKind": str(sk).lower() if sk else None,
                "role": d.get("role"),
            }
        )
    return slots


def gather_workflow_event_rows(conn: sqlite3.Connection, start_ms: int, end_ms: int, limit: int = 24000) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    try:
        q = conn.execute(
            """
            SELECT we.id, we.occurred_at AS at_ms,
                   we.workflow_bag_id AS bag_id, we.station_id AS sid, we.event_type AS etype,
                   we.user_id AS user_id,
                   COALESCE(NULLIF(trim(e.full_name), ''), NULLIF(trim(e.username), '')) AS op_label,
                   we.payload AS payload
            FROM workflow_events we
            LEFT JOIN employees e ON e.id = we.user_id
            WHERE we.occurred_at >= ? AND we.occurred_at < ?
            ORDER BY we.occurred_at ASC
            LIMIT ?
            """,
            (start_ms, end_ms, limit),
        )
        for r in q.fetchall():
            raw_payload = dict(r)["payload"]
            nums = _float_from_payload(str(raw_payload) if raw_payload not in (None, "") else None)
            row = dict(r)
            sid = row.get("sid")
            bid = row.get("bag_id")
            rows_out.append(
                {
                    "atMs": int(row["at_ms"] or 0),
                    "stationId": int(sid) if sid not in (None, "") else None,
                    "eventType": str(row["etype"] or ""),
                    "bagId": int(bid) if bid not in (None, "") else None,
                    "userId": int(row["user_id"]) if row.get("user_id") is not None else None,
                    "operatorLabel": str(row.get("op_label") or ""),
                    "countTotal": nums["count_total"],
                    "displayCount": nums["display_count"],
                    "counterStart": nums["counter_start"],
                    "counterEnd": nums["counter_end"],
                }
            )
    except sqlite3.OperationalError:
        return []
    return rows_out


def gather_bags_for_trace(conn: sqlite3.Connection, bag_ids: list[int]) -> list[dict[str, Any]]:
    if not bag_ids:
        return []
    placeholders = ",".join(["?"] * len(bag_ids))
    out: list[dict[str, Any]] = []
    try:
        for r in conn.execute(
            f"""
            SELECT wb.id,
                   wb.receipt_number,
                   substr(upper(trim(replace(coalesce(pd.product_name,''),' ','-'))),1,48) AS sku,
                   NULL AS qty_received
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE wb.id IN ({placeholders})
            """,
            tuple(bag_ids),
        ):
            rr = dict(r)
            rid = rr.get("id")
            if rid is None:
                continue
            out.append(
                {
                    "id": int(rid),
                    "receiptNumber": str(rr.get("receipt_number") or ""),
                    "sku": str(rr.get("sku") or "—"),
                    "qtyReceived": rr.get("qty_received"),
                    "productLabel": str(rr.get("sku") or "—"),
                }
            )
    except sqlite3.OperationalError:
        return []
    return out


def pick_default_bag_id(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> int | None:
    """Most recently active workflow bag having events in window."""
    try:
        r = conn.execute(
            """
            SELECT workflow_bag_id AS wid,
                   SUM(1) AS c,
                   MAX(occurred_at) AS last_m
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ? AND workflow_bag_id IS NOT NULL
            GROUP BY workflow_bag_id
            ORDER BY last_m DESC, c DESC
            LIMIT 1
            """,
            (start_ms, end_ms),
        ).fetchone()
        if r and r["wid"] is not None:
            return int(r["wid"])
    except sqlite3.OperationalError:
        pass
    return None


def _app_setting(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = ?",
            (key,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    raw = row["setting_value"] if hasattr(row, "keys") else row[0]
    value = str(raw or "").strip()
    return value or None


def _float_setting(conn: sqlite3.Connection, key: str) -> float | None:
    raw = _app_setting(conn, key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _due_time_ms(conn: sqlite3.Connection, day_start_ms: int) -> int | None:
    raw = _app_setting(conn, "ops_tv_production_due_time")
    if not raw or ":" not in raw:
        return None
    try:
        hh, mm = raw.split(":", 1)
        h = int(hh)
        m = int(mm)
    except (TypeError, ValueError):
        return None
    if h < 0 or h > 23 or m < 0 or m > 59:
        return None
    return int(day_start_ms + ((h * 60 + m) * 60_000))


def build_metrics_inputs_bundle(
    conn: sqlite3.Connection,
    machines: list[dict],
    kpis_benchmark_uh: float | None,
    *,
    day_start_ms: int,
    now_ms: int,
) -> dict[str, Any]:
    """Shape keys match TypeScript MetricsInputs camelCase convention."""
    end_ms = now_ms + 60_000
    events = gather_workflow_event_rows(conn, day_start_ms, end_ms)

    demo_mode = os.environ.get("MES_COMMAND_CENTER_DEMO_MODE", "").lower() in ("1", "true", "yes")

    slots = build_slot_map(machines)

    def _ms_row(m: dict) -> dict[str, Any]:
        sid = int(m["id"])
        live_occ = (m.get("occupancy_started_at_ms") if m else None)
        paused = (m.get("paused_at_ms") if m else None)
        wf_bag = m.get("bag_id")
        return {
            "id": sid,
            "displayName": str(m.get("display_name") or ""),
            "stationLabel": str(m.get("station_label") or ""),
            "stationKind": str(m.get("station_kind") or ""),
            "status": str(m.get("status") or "idle"),
            "occupancyStartedAtMs": int(live_occ) if live_occ is not None else None,
            "pausedAtMs": int(paused) if paused is not None else None,
            "workflowBagId": int(wf_bag) if wf_bag is not None else None,
            "manualEntrySignal": False,
        }

    mrows = [_ms_row(m) for m in machines]

    default_bag = pick_default_bag_id(conn, day_start_ms, end_ms)
    bag_ids: list[int] = []
    seen_bag_ids: set[int] = set()
    for ev in reversed(events):
        bid = ev.get("bagId")
        if bid is None:
            continue
        try:
            bid_int = int(bid)
        except (TypeError, ValueError):
            continue
        if bid_int in seen_bag_ids:
            continue
        seen_bag_ids.add(bid_int)
        bag_ids.append(bid_int)
        if len(bag_ids) >= 200:
            break
    if default_bag is not None and default_bag not in seen_bag_ids:
        bag_ids.insert(0, default_bag)
    bags = gather_bags_for_trace(conn, bag_ids)

    configured_target = _float_setting(conn, "ops_tv_target_units_per_hour")
    bm = configured_target if configured_target is not None else (kpis_benchmark_uh if kpis_benchmark_uh and kpis_benchmark_uh > 0.5 else None)
    target_source = "configured" if configured_target is not None else ("historical" if bm is not None else None)
    planned_min = max(1.0, (now_ms - day_start_ms) / 60000.0)

    shift_cfg = {
        "dayStartMs": int(day_start_ms),
        "nowMs": int(now_ms),
        "plannedShiftMinutes": planned_min,
        "targetThroughputPerHour": bm,
        "targetThroughputSource": target_source,
        "productionDueMs": _due_time_ms(conn, day_start_ms),
    }

    return {
        "demoMode": demo_mode,
        "events": events,
        "machines": mrows,
        "bags": bags,
        "slots": slots,
        "shiftConfig": shift_cfg,
        "genealogySelectedBagId": default_bag,
    }
