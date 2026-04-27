"""
Production flow / staging metrics for the operations TV board.

Models Blister → (staging) → Sealing → (staging) → Packaging using workflow_events.
"""

from __future__ import annotations

import sqlite3
from itertools import groupby
from statistics import mean

WARN_MIN = 45.0
CRIT_MIN = 120.0


def _alert_for_staging(wip: int, delays: list[float]) -> str:
    if not delays and wip == 0:
        return "ok"
    mx = max(delays) if delays else 0.0
    if mx >= CRIT_MIN or wip >= 4:
        return "crit"
    if mx >= WARN_MIN or wip >= 2:
        return "warn"
    return "ok"


def _wip_occupied(stations: list[dict], station_live: dict[int, dict], kinds: frozenset[str]) -> int:
    n = 0
    for s in stations:
        sk = str(s.get("station_kind") or "").lower()
        if sk not in kinds:
            continue
        sid = int(s["id"])
        live = station_live.get(sid) or {}
        if str(live.get("status") or "idle").lower() in ("occupied", "paused"):
            n += 1
    return n


def compute_production_flow_intel(
    conn: sqlite3.Connection,
    now_ms: int,
    stations: list[dict],
    station_live: dict[int, dict],
) -> dict:
    """Staging delays, WIP-style counts, bottleneck hint — no HTML tables."""
    blister_kinds = frozenset({"blister", "combined"})
    sealing_kinds = frozenset({"sealing", "combined"})
    packaging_kinds = frozenset({"packaging"})

    wip_blister = _wip_occupied(stations, station_live, blister_kinds)
    wip_seal = _wip_occupied(stations, station_live, sealing_kinds)
    wip_pack = _wip_occupied(stations, station_live, packaging_kinds)

    bag_ids: set[int] = set()
    cutoff = now_ms - 72 * 3600 * 1000
    try:
        for r in conn.execute(
            """
            SELECT DISTINCT workflow_bag_id FROM workflow_events
            WHERE workflow_bag_id IS NOT NULL AND occurred_at >= ?
            """,
            (cutoff,),
        ).fetchall():
            bag_ids.add(int(r[0]))
        for r in conn.execute(
            "SELECT assigned_workflow_bag_id FROM qr_cards WHERE assigned_workflow_bag_id IS NOT NULL"
        ).fetchall():
            bag_ids.add(int(r[0]))
    except sqlite3.OperationalError:
        bag_ids = set()

    ids = list(bag_ids)[:400]
    delays_bs: list[float] = []
    delays_sp: list[float] = []

    if ids:
        qmarks = ",".join("?" * len(ids))
        try:
            rows = conn.execute(
                f"""
                SELECT we.workflow_bag_id, we.event_type, we.occurred_at, we.station_id,
                       COALESCE(ws.station_kind, '') AS skind,
                       json_extract(we.payload, '$.reason') AS preason
                FROM workflow_events we
                LEFT JOIN workflow_stations ws ON ws.id = we.station_id
                WHERE we.workflow_bag_id IN ({qmarks})
                ORDER BY we.workflow_bag_id, we.occurred_at, we.id
                """,
                ids,
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        for bid, group in groupby(rows, key=lambda r: int(r["workflow_bag_id"])):
            evs = list(group)
            if any(r["event_type"] == "BAG_FINALIZED" for r in evs):
                continue
            t_blister = None
            t_seal_done = None
            t_pack_final = None
            first_seal_claim = None
            first_pack_claim = None
            first_pack_snap = None
            for r in evs:
                et = str(r["event_type"])
                t = int(r["occurred_at"] or 0)
                sk = str(r["skind"] or "").lower()
                if et == "BLISTER_COMPLETE" and sk in blister_kinds:
                    t_blister = t if t_blister is None else max(t_blister, t)
                elif et == "SEALING_COMPLETE":
                    t_seal_done = t if t_seal_done is None else max(t_seal_done, t)
                elif et == "BAG_FINALIZED":
                    t_pack_final = t
                elif et == "BAG_CLAIMED":
                    if sk == "sealing" or (sk == "combined" and t_blister is not None):
                        first_seal_claim = t if first_seal_claim is None else min(first_seal_claim, t)
                    if sk == "packaging":
                        first_pack_claim = t if first_pack_claim is None else min(first_pack_claim, t)
                elif et == "PACKAGING_SNAPSHOT":
                    first_pack_snap = t if first_pack_snap is None else min(first_pack_snap, t)
                    pr = str(r["preason"] or "").strip()
                    if pr == "final_submit":
                        t_pack_final = t

            if t_blister and not t_seal_done:
                end = first_seal_claim or now_ms
                if end > t_blister:
                    delays_bs.append((end - t_blister) / 60000.0)
            if t_seal_done and not t_pack_final:
                cand = [x for x in (first_pack_claim, first_pack_snap) if x is not None]
                if cand:
                    ps = min(cand)
                    w = max(0.0, (ps - t_seal_done) / 60000.0)
                else:
                    w = (now_ms - t_seal_done) / 60000.0
                delays_sp.append(w)

    wip_staging_bs = len(delays_bs)
    wip_staging_sp = len(delays_sp)
    avg_bs = round(mean(delays_bs), 1) if delays_bs else None
    max_bs = round(max(delays_bs), 1) if delays_bs else None
    avg_sp = round(mean(delays_sp), 1) if delays_sp else None
    max_sp = round(max(delays_sp), 1) if delays_sp else None

    alert_bs = _alert_for_staging(wip_staging_bs, delays_bs)
    alert_sp = _alert_for_staging(wip_staging_sp, delays_sp)

    pipeline = [
        {
            "id": "blister",
            "label": "Blister",
            "wip": wip_blister,
            "subtitle": "stations active",
            "avg_delay_min": None,
            "max_delay_min": None,
            "alert": "crit" if wip_blister >= 4 else ("warn" if wip_blister >= 2 else "ok"),
        },
        {
            "id": "staging_bs",
            "label": "Staging",
            "wip": wip_staging_bs,
            "subtitle": "→ sealing · batches waiting",
            "avg_delay_min": avg_bs,
            "max_delay_min": max_bs,
            "alert": alert_bs,
        },
        {
            "id": "sealing",
            "label": "Sealing",
            "wip": wip_seal,
            "subtitle": "stations active",
            "avg_delay_min": None,
            "max_delay_min": None,
            "alert": "crit" if wip_seal >= 4 else ("warn" if wip_seal >= 2 else "ok"),
        },
        {
            "id": "staging_sp",
            "label": "Staging",
            "wip": wip_staging_sp,
            "subtitle": "→ packaging · batches waiting",
            "avg_delay_min": avg_sp,
            "max_delay_min": max_sp,
            "alert": alert_sp,
        },
        {
            "id": "packaging",
            "label": "Packaging",
            "wip": wip_pack,
            "subtitle": "stations active",
            "avg_delay_min": None,
            "max_delay_min": None,
            "alert": "crit" if wip_pack >= 3 else ("warn" if wip_pack >= 1 else "ok"),
        },
    ]

    scores = []
    for n in pipeline:
        d = float(n.get("max_delay_min") or 0)
        w = int(n.get("wip") or 0)
        scores.append((d + w * 12.0, n["id"], n))
    bottleneck_id = "staging_bs"
    bottleneck_node = pipeline[1]
    reason = "Monitor staging queues"
    hint = "Watch blister-to-sealing handoff."
    if scores:
        scores.sort(reverse=True)
        bottleneck_id = scores[0][1]
        bottleneck_node = scores[0][2]
        if bottleneck_id == "staging_bs":
            reason = "Batches waiting after blister"
            hint = "Free sealing capacity or move work to sealing."
        elif bottleneck_id == "staging_sp":
            reason = "Batches waiting after sealing"
            hint = "Open packaging or pull sealed WIP forward."
        elif bottleneck_id in ("blister", "sealing", "packaging"):
            reason = f"High WIP at {bottleneck_node['label']}"
            hint = "Balance crew or relieve upstream delay."

    return {
        "thresholds": {"warn_min": WARN_MIN, "crit_min": CRIT_MIN},
        "pipeline": pipeline,
        "bottleneck": {
            "stage_id": bottleneck_id,
            "label": bottleneck_node.get("label"),
            "reason": reason,
            "hint": hint,
            "max_delay_min": bottleneck_node.get("max_delay_min"),
            "wip": bottleneck_node.get("wip"),
        },
    }
