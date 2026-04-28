"""
MES Command Center payload: flow maps, charts passthrough, metrics_inputs for client derivation.
Honest data only — KPI values are finalized in-browser via MesMetrics / metrics.ts from workflow_events.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app.services.command_center_metrics_inputs import build_metrics_inputs_bundle

_LOGGER_MES = logging.getLogger(__name__)


def _find_by_kind(machines: list[dict], kind: str) -> list[dict]:
    k = kind.lower()
    return [m for m in machines if str(m.get("station_kind") or "").lower() == k]


def _pick_station(machines: list[dict], kind: str, index: int = 0) -> dict | None:
    xs = _find_by_kind(machines, kind)
    if index < len(xs):
        return xs[index]
    return xs[0] if xs else None


def _stage_enrich(st: dict) -> dict:
    d = dict(st)
    qb = int(d.get("bags") or 0)
    qw = int(d.get("wip") or 0)
    d["queue_depth"] = max(qb, qw)
    al = str(d.get("alert") or "").lower()
    if al == "crit":
        d["status_level"] = "crit"
    elif al == "warn":
        d["status_level"] = "warn"
    else:
        d["status_level"] = "ok"
    return d


def _spark_real_only(hourly_pkg: list[float]) -> list[float] | None:
    hp = [float(x or 0) for x in hourly_pkg]
    if sum(hp) <= 1e-9:
        return None
    return [round(h, 2) for h in hp]


KPI_SLOTS: tuple[tuple[str, str], ...] = (
    ("bags", "Bags Today"),
    ("units", "Units Today"),
    ("cycles", "Production Cycles"),
    ("avg_cycle", "Avg Cycle Time"),
    ("oee", "OEE"),
    ("on_time", "On Time Completion"),
    ("rework", "Reject Rate"),
)


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
    day_start_ms: int,
    stations: list[dict] | None = None,
    benchmark_uh_hint: float | None = None,
) -> dict[str, Any]:
    pb = pill_board or {}
    hp = [float(x or 0) for x in hourly_pkg]
    trend_spark = _spark_real_only(hp)

    pace = kpis.get("benchmark_displays_pace_per_hour") or benchmark_uh_hint
    try:
        pace_f = float(pace) if pace is not None else None
    except (TypeError, ValueError):
        pace_f = None

    metrics_inputs = {}
    try:
        metrics_inputs = build_metrics_inputs_bundle(
            conn,
            machines,
            pace_f,
            day_start_ms=int(day_start_ms),
            now_ms=int(now_ms),
        )
    except Exception:
        _LOGGER_MES.exception("metrics_inputs_bundle")

    enriched_kpis: list[dict[str, Any]] = []
    for rid, disp in KPI_SLOTS:
        enriched_kpis.append(
            {
                "id": rid,
                "display_label": disp,
                "label": disp,
                "value": None,
                "value_pct": None,
                "sparkline": trend_spark,
                "delta_pct": None,
                "formula_note": "Computed client-side from scan timestamps and workflow_events (MesMetrics).",
            }
        )

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

    blister_lane = {
        "id": "lane_blister",
        "title": "BLISTER SKU",
        "sku": (pb.get("lifelines") or [{}])[0].get("sku") if pb.get("lifelines") else "—",
        "stages": [
            {"key": "raw", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {
                "key": "m1",
                "title": "DPP115",
                "wip": _wip("blister"),
                "bags": _wip("blister"),
                "dwell": None,
                "alert": "warn" if bl and str(bl.get("status")) != "running" else None,
                "alert_note": ("Idle" if bl and str(bl.get("status")) != "running" else None),
            },
            {
                "key": "stg1",
                "title": "Staging Q",
                "wip": _wip("staging_bs"),
                "bags": _wip("staging_bs"),
                "dwell": _dwell("staging_bs"),
                "alert": (
                    "warn"
                    if str((flow_intel or {}).get("bottleneck", {}).get("stage_id") or "") == "staging_bs"
                    else None
                ),
                "alert_note": (
                    "Backlog"
                    if str((flow_intel or {}).get("bottleneck", {}).get("stage_id") or "") == "staging_bs"
                    else None
                ),
            },
            {
                "key": "m2",
                "title": "Heat Seal · M2",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": None,
                "alert_note": None,
            },
            {
                "key": "m3",
                "title": "Heat Seal · M3",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": None,
                "alert_note": None,
            },
            {"key": "stg2", "title": "Staging Q", "wip": _wip("staging_bs"), "bags": _wip("staging_bs"), "dwell": None, "alert": None},
            {"key": "pkg", "title": "Packaging", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "done", "title": "Finished", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    bottle_lane = {
        "id": "lane_bottle",
        "title": "BOTTLE SKU",
        "subtitle": "",
        "sku": (pb.get("lifelines") or [{}, {}])[1].get("sku") if len(pb.get("lifelines") or []) > 1 else "—",
        "stages": [
            {"key": "br", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {
                "key": "m5",
                "title": "Bottle Sealer · M5",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": None,
                "integration_hint": "",
            },
            {"key": "qa", "title": "QA Hold", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "fg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    bottle_lane["subtitle"] = "Awaiting QR workflow setup · verify bottle sealing events"
    bottle_lane["stages"][1]["subtitle"] = "Requires SEALING_COMPLETE at mapped M5 station"

    card_lane = {
        "id": "lane_card",
        "title": "CARD SKU",
        "sku": (pb.get("lifelines") or [{}, {}, {}])[2].get("sku") if len(pb.get("lifelines") or []) > 2 else "—",
        "stages": [
            {"key": "cr", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "m4", "title": "Sticker · M4", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "cpk", "title": "Packaging", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "cfg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    for lane in (blister_lane, bottle_lane, card_lane):
        lane["stages"] = [_stage_enrich(s) for s in lane["stages"]]

    lanes = [blister_lane, bottle_lane, card_lane]

    _apply_bottle_seal_integration_flag(lanes, metrics_inputs.get("events") or [], metrics_inputs.get("slots") or [])

    alerts = [
        {
            "at_ms": a.get("at_ms"),
            "message": a.get("message"),
            "severity": a.get("severity") or "info",
        }
        for a in (activity or [])[:24]
    ]

    trend_out = dict(pb.get("trend") or {})
    if trend_spark is None:
        trend_out["labels"] = pb.get("trend", {}).get("labels") or []
        trend_out["series_valid"] = False
        trend_out["blister"] = []
        trend_out["bottle"] = []
        trend_out["card"] = []
    else:
        trend_out["series_valid"] = True

    decorate_lanes_with_congestion(lanes)

    oee_blank = {"total": None, "availability": None, "performance": None, "quality": None}

    return {
        "generated_at_ms": now_ms,
        "kpis": enriched_kpis,
        "lanes": lanes,
        "scada_machines": [],
        "alerts": alerts,
        "pill_board": pb,
        "trend": trend_out if trend_out else pb.get("trend") or {},
        "cycle_analysis": pb.get("cycle_analysis") or {},
        "oee_donut": oee_blank,
        "inventory": pb.get("inventory") or [],
        "sku_table": pb.get("sku_table") or [],
        "staging": pb.get("staging") or [],
        "timeline": pb.get("timeline") or [],
        "team": pb.get("team") or [],
        "downtime": pb.get("downtime") or [],
        "metrics_inputs": metrics_inputs,
    }


def _apply_bottle_seal_integration_flag(
    lanes: list[dict],
    events: list[dict],
    slots: list[dict],
) -> None:
    """M5 shows integrated only after a SEALING_COMPLETE at the mapped bottle station."""
    m5_sid: int | None = None
    for slot in slots or []:
        if slot.get("slot") == 5:
            sid = slot.get("stationId")
            m5_sid = int(sid) if sid is not None else None
            break
    has_event = False
    if m5_sid is not None:
        for e in events or []:
            if e.get("stationId") is None:
                continue
            try:
                if int(e["stationId"]) != m5_sid:
                    continue
            except (TypeError, ValueError):
                continue
            if str(e.get("eventType")) == "SEALING_COMPLETE":
                has_event = True
                break

    for ln in lanes:
        if ln.get("id") != "lane_bottle":
            continue
        for st in ln.get("stages") or []:
            if st.get("key") == "m5":
                st["bottleSealIntegrated"] = has_event


def decorate_lanes_with_congestion(lanes: list[dict]) -> None:
    """Minimal pulse from queue depths when present."""
    for ln in lanes:
        depths: list[float] = []
        for sd in ln.get("stages") or []:
            qd = float(sd.get("queue_depth") or 0)
            depths.append(qd)
        mx = max(depths + [1.0])
        for sd in ln.get("stages") or []:
            qw = float(sd.get("queue_depth") or 0)
            sd["congestion_pulse"] = round(max(0.05, min(1.0, qw / mx * 0.74)), 3)
