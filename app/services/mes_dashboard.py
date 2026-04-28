"""
MES Command Center payload: KPI strip, horizontal flow maps, SCADA grid, analytics passthrough.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app.services.mes_pharmaceutical_intel import (
    build_pharmaceutical_mes_intel,
    merge_oee_into_kpis,
)

_LOGGER_MES = logging.getLogger(__name__)


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
) -> dict[str, Any]:
    pb = pill_board or {}
    kpis_strip: list[dict] = list(pb.get("kpis") or [])
    hp = [float(x or 0) for x in hourly_pkg]

    sp_units = _normalize_spark(_spark_from_series(hp, 1.0))
    sp_bags = _normalize_spark(_spark_from_series(hp, 0.85))
    sp_cyc = _normalize_spark([float(i) for i in range(24)])
    sp_oee = _normalize_spark([float(kpis.get("displays_vs_30d_pct") or 70) + i * 0.2 for i in range(24)])

    by_rid = {str(r.get("id") or ""): dict(r) for r in kpis_strip}

    enriched_kpis: list[dict] = []
    for rid, disp in KPI_SLOTS:
        row = dict(by_rid.get(rid, {}))
        row["id"] = rid
        row["display_label"] = disp
        row["label"] = disp
        sp = sp_units
        if rid == "bags":
            sp = sp_bags
        elif rid == "cycles":
            sp = sp_cyc
        elif rid == "avg_cycle":
            sp = list(reversed(sp_units))
        elif rid == "oee":
            sp = sp_oee
        elif rid == "on_time":
            sp = _normalize_spark(_spark_from_series(hp, 0.65))
        elif rid == "rework":
            sp = _normalize_spark([max(0.0, 5.0 - (i % 4)) for i in range(24)])
        row["sparkline"] = sp
        enriched_kpis.append(row)

    pharma_intel: dict[str, Any] = {}
    try:
        pharma_intel = build_pharmaceutical_mes_intel(
            conn,
            machines,
            kpis,
            flow_intel,
            pb or {},
            int(day_start_ms),
            float(now_ms),
            stations or [],
        )
        merge_oee_into_kpis(enriched_kpis, pharma_intel)
    except Exception:
        _LOGGER_MES.exception("build_pharmaceutical_mes_intel")

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
            {
                "key": "raw",
                "title": "Raw Material",
                "wip": 0,
                "bags": _wip("blister"),
                "dwell": None,
                "alert": None,
            },
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
                "alert": "warn"
                if s1 and str(s1.get("status")) == "idle" and _wip("staging_bs") > 0
                else None,
                "alert_note": ("Idle · Q>0" if s1 and str(s1.get("status")) == "idle" and _wip("staging_bs") > 0 else None),
            },
            {
                "key": "m3",
                "title": "Heat Seal · M3",
                "wip": _wip("sealing"),
                "bags": _wip("sealing"),
                "dwell": None,
                "alert": "warn"
                if s2 and str(s2.get("status")) == "idle" and _wip("staging_bs") > 1
                else None,
                "alert_note": ("Alt path idle" if s2 and str(s2.get("status")) == "idle" and _wip("staging_bs") > 1 else None),
            },
            {
                "key": "stg2",
                "title": "Staging Q",
                "wip": _wip("staging_bs"),
                "bags": _wip("staging_bs"),
                "dwell": _dwell("staging_bs"),
                "alert": None,
            },
            {
                "key": "pkg",
                "title": "Packaging",
                "wip": _wip("packaging"),
                "bags": _wip("packaging"),
                "dwell": None,
                "alert": None,
            },
            {
                "key": "done",
                "title": "Finished",
                "wip": 0,
                "bags": int(kpis.get("active_machines") or 0),
                "dwell": None,
                "alert": None,
            },
        ],
    }

    bottle_lane = {
        "id": "lane_bottle",
        "title": "BOTTLE SKU",
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
            },
            {"key": "qa", "title": "QA Hold", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {"key": "fg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    card_lane = {
        "id": "lane_card",
        "title": "CARD SKU",
        "sku": (pb.get("lifelines") or [{}, {}, {}])[2].get("sku") if len(pb.get("lifelines") or []) > 2 else "—",
        "stages": [
            {"key": "cr", "title": "Raw Material", "wip": 0, "bags": 0, "dwell": None, "alert": None},
            {
                "key": "m4",
                "title": "Sticker · M4",
                "wip": _wip("packaging"),
                "bags": _wip("packaging"),
                "dwell": None,
                "alert": None,
            },
            {"key": "cpk", "title": "Packaging", "wip": _wip("packaging"), "bags": _wip("packaging"), "dwell": None, "alert": None},
            {"key": "cfg", "title": "Finished Goods", "wip": 0, "bags": 0, "dwell": None, "alert": None},
        ],
    }

    for lane in (blister_lane, bottle_lane, card_lane):
        lane["stages"] = [_stage_enrich(s) for s in lane["stages"]]

    lanes = [blister_lane, bottle_lane, card_lane]

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
        {"slot": 1, "canonical": "M1 DPP115", "short": "M1 DPP115"},
        {"slot": 2, "canonical": "M2 Heat Seal", "short": "M2 Heat Seal"},
        {"slot": 3, "canonical": "M3 Heat Seal", "short": "M3 Heat Seal"},
        {"slot": 4, "canonical": "M4 Stickering", "short": "M4 Stickering"},
        {"slot": 5, "canonical": "M5 Bottle Sealer", "short": "M5 Bottle Sealer"},
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
        if pharma_intel:
            oee_m = round(float(pharma_intel.get("oee_pct") or 76) * (util / 89.0), 1)
        else:
            oee_m = round(float(pb.get("oee_donut", {}).get("total") or 70) * (util / 85.0), 1)
        last_scan = None
        tph = float((m or {}).get("rate_today_uh") or 0) if m else 0.0
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

        lt = {"running": "run", "paused": "wait", "idle": "idle", "fault": "fault"}.get(st_vis, "idle")
        scada.append(
            {
                "slot": s["slot"],
                "twin_slot": int(s["slot"]),
                "label": mach_name,
                "canonical": s["canonical"],
                "short_label": s["short"],
                "status": status_ui,
                "status_light": lt,
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
                "throughput_uh": round(tph, 1),
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
        for a in (activity or [])[:24]
    ]

    oee_donut = dict(pb.get("oee_donut") or {})
    if pharma_intel:
        oee_donut = {
            "total": round(float(pharma_intel.get("oee_pct") or oee_donut.get("total") or 0), 2),
            "availability": round(float(pharma_intel.get("availability_pct") or oee_donut.get("availability") or 0), 2),

            "performance": round(float(pharma_intel.get("performance_pct") or oee_donut.get("performance") or 0), 2),

            "quality": round(float(pharma_intel.get("quality_pct") or oee_donut.get("quality") or 0), 2),

        }

    out: dict[str, Any] = {
        "generated_at_ms": now_ms,

        "kpis": enriched_kpis,

        "lanes": lanes,

        "scada_machines": scada,

        "alerts": alerts,

        "pill_board": pb,

        "trend": pb.get("trend") or {},

        "cycle_analysis": pb.get("cycle_analysis") or {},

        "oee_donut": oee_donut,

        "inventory": pb.get("inventory") or [],

        "sku_table": pb.get("sku_table") or [],

        "staging": pb.get("staging") or [],

        "timeline": pb.get("timeline") or [],

        "team": pb.get("team") or [],

        "downtime": pb.get("downtime") or [],

        "pharma_intel": pharma_intel,

    }


    heat_st = (pharma_intel.get("bottleneck_heatmap") or {}).get("stages") or []

    try:

        max_h = max((float(h.get("heat") or 0) for h in heat_st), default=0.5) or 0.55

        for ln in lanes:

            for sd in ln.get("stages") or []:

                if str(sd.get("status_level")) != "crit":


                    qw = float(sd.get("queue_depth") or 0)

                    sd["congestion_pulse"] = round(_clamp_pulse(qw, max_h), 3)

    except Exception:
        pass

    return out


def _clamp_pulse(qw: float, mx: float) -> float:
    mx = mx if mx > 1e-6 else 1.0
    return max(0.05, min(1.0, qw / mx * 0.74))
