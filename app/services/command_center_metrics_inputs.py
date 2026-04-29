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
    "case_count",
    "loose_display_count",
    "counter_start",
    "counter_end",
    "cards_reopened",
)

_START_EVENTS = {"BAG_CLAIMED", "STATION_RESUMED", "PACKAGING_START"}
_COMPLETE_EVENTS = {"BLISTER_COMPLETE", "SEALING_COMPLETE", "PACKAGING_SNAPSHOT", "BAG_FINALIZED"}


def _payload_from_raw(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        p = json.loads(raw) if isinstance(raw, str) else dict(raw) if isinstance(raw, dict) else {}
    except json.JSONDecodeError:
        return {}
    return p if isinstance(p, dict) else {}


def _float_from_payload(raw: str | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {k: None for k in _PAYLOAD_NUM}
    p = _payload_from_raw(raw)
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


def _find_by_role(machines: list[dict], role: str) -> list[dict]:
    r = role.lower()
    return [m for m in machines if str(m.get("machine_role") or "").lower() == r]


def _station_display_name(picked: dict, fallback: str) -> str:
    """Primary label: machine name from settings (ops snapshot uses display_name)."""
    s = (
        picked.get("display_name")
        or picked.get("machine_name")
        or picked.get("label")
        or picked.get("station_label")
        or ""
    )
    s = str(s).strip()
    return s if s else fallback


def _station_subtitle(picked: dict, meta_canonical: str) -> str:
    """Secondary line under title — workflow station label, then generic role hint."""
    lab = str(picked.get("station_label") or "").strip()
    return lab if lab else meta_canonical


def build_slot_map(machines: list[dict]) -> list[dict[str, Any]]:
    blisters = _find_by_kind(machines, "blister")[:1]
    seal_list = _find_by_kind(machines, "sealing")[:3]
    packs = _find_by_kind(machines, "packaging")
    bottle_flow = [
        m for m in machines
        if str(m.get("machine_role") or "").lower() in {"bottle", "stickering"}
    ]
    used_ids: set[int] = set()
    ordered: list[tuple[dict, dict[str, Any]]] = []

    def _append(picked: dict | None, meta: dict[str, Any]) -> None:
        if not isinstance(picked, dict):
            return
        mid = picked.get("id")
        try:
            sid = int(mid)
        except (TypeError, ValueError):
            return
        dedupe_id = picked.get("machine_id") or sid
        try:
            dedupe_int = int(dedupe_id)
        except (TypeError, ValueError):
            dedupe_int = sid
        if dedupe_int in used_ids:
            return
        used_ids.add(dedupe_int)
        ordered.append((picked, meta))

    for idx, picked in enumerate(blisters, start=1):
        _append(
            picked,
            {
                "shortLabel": _station_display_name(picked, f"Blister · station {idx}"),
                "canonical": "DPP115 BLISTER MACHINE",
                "flow": "blister_card",
                "stepRole": "blister",
            },
        )
    heat_start = len(blisters) + 1
    for idx, picked in enumerate(seal_list, start=heat_start):
        _append(
            picked,
            {
                "shortLabel": _station_display_name(picked, f"Heat seal · station {idx}"),
                "canonical": "HEAT PRESS MACHINE",
                "flow": "blister_card",
                "stepRole": "heat_seal",
            },
        )
    for idx, picked in enumerate(packs, start=1):
        _append(
            picked,
            {
                "shortLabel": _station_display_name(
                    picked, "PACKAGING" if idx == 1 else f"PACKAGING {idx}"
                ),
                "canonical": "PACKAGING STATION",
                "flow": "packaging_station",
                "stepRole": "packaging",
            },
        )
    for picked in bottle_flow:
        role = str(picked.get("machine_role") or "").lower()
        _append(
            picked,
            {
                "shortLabel": str(picked.get("machine_name") or picked.get("label") or "BOTTLE FLOW").upper()[:18],
                "canonical": "BOTTLE STATION" if role == "bottle" else "STICKERING STATION",
                "flow": "bottle",
                "stepRole": role or "bottle",
            },
        )

    slots: list[dict[str, Any]] = []
    for slot_idx, (picked, meta) in enumerate(ordered, start=1):
        mid = picked.get("id")
        sk = picked.get("station_kind")
        mr = picked.get("machine_role")
        slots.append(
            {
                "slot": slot_idx,
                "label": _station_subtitle(picked, meta["canonical"]),
                "shortLabel": meta["shortLabel"],
                "stationId": int(mid) if mid is not None else None,
                "machineId": int(picked["machine_id"]) if picked.get("machine_id") not in (None, "") else None,
                "stationKind": str(sk).lower() if sk else None,
                "machineRole": str(mr).lower() if mr else None,
                "flow": meta["flow"],
                "stepRole": meta["stepRole"],
                "stationLabel": str(picked.get("label") or ""),
                "displayName": _station_display_name(picked, meta["canonical"]),
            }
        )
    return slots


def gather_unmapped_machine_settings(conn: sqlite3.Connection, existing: list[dict]) -> list[dict[str, Any]]:
    """Machines configured in settings but not yet attached to a workflow station."""
    attached_ids: set[int] = set()
    for row in existing:
        mid = row.get("machine_id")
        try:
            if mid is not None:
                attached_ids.add(int(mid))
        except (TypeError, ValueError):
            continue
    try:
        rows = conn.execute(
            """
            SELECT id, machine_name, machine_role, cards_per_turn
            FROM machines
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY machine_name
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[dict[str, Any]] = []
    next_virtual_id = -1
    for r in rows:
        try:
            machine_id = int(r["id"])
        except (TypeError, ValueError):
            continue
        if machine_id in attached_ids:
            continue
        role = str(r["machine_role"] or "").lower()
        if role not in {"bottle", "stickering", "packaging"}:
            continue
        out.append(
            {
                "id": next_virtual_id,
                "machine_id": machine_id,
                "display_name": str(r["machine_name"] or ""),
                "machine_name": str(r["machine_name"] or ""),
                "station_label": "Configured machine",
                "label": "Configured machine",
                "station_kind": role,
                "machine_role": role,
                "cards_per_turn": float(r["cards_per_turn"] or 1),
                "status": "idle",
                "bag_id": None,
                "occupancy_started_at_ms": None,
                "paused_at_ms": None,
                "tablets_today": 0,
                "displays_today": 0,
                "rate_hist_uh": None,
                "rate_today_uh": None,
                "rate_session_uh": None,
            }
        )
        next_virtual_id -= 1
    return out


def gather_workflow_event_rows(conn: sqlite3.Connection, start_ms: int, end_ms: int, limit: int = 24000) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    try:
        q = conn.execute(
            """
            SELECT we.id, we.occurred_at AS at_ms,
                   we.workflow_bag_id AS bag_id, we.station_id AS sid, we.event_type AS etype,
                   we.user_id AS user_id,
                   COALESCE(NULLIF(trim(e.full_name), ''), NULLIF(trim(e.username), '')) AS op_label,
                   we.payload AS payload,
                   COALESCE(pd.displays_per_case, 0) AS product_displays_per_case
            FROM workflow_events we
            LEFT JOIN employees e ON e.id = we.user_id
            LEFT JOIN workflow_bags wb ON wb.id = we.workflow_bag_id
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE we.occurred_at >= ? AND we.occurred_at < ?
            ORDER BY we.occurred_at ASC
            LIMIT ?
            """,
            (start_ms, end_ms, limit),
        )
        for r in q.fetchall():
            raw_payload = dict(r)["payload"]
            nums = _float_from_payload(str(raw_payload) if raw_payload not in (None, "") else None)
            payload_obj = _payload_from_raw(str(raw_payload) if raw_payload not in (None, "") else None)
            row = dict(r)
            sid = row.get("sid")
            bid = row.get("bag_id")
            packaging_case_breakdown = (
                "case_count" in payload_obj or "loose_display_count" in payload_obj
            )
            loose_display_num = nums["loose_display_count"]
            if loose_display_num is None:
                loose_display_num = nums["display_count"]
            try:
                prod_dpc = int(row.get("product_displays_per_case") or 0)
            except (TypeError, ValueError):
                prod_dpc = 0
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
                    "caseCount": nums["case_count"],
                    "looseDisplayCount": loose_display_num,
                    "productDisplaysPerCase": prod_dpc,
                    "packagingCaseBreakdown": packaging_case_breakdown,
                    "counterStart": nums["counter_start"],
                    "counterEnd": nums["counter_end"],
                    "cardsReopened": nums["cards_reopened"],
                    "reason": str(payload_obj.get("reason") or ""),
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
                   NULL AS qty_received,
                   COALESCE(pd.displays_per_case, 0) AS displays_per_case
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
            try:
                dpc = int(rr.get("displays_per_case") or 0)
            except (TypeError, ValueError):
                dpc = 0
            out.append(
                {
                    "id": int(rid),
                    "receiptNumber": str(rr.get("receipt_number") or ""),
                    "sku": str(rr.get("sku") or "—"),
                    "qtyReceived": rr.get("qty_received"),
                    "productLabel": str(rr.get("sku") or "—"),
                    "displaysPerCase": dpc,
                }
            )
    except sqlite3.OperationalError:
        return []
    return out


def gather_station_cycle_averages(
    conn: sqlite3.Connection,
    history_start_ms: int,
    history_end_ms: int,
) -> dict[str, dict[str, float | int]]:
    """Historical station cycle averages from real station check-in and completion events."""
    try:
        rows = conn.execute(
            """
            SELECT occurred_at AS at_ms, workflow_bag_id AS bag_id, station_id, event_type
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND workflow_bag_id IS NOT NULL
              AND station_id IS NOT NULL
            ORDER BY station_id, workflow_bag_id, occurred_at
            """,
            (history_start_ms, history_end_ms),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}

    start_by_pair: dict[tuple[int, int], int] = {}
    durations: dict[int, list[float]] = {}
    for r in rows:
        try:
            sid = int(r["station_id"])
            bid = int(r["bag_id"])
            at = int(r["at_ms"])
        except (TypeError, ValueError):
            continue
        et = str(r["event_type"] or "").upper()
        key = (sid, bid)
        if et in _START_EVENTS:
            start_by_pair[key] = at
        elif et in _COMPLETE_EVENTS:
            started = start_by_pair.pop(key, None)
            if started is None or at <= started:
                continue
            minutes = (at - started) / 60000.0
            if 0.25 <= minutes <= 24 * 60:
                durations.setdefault(sid, []).append(minutes)

    out: dict[str, dict[str, float | int]] = {}
    for sid, vals in durations.items():
        if not vals:
            continue
        out[str(sid)] = {
            "avgMinutes": sum(vals) / len(vals),
            "sampleCount": len(vals),
        }
    return out


def gather_output_pace_averages(
    conn: sqlite3.Connection,
    day_start_ms: int,
    now_ms: int,
) -> dict[str, float | int | None]:
    """Final-display pace from real packaging final-submit events."""
    window_start = day_start_ms - (7 * 24 * 60 * 60_000)
    window_end = day_start_ms + (24 * 60 * 60_000)
    daily: dict[int, float] = {i: 0.0 for i in range(-7, 1)}
    try:
        rows = conn.execute(
            """
            SELECT occurred_at AS at_ms, workflow_bag_id AS bag_id, payload
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND event_type = 'PACKAGING_SNAPSHOT'
            """,
            (window_start, window_end),
        ).fetchall()
    except sqlite3.OperationalError:
        return {
            "weeklyAvgDisplays": None,
            "dailyDisplays": None,
            "projectedDisplays": None,
            "sampleDays": 0,
        }

    bag_ids_pace: set[int] = set()
    for r in rows:
        payload = _payload_from_raw(r["payload"])
        if str(payload.get("reason") or "").lower() != "final_submit":
            continue
        bid = r["bag_id"]
        try:
            if bid is not None:
                bag_ids_pace.add(int(bid))
        except (TypeError, ValueError):
            pass

    dpc_by_bag: dict[int, int] = {}
    if bag_ids_pace:
        ph = ",".join(["?"] * len(bag_ids_pace))
        try:
            for br in conn.execute(
                f"""
                SELECT wb.id, COALESCE(pd.displays_per_case, 0) AS dpc
                FROM workflow_bags wb
                LEFT JOIN product_details pd ON pd.id = wb.product_id
                WHERE wb.id IN ({ph})
                """,
                tuple(bag_ids_pace),
            ):
                try:
                    wid = int(br["id"])
                    dpc_by_bag[wid] = int(br["dpc"] or 0)
                except (TypeError, ValueError):
                    continue
        except sqlite3.OperationalError:
            dpc_by_bag = {}

    def _final_submit_display_equivalent(payload: dict[str, Any], bag_id: int | None) -> float:
        """Match workflow_floor packaging normalization: loose-only display_count when case fields exist."""
        p = payload or {}
        case_breakdown = "case_count" in p or "loose_display_count" in p
        if case_breakdown:
            try:
                cases = float(p.get("case_count") or 0)
            except (TypeError, ValueError):
                cases = 0.0
            loose_raw = p.get("loose_display_count")
            if loose_raw is None:
                loose_raw = p.get("display_count")
            try:
                loose = float(loose_raw or 0)
            except (TypeError, ValueError):
                loose = 0.0
            dpc = 0
            if bag_id is not None:
                try:
                    dpc = dpc_by_bag.get(int(bag_id), 0)
                except (TypeError, ValueError):
                    dpc = 0
            return max(0.0, cases * float(dpc) + loose)
        raw_one = p.get("display_count", p.get("count_total"))
        try:
            return max(0.0, float(raw_one or 0))
        except (TypeError, ValueError):
            return 0.0

    for r in rows:
        try:
            at = int(r["at_ms"])
        except (TypeError, ValueError):
            continue
        payload = _payload_from_raw(r["payload"])
        if str(payload.get("reason") or "").lower() != "final_submit":
            continue
        bid = r["bag_id"]
        try:
            bid_int = int(bid) if bid is not None else None
        except (TypeError, ValueError):
            bid_int = None
        count = _final_submit_display_equivalent(payload, bid_int)
        if count <= 0:
            continue
        idx = int((at - day_start_ms) // (24 * 60 * 60_000))
        if idx in daily:
            daily[idx] += count

    previous = [daily[i] for i in range(-7, 0)]
    today = daily[0]
    elapsed_fraction = max((now_ms - day_start_ms) / float(24 * 60 * 60_000), 1 / 96)
    return {
        "weeklyAvgDisplays": round(sum(previous) / 7.0, 2),
        "dailyDisplays": round(today, 2),
        "projectedDisplays": round(today / elapsed_fraction, 2) if today > 0 else 0,
        "sampleDays": 7,
    }


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


def _first_blister_station_id(machines: list[dict]) -> int | None:
    """Workflow station id for the primary blister line (material roll APIs)."""
    for m in machines:
        if str(m.get("station_kind") or "").lower() == "blister":
            try:
                return int(m["id"])
            except (TypeError, ValueError, KeyError):
                continue
    return None


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

    machines = list(machines or []) + gather_unmapped_machine_settings(conn, machines or [])
    slots = build_slot_map(machines)
    blister_station_id = _first_blister_station_id(machines)

    def _ms_row(m: dict) -> dict[str, Any]:
        sid = int(m["id"])
        live_occ = (m.get("occupancy_started_at_ms") if m else None)
        paused = (m.get("paused_at_ms") if m else None)
        wf_bag = m.get("bag_id")
        try:
            tablets_today = int(m.get("tablets_today") or 0)
        except (TypeError, ValueError):
            tablets_today = 0
        try:
            displays_today = int(m.get("displays_today") or 0)
        except (TypeError, ValueError):
            displays_today = 0
        return {
            "id": sid,
            "displayName": str(m.get("display_name") or ""),
            "stationLabel": str(m.get("station_label") or ""),
            "stationKind": str(m.get("station_kind") or ""),
            "machineRole": str(m.get("machine_role") or ""),
            "cardsPerTurn": float(m.get("cards_per_turn") or 1),
            "status": str(m.get("status") or "idle"),
            "occupancyStartedAtMs": int(live_occ) if live_occ is not None else None,
            "pausedAtMs": int(paused) if paused is not None else None,
            "workflowBagId": int(wf_bag) if wf_bag is not None else None,
            "tabletsToday": tablets_today,
            "displaysToday": displays_today,
            "manualEntrySignal": False,
            "rateHistUh": m.get("rate_hist_uh"),
            "rateTodayUh": m.get("rate_today_uh"),
            "rateSessionUh": m.get("rate_session_uh"),
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
    daily_display_target = _float_setting(conn, "ops_tv_daily_output_target")
    bm = configured_target if configured_target is not None else (kpis_benchmark_uh if kpis_benchmark_uh and kpis_benchmark_uh > 0.5 else None)
    target_source = "configured" if configured_target is not None else ("historical" if bm is not None else None)
    planned_min = max(1.0, (now_ms - day_start_ms) / 60000.0)

    shift_cfg = {
        "dayStartMs": int(day_start_ms),
        "nowMs": int(now_ms),
        "plannedShiftMinutes": planned_min,
        "targetThroughputPerHour": bm,
        "targetThroughputSource": target_source,
        "dailyDisplayTarget": daily_display_target,
        "productionDueMs": _due_time_ms(conn, day_start_ms),
        "stationCycleAvgWindowDays": 7,
        "stationCycleAvgMinutes": gather_station_cycle_averages(conn, day_start_ms - (7 * 24 * 60 * 60_000), day_start_ms),
        "outputPaceAverages": gather_output_pace_averages(conn, day_start_ms, now_ms),
    }

    return {
        "demoMode": demo_mode,
        "events": events,
        "machines": mrows,
        "bags": bags,
        "slots": slots,
        "blisterStationId": blister_station_id,
        "shiftConfig": shift_cfg,
        "genealogySelectedBagId": default_bag,
    }
