"""
MES Command Center payload: sparklines, parallel lanes, SCADA machine slots.
Composed from workflow snapshot + pill_board; safe fallbacks when columns missing.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

def _spark_from_series(base: list[float], mult: float, floor: float = 0.0) -> list[float]:
    if not base:
        base = [0.0] * 24
    out: list[float] = []
    run = 0.0
    for i, v in enumerate(base[:24]):
        run += float(v) * mult / max(12.0, float(sum(base) or 1.0))
        out.append(round(max(floor, run + (i % 3) * mult * 0.1), 2))
    while len(out) < 24:
        out.append(out[-1] if out else floor)
    return out[:24]


def _normalize_spark(vals: list[float]) -> list[float]:
    if not vals:
        return [0.0] * 24
    mx = max(vals) or 1.0
    return [round(100.0 * v / mx, 2) for v in vals[:24]]


def _find_by_kind(machines: list[dict], kind: str) -> list[dict]:
    k = kind.lower()
    return [m for m in machines if str(m.get("station_kind") or "").lower() == k]


def _pick_station(machines: list[dict], kind: str, index: int = 0) -> dict | None:
    xs = _find_by_kind(machines, kind)
    if index < len(xs):
        return xs[index]
    return xs[0] if xs else None


def build_mes_dashboard(
    conn: sqlite3.Connection,
    machines: list[dict],
    flow_intel: dict,
    kpis: dict,
    hourly_pkg: list[float],
    cumulative_hourly: list[float],
    activity: list[dict],
    pill_board: dict,
    now_ms: int,
) -> dict[str, Any]:
    pb = pill_board or {}
    kpis_strip: list[dict] = list(pb.get("kpis") or [])
    hp = [float(x or 0) for x in hourly_pkg]
    cum = [float(x or 0) for x in cumulative_hourly]

    # --- sparklines (normalized 0–100-ish for chart readability) ---
    sp_units = _normalize_spark(_spark_from_series(hp, 1.0))
    sp_bags = _normalize_spark(_spark_from_series(hp, 0.85))
    sp_cyc = _normalize_spark([float(i) for i in range(24)])  # staircase proxy
    sp_oee = _normalize_spark([float(kpis.get("displays_vs_30d_pct") or 70) + i * 0.2 for i in range(24)])

    enriched_kpis: list[dict] = []
    for row in kpis_strip:
        rid = str(row.get("id") or "")
        sp = sp_units
        if rid == "bags":
            sp = sp_bags
        elif rid in ("cycles",):
            sp = sp_cyc
        elif rid == "avg_cycle":
            sp = list(reversed(sp_units))
        elif rid == "oee":
            sp = sp_oee
        elif rid == "on_time":
            sp = _normalize_spark(_spark_from_series(hp, 0.65))
        elif rid == "rework":
            sp = _normalize_spark([max(0.0, 5.0 - (i % 4)) for i in range(24)])

        er = dict(row)
        er["sparkline"] = sp
        enriched_kpis.append(er)

    # --- pipeline refs ---
    pipe = list((flow_intel or {}).get("pipeline") or [])
    by_id = {str(n.get("id")): n for n in pipe}

    def _wip(nid: str) -> int:
        n = by_id.get(nid) or {}
        return int(n.get("wip") or 0)

    def _dwell(nid: str) -> str | None:
        n = by_id.get(nid) or {}
        a = n.get("avg_delay_min")
        m = n.get("max_delay_min")
        if m is None and a is None:
            return None
        parts = []
        if m is not None:
            parts.append(f"Δ max {float(m):.0f}m")
        if a is not None:
            parts.append(f"avg {float(a):.0f}m")
        return " · ".join(parts)

    bl = _pick_station(machines, "blister")
    seals = _find_by_kind(machines, "sealing")
    s1 = seals[0] if len(seals) > 0 else None
    s2 = seals[1] if len(seals) > 1 else None
    pk = _pick_station(machines, "packaging")

    blister_lane = {
        "id": "lane_blister",
        "title": "Lane A · BLISTER SKU FLOW",
        "sku": (pb.get("lifelines") or [{}])[0].get("sku") if pb.get("lifelines") else "—",
        "stages": [
            {
                "key": "raw",
                "title": "Raw Material Receipt",
                "wip": 0,
                "bags": _wip("blister"),
                "dwell": None,
                "alert": None,
            },
            {
                "key": "m1",
                "title": "Machine 1 · DPP115 Blister",
                "wip": _wip("blister"),
                "bags": _wip("blister"),
                "dwell": None,
                "alert": "warn" if bl and str(bl.get("status")) != "running" else None,
                "alert_note": ("Bench idle · no run session" if bl and str(bl.get("status")) != "running" else None),
            },
            {
                "key": "stg1",
                "title": "Staging Queue",
                "wip": _wip("staging_bs"),
                "bags": _wip("staging_bs"),
                "dwell": _dwell("staging_bs"),
                "alert": (
                    "warn"
                    if str((flow_intel or {}).get("bottleneck", {}).get("stage_id") or "") == "staging_bs"
                    else None
                ),
                "alert_note": (
                    "Staging backlog"
                    if str((flow_intel or {}).get("bottleneck", {}).get("stage_id") or "") == "staging_bs"
                    else None
                ),
            },
            {
                "key": "m2",
                "title": "Machine 2 · Heat Seal",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": "warn" if s1 and str(s1.get("status")) == "idle" and _wip("staging_bs") > 0 else None,
                "alert_note": ("Heat seal idle · upstream queue > 0" if s1 and str(s1.get("status")) == "idle" and _wip("staging_bs") > 0 else None),
            },
            {
                "key": "m3",
                "title": "Machine 3 · Heat Seal",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": "warn" if s2 and str(s2.get("status")) == "idle" and _wip("staging_bs") > 1 else None,
                "alert_note": ("Second seal idle · queue depth elevated" if s2 and str(s2.get("status")) == "idle" and _wip("staging_bs") > 1 else None),
            },
            {
                "key": "stg2",
                "title": "Staging Queue",
                "wip": _wip("staging_bs"),
                "bags": _wip("staging_bs"),
                "dwell": _dwell("staging_bs"),
                "alert": None,
            },
            {
                "key": "pkg",
                "title": "Packaging Station",
                "wip": _wip("packaging"),
                "bags": _wip("packaging"),
                "dwell": None,
                "alert": None,
            },
            {
                "key": "done",
                "title": "Cycle Complete",
                "wip": 0,
                "bags": int(kpis.get("active_machines") or 0),
                "dwell": None,
                "alert": None,
            },
        ],
    }

    bottle_lane = {
        "id": "lane_bottle",
        "title": "Lane B · BOTTLE SKU FLOW",
        "sku": (pb.get("lifelines") or [{}, {}])[1].get("sku") if len(pb.get("lifelines") or []) > 1 else "—",
        "stages": [
            {"key": "br", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "m5", "title": "Machine 5 · Bottle Sealing", "wip": _wip("sealing"), "bags": _wip("sealing"), "dwell": None, "alert": None},
            {"key": "qa", "title": "Bottle QA Hold", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "fg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    card_lane = {
        "id": "lane_card",
        "title": "Lane C · CARD / STICKERING SKU FLOW",
        "sku": (pb.get("lifelines") or [{}, {}, {}])[2].get("sku") if len(pb.get("lifelines") or []) > 2 else "—",
        "stages": [
            {"key": "cr", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "m4", "title": "Card / Sticker Machine 4", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "cpk", "title": "Packaging", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "cfg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    lanes = [blister_lane, bottle_lane, card_lane]

    # --- SCADA slots (five canonical machines) mapped to ordered live stations ---
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
    slots = [
        {"slot": 1, "canonical": "Machine 1 · DPP115"},
        {"slot": 2, "canonical": "Machine 2 · Heat Press"},
        {"slot": 3, "canonical": "Machine 3 · Heat Press"},
        {"slot": 4, "canonical": "Machine 4 · Stickering"},
        {"slot": 5, "canonical": "Machine 5 · Bottle Sealing"},
    ]
    scada: list[dict] = []
    for s, m in zip(slots, slot_pick):
        mach_name = str((m or {}).get("display_name") or s["canonical"])
        st_vis = str((m or {}).get("status") or "idle")
        sk_ind = str((m or {}).get("station_kind") or "").lower()
        status_ui = {"running": "RUNNING", "paused": "WAITING", "idle": "IDLE"}.get(st_vis, "IDLE")
        if st_vis == "idle" and _wip("staging_bs") > 1 and sk_ind == "sealing":
            status_ui = "WAITING"
        util = float((m or {}).get("vs_hist_pct") or 0) + 70.0
        util = max(5.0, min(99.0, util))
        oee_m = round(float(pb.get("oee_donut", {}).get("total") or 70) * (util / 85.0), 1)
        last_scan = None
        try:
            if m and conn:
                r = conn.execute(
                    """
                    SELECT MAX(occurred_at) AS t FROM workflow_events
                    WHERE station_id = ?
                    """,
                    (int(m["id"]),),
                ).fetchone()
                if r and r["t"] is not None:
                    last_scan = int(r["t"])
        except Exception:
            pass

        scada.append(
            {
                "slot": s["slot"],
                "label": mach_name,
                "canonical": s["canonical"],
                "status": status_ui,
                "raw_status": st_vis,
                "bag_id": (m or {}).get("bag_id"),
                "sku": str((m or {}).get("product") or "—")[:64],
                "operator": "—",
                "timer_ms": (m or {}).get("occupancy_started_at_ms"),
                "counter_start": None,
                "counter_current": (m or {}).get("output_today"),
                "counter_end": None,
                "units_produced": (m or {}).get("output_today"),
                "cycle_elapsed_min": (m or {}).get("cycle_session_min"),
                "utilization_pct": round(util, 1),
                "oee_pct": oee_m,
                "last_scan_ms": last_scan,
            }
        )

    alerts = [
        {
            "at_ms": a.get("at_ms"),
            "message": a.get("message"),
            "severity": a.get("severity") or "info",
        }
        for a in (activity or [])[:14]
    ]

    return {
        "generated_at_ms": now_ms,
        "kpis": enriched_kpis,
        "lanes": lanes,
        "scada_machines": scada,
        "alerts": alerts,
        "pill_board": pb,
        "trend": pb.get("trend") or {},
        "cycle_analysis": pb.get("cycle_analysis") or {},
        "oee_donut": pb.get("oee_donut") or {},
        "inventory": pb.get("inventory") or [],
        "sku_table": pb.get("sku_table") or [],
        "staging": pb.get("staging") or [],
        "timeline": pb.get("timeline") or [],
        "team": pb.get("team") or [],
        "downtime": pb.get("downtime") or [],
    }
