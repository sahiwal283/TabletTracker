"""
Admin routes
"""
import json
import re
import secrets
import sqlite3
import statistics
import traceback
import unicodedata
from collections import defaultdict
from datetime import datetime
from time import time as epoch_time

from config import Config
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.blueprints.workflow_floor import _current_station_occupancy
from app.blueprints.workflow_staff import ASSIGN_BAG_RETURN_COMMAND_CENTER, _load_workflow_products
from app.services import workflow_constants as WC
from app.services.workflow_finalize import force_release_card
from app.services.workflow_txn import run_with_busy_retry
from app.utils.auth_utils import admin_required
from app.utils.db_utils import db_read_only, db_transaction, get_db
from app.utils.route_helpers import ensure_app_settings_table
from app.utils.version_display import read_version_constants
from app.services.ops_flow_intel import compute_production_flow_intel

bp = Blueprint('admin', __name__)

# QR / URL path–safe scan tokens (stations: /workflow/station/<token>; bag cards: floor API card_token)
_STATION_SCAN_TOKEN_RE = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")

_VALID_STATION_KINDS = frozenset({"sealing", "blister", "packaging", "combined"})
_STATION_KIND_ORDER = ["sealing", "blister", "packaging", "combined"]


def _workflow_inventory_bag_name(conn: sqlite3.Connection, inventory_bag_id: int | None) -> str:
    """PO-shipment-box-bag label for workflow/admin tables."""
    if not inventory_bag_id:
        return "—"
    try:
        row = conn.execute(
            """
            SELECT po.po_number, COALESCE(r.shipment_number, 1) AS shipment_number,
                   sb.box_number, b.bag_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE b.id = ?
            """,
            (int(inventory_bag_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        row = conn.execute(
            """
            SELECT po.po_number, 1 AS shipment_number, sb.box_number, b.bag_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE b.id = ?
            """,
            (int(inventory_bag_id),),
        ).fetchone()
    if not row:
        return f"bag-{int(inventory_bag_id)}"
    po_num = (row["po_number"] or f"REC{int(inventory_bag_id)}").strip()
    return f"{po_num}-{int(row['shipment_number'])}-{row['box_number']}-{row['bag_number']}"


def _ny_today_bounds_ms() -> tuple[int, int, str]:
    """Factory-local day bounds in America/New_York for workflow floor stats."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (
        int(start.timestamp() * 1000),
        int(end.timestamp() * 1000),
        start.date().isoformat(),
    )


def _floor_station_day_stats(conn: sqlite3.Connection, start_ms: int, end_ms: int) -> dict[int, dict]:
    """Per-station workflow event counts and average count totals for the ops board."""
    by: dict[int, dict] = {}
    try:
        rows = conn.execute(
            """
            SELECT station_id, event_type, COUNT(*) AS cnt
            FROM workflow_events
            WHERE station_id IS NOT NULL
              AND occurred_at >= ? AND occurred_at < ?
              AND event_type IN (
                'BAG_CLAIMED',
                'BLISTER_COMPLETE',
                'SEALING_COMPLETE',
                'PACKAGING_SNAPSHOT',
                'STATION_RESUMED'
              )
            GROUP BY station_id, event_type
            """,
            (start_ms, end_ms),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    for r in rows:
        sid = int(r["station_id"])
        by.setdefault(sid, {})[str(r["event_type"])] = int(r["cnt"])
    try:
        for r in conn.execute(
            """
            SELECT station_id,
                   AVG(CAST(json_extract(payload, '$.count_total') AS REAL)) AS avg_ct,
                   COUNT(*) AS n
            FROM workflow_events
            WHERE event_type = 'BLISTER_COMPLETE'
              AND occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND json_extract(payload, '$.count_total') IS NOT NULL
            GROUP BY station_id
            """,
            (start_ms, end_ms),
        ).fetchall():
            sid = int(r["station_id"])
            b = by.setdefault(sid, {})
            b["_avg_blister"] = float(r["avg_ct"]) if r["avg_ct"] is not None else None
            b["_n_blister_avg"] = int(r["n"])
        for r in conn.execute(
            """
            SELECT station_id,
                   AVG(CAST(json_extract(payload, '$.count_total') AS REAL)) AS avg_ct,
                   COUNT(*) AS n
            FROM workflow_events
            WHERE event_type = 'SEALING_COMPLETE'
              AND occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND json_extract(payload, '$.count_total') IS NOT NULL
            GROUP BY station_id
            """,
            (start_ms, end_ms),
        ).fetchall():
            sid = int(r["station_id"])
            b = by.setdefault(sid, {})
            b["_avg_sealing"] = float(r["avg_ct"]) if r["avg_ct"] is not None else None
            b["_n_sealing_avg"] = int(r["n"])
    except sqlite3.OperationalError:
        pass
    return by


def _floor_ops_overview(
    stations: list[dict],
    station_live: dict[int, dict],
    floor_station_day_stats: dict[int, dict],
    cards: list[dict],
) -> dict[str, int]:
    """Roll-up counts for the Command Center ops header (single-pane KPI strip)."""
    occ = pau = idl = 0
    for s in stations:
        sid = int(s["id"])
        st = str((station_live.get(sid) or {}).get("status") or "idle").lower()
        if st == "occupied":
            occ += 1
        elif st == "paused":
            pau += 1
        else:
            idl += 1
    t_claims = t_res = t_bl = t_se = t_pk = 0
    for d in floor_station_day_stats.values():
        t_claims += int(d.get("BAG_CLAIMED") or 0)
        t_res += int(d.get("STATION_RESUMED") or 0)
        t_bl += int(d.get("BLISTER_COMPLETE") or 0)
        t_se += int(d.get("SEALING_COMPLETE") or 0)
        t_pk += int(d.get("PACKAGING_SNAPSHOT") or 0)
    on_bag = sum(1 for c in cards if c.get("assigned_workflow_bag_id"))
    n_cards = len(cards)
    return {
        "stations_total": len(stations),
        "stations_occupied": occ,
        "stations_paused": pau,
        "stations_idle": idl,
        "today_claims": t_claims,
        "today_resumes": t_res,
        "today_blister": t_bl,
        "today_seal": t_se,
        "today_pack": t_pk,
        "cards_total": n_cards,
        "cards_on_bag": on_bag,
        "cards_idle": max(0, n_cards - on_bag),
    }


def _ops_tv_daily_target_tablets(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            """
            SELECT setting_value FROM app_settings
            WHERE setting_key = 'ops_tv_daily_output_target'
            """,
        ).fetchone()
        if row:
            raw = dict(row).get("setting_value") if hasattr(row, "keys") else row[0]
            if raw is not None and str(raw).strip() != "":
                return max(1, int(float(str(raw).strip())))
    except (sqlite3.OperationalError, TypeError, ValueError):
        pass
    return 800


def _hist_station_totals_7d(conn: sqlite3.Connection, today_start_ms: int) -> dict[int, float]:
    """Tablets + packaging displays per station for the 7 NY days before today_start_ms."""
    hist_start = today_start_ms - 7 * 24 * 3600 * 1000
    out: dict[int, float] = defaultdict(float)
    try:
        for r in conn.execute(
            """
            SELECT station_id,
                   COALESCE(SUM(CAST(json_extract(payload, '$.count_total') AS REAL)), 0) AS tablets
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE')
              AND json_extract(payload, '$.count_total') IS NOT NULL
            GROUP BY station_id
            """,
            (hist_start, today_start_ms),
        ).fetchall():
            out[int(r["station_id"])] = float(r["tablets"] or 0)
        for r in conn.execute(
            """
            SELECT station_id,
                   COALESCE(SUM(CAST(json_extract(payload, '$.display_count') AS REAL)), 0) AS d
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND event_type = 'PACKAGING_SNAPSHOT'
              AND json_extract(payload, '$.display_count') IS NOT NULL
            GROUP BY station_id
            """,
            (hist_start, today_start_ms),
        ).fetchall():
            out[int(r["station_id"])] += float(r["d"] or 0)
    except sqlite3.OperationalError:
        pass
    return out


def _latest_bag_claim_ms(conn: sqlite3.Connection, workflow_bag_id: int, station_id: int) -> int | None:
    try:
        r = conn.execute(
            """
            SELECT MAX(occurred_at) AS t
            FROM workflow_events
            WHERE workflow_bag_id = ? AND station_id = ? AND event_type = 'BAG_CLAIMED'
            """,
            (workflow_bag_id, station_id),
        ).fetchone()
        if r and r["t"] is not None:
            return int(r["t"])
    except sqlite3.OperationalError:
        pass
    return None


def _session_tablets_since_claim(
    conn: sqlite3.Connection, workflow_bag_id: int, station_id: int, claim_ms: int
) -> float:
    try:
        r = conn.execute(
            """
            SELECT COALESCE(SUM(
              CASE
                WHEN event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE') THEN
                  COALESCE(CAST(json_extract(payload, '$.count_total') AS REAL), 0)
                WHEN event_type = 'PACKAGING_SNAPSHOT' THEN
                  COALESCE(CAST(json_extract(payload, '$.display_count') AS REAL), 0)
                ELSE 0
              END
            ), 0) AS s
            FROM workflow_events
            WHERE workflow_bag_id = ? AND station_id = ? AND occurred_at >= ?
            """,
            (workflow_bag_id, station_id, claim_ms),
        ).fetchone()
        return float(r["s"] or 0) if r else 0.0
    except sqlite3.OperationalError:
        return 0.0


def _ops_smart_alerts(
    now_ms: int,
    kpis: dict,
    targets: dict,
    machines: list[dict],
    flow_intel: dict,
) -> list[dict]:
    """High-signal alerts for the TV ticker (prepended before raw activity)."""
    out: list[dict] = []
    pct_floor = float(kpis.get("throughput_pct") or 0)
    tgt = int(targets.get("daily_output_tablets") or 800)
    if pct_floor < 80.0:
        out.append(
            {
                "at_ms": now_ms,
                "message": f"Floor output {pct_floor:.0f}% of daily target ({tgt:,} tablets) — behind pace",
                "severity": "warn",
            }
        )
    elif pct_floor >= 100.0:
        out.append(
            {
                "at_ms": now_ms,
                "message": f"Floor output at {pct_floor:.0f}% of target — on or ahead of pace",
                "severity": "info",
            }
        )

    bn = (flow_intel or {}).get("bottleneck") or {}
    reason = str(bn.get("reason") or "").strip()
    if reason:
        hint = str(bn.get("hint") or "").strip()
        mx = bn.get("max_delay_min")
        sev = (
            "warn"
            if mx is not None and float(mx) >= 45.0
            else "info"
        )
        msg = reason if not hint else f"{reason} — {hint}"
        out.append({"at_ms": now_ms, "message": msg, "severity": sev})

    for m in machines:
        if m.get("perf_tier") == "below" and m.get("status") == "running":
            hint = str(m.get("perf_hint") or "Below 7d avg rate")
            out.append(
                {
                    "at_ms": now_ms,
                    "message": f"{m.get('display_name') or 'Station'}: {hint}",
                    "severity": "warn",
                }
            )

    wip_pack = 0
    for n in (flow_intel or {}).get("pipeline") or []:
        if n.get("id") == "packaging":
            wip_pack = int(n.get("wip") or 0)
            break
    idle_pack_bench = sum(
        1
        for m in machines
        if str(m.get("station_kind") or "").lower() == "packaging" and m.get("status") == "idle"
    )
    if wip_pack >= 2 and idle_pack_bench > 0:
        out.append(
            {
                "at_ms": now_ms,
                "message": "Packaging idle while downstream WIP exists — check handoff",
                "severity": "warn",
            }
        )

    return out


def build_ops_tv_snapshot(conn: sqlite3.Connection) -> dict:
    """JSON payload for the TV operations dashboard (no HTML tables; data only)."""
    start_ms, end_ms, date_label = _ny_today_bounds_ms()
    now_ms = int(epoch_time() * 1000)

    stations: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT ws.id, ws.label, ws.station_scan_token, ws.station_code, ws.machine_id,
                   m.machine_name AS machine_name,
                   COALESCE(ws.station_kind, 'sealing') AS station_kind
            FROM workflow_stations ws
            LEFT JOIN machines m ON m.id = ws.machine_id
            ORDER BY ws.station_kind, ws.id
            """
        ).fetchall()
        stations = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        try:
            rows = conn.execute(
                """
                SELECT id, label, station_scan_token, station_code, NULL AS machine_id,
                       NULL AS machine_name, 'sealing' AS station_kind
                FROM workflow_stations
                ORDER BY id
                """
            ).fetchall()
            stations = [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass

    station_live: dict[int, dict] = {}
    for st in stations:
        sid = int(st["id"])
        station_live[sid] = {
            "status": "idle",
            "workflow_bag_id": None,
            "card_token": None,
            "occupancy_started_at": None,
            "product_name": None,
            "receipt_number": None,
            "bag_name": None,
        }
    for st in stations:
        sid = int(st["id"])
        occ = _current_station_occupancy(conn, sid)
        if not occ:
            continue
        wid = int(occ["workflow_bag_id"])
        bag_row = conn.execute(
            """
            SELECT wb.id, wb.receipt_number, wb.product_id, pd.product_name, wb.inventory_bag_id
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE wb.id = ?
            """,
            (wid,),
        ).fetchone()
        bd = dict(bag_row) if bag_row else {}
        station_live[sid] = {
            "status": occ["status"],
            "workflow_bag_id": wid,
            "card_token": occ.get("card_token"),
            "occupancy_started_at": occ.get("occupancy_started_at_ms"),
            "product_name": bd.get("product_name"),
            "flavor": bd.get("product_name"),
            "receipt_number": bd.get("receipt_number"),
            "bag_name": _workflow_inventory_bag_name(conn, bd.get("inventory_bag_id")),
        }

    daily_target = _ops_tv_daily_target_tablets(conn)
    total_out = 0.0
    try:
        r = conn.execute(
            """
            SELECT COALESCE(SUM(CAST(json_extract(payload, '$.count_total') AS REAL)), 0) AS s
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE')
              AND json_extract(payload, '$.count_total') IS NOT NULL
            """,
            (start_ms, end_ms),
        ).fetchone()
        total_out = float(r["s"] or 0) if r else 0.0
    except sqlite3.OperationalError:
        pass

    throughput_pct = min(199.0, (total_out / float(daily_target)) * 100.0) if daily_target else 0.0

    per_out: dict[int, float] = {}
    try:
        for r in conn.execute(
            """
            SELECT station_id,
                   COALESCE(SUM(CAST(json_extract(payload, '$.count_total') AS REAL)), 0) AS tablets
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE')
              AND json_extract(payload, '$.count_total') IS NOT NULL
            GROUP BY station_id
            """,
            (start_ms, end_ms),
        ).fetchall():
            per_out[int(r["station_id"])] = float(r["tablets"] or 0)
    except sqlite3.OperationalError:
        pass

    hourly = [0.0] * 24
    station_hourly: dict[int, list[float]] = defaultdict(lambda: [0.0] * 24)
    try:
        q = """
            SELECT station_id,
                   CAST((occurred_at - ?) / 3600000 AS INTEGER) AS hr,
                   COALESCE(SUM(CAST(json_extract(payload, '$.count_total') AS REAL)), 0) AS v
            FROM workflow_events
            WHERE occurred_at >= ? AND occurred_at < ?
              AND station_id IS NOT NULL
              AND event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE')
              AND json_extract(payload, '$.count_total') IS NOT NULL
            GROUP BY station_id, hr
            """
        for r in conn.execute(q, (start_ms, start_ms, end_ms)).fetchall():
            hr = int(r["hr"])
            if 0 <= hr < 24:
                v = float(r["v"] or 0)
                hourly[hr] += v
                station_hourly[int(r["station_id"])][hr] += v
    except sqlite3.OperationalError:
        pass

    cumulative_hourly: list[float] = []
    run = 0.0
    for h in range(24):
        run += hourly[h]
        cumulative_hourly.append(round(run, 1))

    cycle_mins: list[float] = []
    try:
        for r in conn.execute(
            """
            WITH claims AS (
                SELECT workflow_bag_id, station_id, occurred_at AS t0
                FROM workflow_events
                WHERE event_type = 'BAG_CLAIMED'
                  AND occurred_at >= ? AND occurred_at < ?
            ),
            seals AS (
                SELECT workflow_bag_id, station_id, MIN(occurred_at) AS t1
                FROM workflow_events
                WHERE event_type = 'SEALING_COMPLETE'
                  AND occurred_at >= ? AND occurred_at < ?
                GROUP BY workflow_bag_id, station_id
            )
            SELECT (s.t1 - c.t0) / 60000.0 AS cm
            FROM claims c
            JOIN seals s
              ON s.workflow_bag_id = c.workflow_bag_id
             AND s.station_id = c.station_id
            WHERE s.t1 > c.t0 AND (s.t1 - c.t0) <= 7200000
            """,
            (start_ms, end_ms, start_ms, end_ms),
        ).fetchall():
            cycle_mins.append(float(r["cm"]))
    except sqlite3.OperationalError:
        pass
    avg_cycle: float | None
    if len(cycle_mins) >= 3:
        avg_cycle = round(float(statistics.median(cycle_mins)), 1)
    elif cycle_mins:
        avg_cycle = round(float(statistics.mean(cycle_mins)), 1)
    else:
        avg_cycle = None

    cur_h = int((now_ms - start_ms) // 3600000)
    cur_h = min(23, max(0, cur_h))

    occupied = idle = paused = 0
    machines: list[dict] = []
    for s in stations:
        sid = int(s["id"])
        live = station_live.get(sid) or {}
        st = str(live.get("status") or "idle").lower()
        if st == "occupied":
            occupied += 1
            vis = "running"
        elif st == "paused":
            paused += 1
            vis = "paused"
        else:
            idle += 1
            vis = "idle"
        display_name = (s.get("machine_name") or s.get("label") or f"Station {sid}").strip()
        product = (live.get("flavor") or live.get("product_name") or "—") or "—"
        spark: list[float] = []
        sh = station_hourly.get(sid, [0.0] * 24)
        for i in range(6):
            h = cur_h - (5 - i)
            spark.append(round(sh[h], 1) if h >= 0 else 0.0)
        out_today = int(round(per_out.get(sid, 0.0)))
        machines.append(
            {
                "id": sid,
                "display_name": display_name,
                "station_label": str(s.get("label") or ""),
                "station_kind": str(s.get("station_kind") or ""),
                "status": vis,
                "product": str(product)[:80],
                "bag_id": live.get("workflow_bag_id"),
                "occupancy_started_at_ms": live.get("occupancy_started_at"),
                "output_today": out_today,
                "sparkline": spark,
            }
        )

    sorted_by_out = sorted(machines, key=lambda m: m["output_today"], reverse=True)
    best_name = sorted_by_out[0]["display_name"] if sorted_by_out and sorted_by_out[0]["output_today"] > 0 else None
    worst_name = None
    if len(machines) > 1:
        m_lo = min(machines, key=lambda m: m["output_today"])
        worst_name = m_lo["display_name"]

    top_ids = [m["id"] for m in sorted_by_out[:3] if m["output_today"] > 0]
    if not top_ids:
        top_ids = [m["id"] for m in machines[:3]]

    chart_station_series: dict[str, list[float]] = {}
    labels_h = [f"{h:02d}" for h in range(24)]
    for sid in top_ids:
        chart_station_series[str(sid)] = [round(x, 1) for x in station_hourly.get(sid, [0.0] * 24)]

    bar_by_station = [
        {"id": m["id"], "name": m["display_name"][:24], "output": m["output_today"]}
        for m in sorted(machines, key=lambda x: x["output_today"], reverse=True)
    ]
    max_out = max((b["output"] for b in bar_by_station), default=1) or 1
    idle_pct_by_station = []
    for m in machines:
        if m["status"] == "running":
            pct = 5.0
        elif m["status"] == "paused":
            pct = 35.0
        else:
            pct = 92.0
        idle_pct_by_station.append(
            {
                "id": m["id"],
                "name": m["display_name"][:20],
                "pct": pct,
                "load_pct": round(100.0 * (1.0 - pct / 100.0), 0),
            }
        )

    hist_totals = _hist_station_totals_7d(conn, start_ms)
    hours_into_day = max(0.25, (now_ms - start_ms) / 3600000.0)
    hours_7d = 7.0 * 24.0
    for m in machines:
        sid = int(m["id"])
        ht = float(hist_totals.get(sid, 0.0))
        hist_uh = round(ht / hours_7d, 2) if ht > 0 else 0.0
        out_today = int(m["output_today"])
        today_uh = round(out_today / hours_into_day, 2) if out_today else 0.0

        session_uh = None
        cycle_session_min = None
        session_out_val = None
        live_bid = m.get("bag_id")
        st_vis = m.get("status")
        if live_bid and st_vis in ("running", "paused"):
            claim_ms = _latest_bag_claim_ms(conn, int(live_bid), sid)
            if claim_ms is not None:
                session_out_val = _session_tablets_since_claim(conn, int(live_bid), sid, claim_ms)
                elapsed_h = max(1.0 / 60.0, (now_ms - claim_ms) / 3600000.0)
                session_uh = round(float(session_out_val) / elapsed_h, 1)
                cycle_session_min = round((now_ms - claim_ms) / 60000.0, 1)

        has_running_session = session_uh is not None and st_vis == "running"
        compare_uh = session_uh if has_running_session else today_uh
        if hist_uh > 0.01:
            vs_pct = round(100.0 * (compare_uh - hist_uh) / hist_uh, 1)
        else:
            vs_pct = 0.0

        if hist_uh <= 0.01:
            tier = "inline"
            perf_hint = "No 7d baseline"
        elif vs_pct >= 5.0:
            tier = "above"
            perf_hint = f"↑ {vs_pct:.0f}% vs 7d avg"
        elif vs_pct <= -10.0:
            tier = "below"
            perf_hint = f"↓ {abs(vs_pct):.0f}% vs 7d avg"
        else:
            tier = "inline"
            perf_hint = "Near 7d avg"

        m["rate_hist_uh"] = hist_uh
        m["rate_today_uh"] = today_uh
        m["rate_session_uh"] = session_uh
        m["session_out_tablets"] = (
            round(float(session_out_val), 1) if session_out_val is not None else None
        )
        m["cycle_session_min"] = cycle_session_min
        m["vs_hist_pct"] = vs_pct
        m["perf_tier"] = tier
        m["perf_hint"] = perf_hint

    flow_intel: dict = {}
    try:
        flow_intel = compute_production_flow_intel(conn, now_ms, stations, station_live)
    except Exception:
        flow_intel = {}

    flavor_breakdown: list[dict] = []
    try:
        for r in conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(pd.product_name), ''), 'Unknown') AS pname,
                   COALESCE(SUM(CAST(json_extract(we.payload, '$.count_total') AS REAL)), 0) AS v
            FROM workflow_events we
            JOIN workflow_bags wb ON wb.id = we.workflow_bag_id
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE we.occurred_at >= ? AND we.occurred_at < ?
              AND we.event_type IN ('BLISTER_COMPLETE', 'SEALING_COMPLETE')
              AND json_extract(we.payload, '$.count_total') IS NOT NULL
            GROUP BY pname
            ORDER BY v DESC
            LIMIT 8
            """,
            (start_ms, end_ms),
        ).fetchall():
            v = float(r["v"] or 0)
            if v > 0:
                flavor_breakdown.append({"label": str(r["pname"])[:32], "value": int(round(v))})
    except sqlite3.OperationalError:
        pass

    activity: list[dict] = []

    def _push_act(at_ms: int, message: str, severity: str) -> None:
        activity.append({"at_ms": at_ms, "message": message, "severity": severity})

    for st in stations:
        sid = int(st["id"])
        live = station_live.get(sid) or {}
        if live.get("status") == "paused" and live.get("occupancy_started_at"):
            el = now_ms - int(live["occupancy_started_at"])
            if el > 30 * 60 * 1000:
                lbl = str(st.get("label") or f"Station {sid}")
                _push_act(
                    now_ms,
                    f"{lbl}: paused {int(el // 60000)} min — check floor",
                    "alert",
                )

    try:
        ev_rows = conn.execute(
            """
            SELECT event_type, occurred_at, workflow_bag_id, station_id, payload
            FROM workflow_events
            ORDER BY occurred_at DESC, id DESC
            LIMIT 18
            """
        ).fetchall()
    except sqlite3.OperationalError:
        ev_rows = []

    et_labels = {
        "BAG_CLAIMED": "Bag claimed",
        "STATION_RESUMED": "Station resumed",
        "BLISTER_COMPLETE": "Blister count saved",
        "SEALING_COMPLETE": "Sealing count saved",
        "PACKAGING_SNAPSHOT": "Packaging snapshot",
        "BAG_FINALIZED": "Bag finalized",
        "CARD_ASSIGNED": "Card assigned",
        "CARD_FORCE_RELEASED": "Card released",
    }
    for r in ev_rows:
        et = str(r["event_type"])
        sid = r["station_id"]
        at = int(r["occurred_at"] or 0)
        base = et_labels.get(et, et.replace("_", " ").title())
        where = f" · st {sid}" if sid else ""
        msg = f"{base}{where}"
        sev = "warn" if et == "CARD_FORCE_RELEASED" else "info"
        _push_act(at, msg, sev)

    _sev_rank = {"alert": 0, "warn": 1, "info": 2}

    kpis_out = {
        "active_machines": occupied,
        "idle_machines": idle,
        "paused_machines": paused,
        "down_machines": 0,
        "total_output_today": int(round(total_out)),
        "throughput_pct": round(throughput_pct, 1),
        "avg_cycle_time_min": avg_cycle,
    }
    targets_out = {"daily_output_tablets": daily_target}
    smart_acts = _ops_smart_alerts(now_ms, kpis_out, targets_out, machines, flow_intel)
    activity = smart_acts + activity
    activity.sort(
        key=lambda x: (
            _sev_rank.get(x.get("severity"), 2),
            -int(x.get("at_ms") or 0),
        )
    )
    activity = activity[:48]

    chart_target_cumulative = [round(float(daily_target) * (h + 1) / 24.0, 0) for h in range(24)]

    return {
        "generated_at_ms": now_ms,
        "date_label": date_label,
        "hour_labels": labels_h,
        "chart_target_cumulative": chart_target_cumulative,
        "flow": flow_intel,
        "targets": targets_out,
        "kpis": kpis_out,
        "highlights": {"best_station": best_name, "lowest_output_station": worst_name},
        "machines": machines,
        "activity": activity,
        "chart_hourly_output": [round(x, 1) for x in hourly],
        "chart_cumulative_output": cumulative_hourly,
        "chart_station_series": chart_station_series,
        "chart_station_names": {str(m["id"]): m["display_name"] for m in machines},
        "bar_by_station": bar_by_station,
        "idle_pct_by_station": idle_pct_by_station,
        "flavor_breakdown": flavor_breakdown,
        "max_bar_output": max_out,
    }


def _normalize_station_kind(raw) -> str:
    k = (raw or "").strip().lower()
    if k in _VALID_STATION_KINDS:
        return k
    return "sealing"


def _station_scan_token_prefix(station_kind: str) -> str:
    """URL token prefix for workflow station scan tokens (matches station type)."""
    k = _normalize_station_kind(station_kind)
    return {
        "sealing": "seal-",
        "blister": "blister-",
        "packaging": "packaging-",
        "combined": "combined-",
    }.get(k, "seal-")


def _validate_station_scan_token_for_kind(station_kind: str, token: str) -> bool:
    if not _STATION_SCAN_TOKEN_RE.match(token):
        return False
    return token.startswith(_station_scan_token_prefix(station_kind))


def _validate_bag_card_scan_token(token: str) -> bool:
    """Manual bag card tokens: URL/path safe (same charset as station tokens); any prefix is allowed."""
    return bool(_STATION_SCAN_TOKEN_RE.match(token))


# Shown when manual scan_token fails validation (missing bag- is not an error — only charset/length).
_BAG_CARD_SCAN_TOKEN_INVALID_FLASH = (
    "Scan token is not valid: use only letters, numbers, periods (.), underscores (_), and hyphens (-), "
    "1–128 characters. Spaces and other special characters are not allowed. "
    "Leave the scan token blank to auto-generate a token with a bag- prefix."
)


def _normalize_bag_scan_token_input(raw: str) -> str:
    """Strip, drop invisible format chars, map unicode dashes to ASCII (copy-paste from docs)."""
    s = (raw or "").strip()
    if not s:
        return ""
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    for u in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "\uff0d"):
        s = s.replace(u, "-")
    return s.strip()


def _allocate_unique_card_scan_token(conn: sqlite3.Connection) -> str:
    for _ in range(40):
        t = "bag-" + secrets.token_hex(8)
        if not conn.execute(
            "SELECT 1 FROM qr_cards WHERE scan_token = ?", (t,)
        ).fetchone():
            return t
    raise RuntimeError("could_not_allocate_card_token")


def _allocate_unique_station_scan_token(conn: sqlite3.Connection, station_kind: str) -> str:
    prefix = _station_scan_token_prefix(station_kind)
    for _ in range(40):
        t = prefix + secrets.token_hex(8)
        if not conn.execute(
            "SELECT 1 FROM workflow_stations WHERE station_scan_token = ?", (t,)
        ).fetchone():
            return t
    raise RuntimeError("could_not_allocate_station_token")


def _machine_allowed_for_station_kind(
    conn: sqlite3.Connection, station_kind: str, machine_id: int | None
) -> bool:
    """Validate ``machine_id`` for a workflow station role (production machines table)."""
    if machine_id is None:
        return True
    row = conn.execute(
        """
        SELECT machine_role FROM machines
        WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (machine_id,),
    ).fetchone()
    if not row:
        return False
    role = (row["machine_role"] or "sealing").strip().lower()
    if station_kind == "sealing":
        return role == "sealing"
    if station_kind == "blister":
        return role == "blister"
    if station_kind == "packaging":
        return True
    if station_kind == "combined":
        return role in ("sealing", "blister")
    return False

@bp.route('/admin')
def admin_panel():
    """Admin panel with quick actions and product management"""
    # Check for admin session
    if not session.get('admin_authenticated'):
        return render_template('admin_login.html')

    try:
        ensure_app_settings_table()  # Ensure table exists
        with db_read_only() as conn:
            # Get current settings
            cards_per_turn = conn.execute(
                'SELECT setting_value FROM app_settings WHERE setting_key = ?',
                ('cards_per_turn',)
            ).fetchone()
            cards_per_turn_value = int(cards_per_turn['setting_value']) if cards_per_turn else 1
            return render_template('admin_panel.html', cards_per_turn=cards_per_turn_value)
    except Exception:
        import traceback
        traceback.print_exc()
        return render_template('admin_panel.html', cards_per_turn=1)



@bp.route('/admin/login', methods=['POST'])
def admin_login():
    """Handle admin login with enhanced security"""
    password = request.form.get('password') or request.json.get('password')

    # Get admin password from environment variable with secure default
    admin_password = Config.ADMIN_PASSWORD

    if password == admin_password:
        session['admin_authenticated'] = True
        session['employee_role'] = 'admin'  # Set admin role for navigation
        session['login_time'] = datetime.now().isoformat()
        session.permanent = True  # Make session permanent
        # Note: session lifetime is set in app factory

        return redirect(url_for('admin.admin_panel')) if request.form else jsonify({'success': True})
    else:
        # Log failed login attempt
        current_app.logger.warning(f"Failed admin login attempt from {request.remote_addr} at {datetime.now()}")

        if request.form:
            flash('Invalid password', 'error')
            return render_template('admin_login.html')
        else:
            return jsonify({'success': False, 'error': 'Invalid password'})



@bp.route('/admin/logout')
def admin_logout():
    """Logout admin - redirect to unified logout"""
    return redirect(url_for('auth.logout'))



@bp.route('/admin/products')
@admin_required
def product_mapping():
    """Redirect to unified product configuration page"""
    return redirect(url_for('admin.product_config'))


@bp.route('/admin/tablet_types')
@admin_required
def tablet_types_config():
    """Redirect to unified product configuration page"""
    return redirect(url_for('admin.product_config'))


@bp.route('/admin/config')
@admin_required
def product_config():
    """Unified product & tablet type configuration page"""
    try:
        with db_transaction() as conn:
            # Get all products with their tablet type and calculation details
            products = conn.execute('''
                SELECT pd.*, tt.tablet_type_name, tt.inventory_item_id,
                       COALESCE(NULLIF(TRIM(pd.category), ''), tt.category) as category,
                       (SELECT GROUP_CONCAT(pat.tablet_type_id)
                        FROM product_allowed_tablet_types pat
                        WHERE pat.product_details_id = pd.id) AS allowed_tablet_type_ids_csv
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                ORDER BY COALESCE(NULLIF(TRIM(pd.category), ''), tt.category, 'ZZZ'), pd.product_name
            ''').fetchall()

            # Check if category column exists and add it if missing
            table_info = conn.execute("PRAGMA table_info(tablet_types)").fetchall()
            has_category_column = any(col[1] == 'category' for col in table_info)

            if not has_category_column:
                try:
                    conn.execute('ALTER TABLE tablet_types ADD COLUMN category TEXT')
                    conn.commit()
                    has_category_column = True
                except Exception as e:
                    current_app.logger.warning(f"Warning: Could not add category column: {e}")

            # Get all tablet types
            tablet_types_rows = conn.execute('''
                SELECT * FROM tablet_types
                ORDER BY COALESCE(category, 'ZZZ'), tablet_type_name
            ''').fetchall()
            tablet_types = [dict(row) for row in tablet_types_rows]

            # Get unique categories from tablet_types (in use)
            categories = conn.execute('''
                SELECT DISTINCT category FROM tablet_types
                WHERE category IS NOT NULL AND category != ""
                ORDER BY category
            ''').fetchall()
            category_list = [cat['category'] for cat in categories] if categories else []
            category_set = set(category_list)

            # Product-only categories: ``product_details.category`` overrides tablet type for display,
            # but those names were invisible if no tablet type (and no created_categories row) used them.
            try:
                pd_cat_rows = conn.execute(
                    """
                    SELECT DISTINCT TRIM(pd.category) AS c
                    FROM product_details pd
                    WHERE pd.category IS NOT NULL AND TRIM(pd.category) != ""
                    """
                ).fetchall()
                for row in pd_cat_rows:
                    c = row["c"] if isinstance(row, dict) else row[0]
                    if c and c not in category_set:
                        category_list.append(c)
                        category_set.add(c)
            except Exception as e:
                current_app.logger.warning("Warning: Could not load product_details categories: %s", e)

            # Get created categories from app_settings (may not be in use yet)
            try:
                created_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'created_categories'
                ''').fetchone()
                if created_categories_json and created_categories_json['setting_value']:
                    created_categories = json.loads(created_categories_json['setting_value'])
                    # Add to category list (union)
                    for cat in created_categories:
                        if cat and cat not in category_set:
                            category_list.append(cat)
                            category_set.add(cat)
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load created categories: {e}")

            # Get deleted categories from app_settings
            deleted_categories_set = set()
            try:
                deleted_categories_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'deleted_categories'
                ''').fetchone()
                if deleted_categories_json and deleted_categories_json['setting_value']:
                    deleted_categories_set = set(json.loads(deleted_categories_json['setting_value']))
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load deleted categories: {e}")

            # Get category order from app_settings
            try:
                category_order_json = conn.execute('''
                    SELECT setting_value FROM app_settings WHERE setting_key = 'category_order'
                ''').fetchone()
                if category_order_json and category_order_json['setting_value']:
                    preferred_order = json.loads(category_order_json['setting_value'])
                else:
                    preferred_order = sorted(category_list)
            except Exception as e:
                current_app.logger.warning(f"Warning: Could not load category order: {e}")
                preferred_order = sorted(category_list)

            # Filter out deleted categories
            all_categories = [cat for cat in category_list if cat not in deleted_categories_set]
            all_categories.sort(key=lambda x: (preferred_order.index(x) if x in preferred_order else len(preferred_order) + 1, x))

            # Find tablet types that don't have product configurations yet
            product_tablet_type_ids = set(p['tablet_type_id'] for p in products if p['tablet_type_id'])
            tablet_types_without_products = [tt for tt in tablet_types if tt['id'] not in product_tablet_type_ids]

            return render_template('product_config.html',
                                   products=products,
                                   tablet_types=tablet_types,
                                   categories=all_categories,
                                   tablet_types_without_products=tablet_types_without_products)
    except Exception as e:
        current_app.logger.error(f"Error loading product config: {str(e)}")
        flash(f'Error loading configuration: {str(e)}', 'error')
        return render_template('product_config.html', products=[], tablet_types=[], categories=[], tablet_types_without_products=[])



@bp.route('/admin/fix-bags')
@admin_required
def fix_bags_page():
    """Page to fix bag assignments"""
    return render_template('fix_bags.html')


@bp.route('/admin/employees')
@admin_required
def manage_employees():
    """Employee management page"""
    try:
        with db_read_only() as conn:
            employees = conn.execute('''
                SELECT id, username, full_name, role, is_active, created_at
                FROM employees
                ORDER BY role, full_name
            ''').fetchall()

            return render_template('employee_management.html', employees=employees)
    except Exception as e:
        current_app.logger.error(f"Error in manage_employees: {e}")
        traceback.print_exc()
        flash('An error occurred while loading employees', 'error')
        return render_template('employee_management.html', employees=[])


@bp.route("/admin/workflow-qr")
@bp.route("/command-center")
@admin_required
def workflow_qr_management():
    """Command Center: monitor workflow stations/cards and manage QR settings."""
    try:
        with db_read_only() as conn:
            stations = []
            cards = []
            station_live = {}
            sealing_machines = []
            try:
                stations = conn.execute(
                    """
                    SELECT ws.id, ws.label, ws.station_scan_token, ws.station_code, ws.machine_id,
                           m.machine_name AS machine_name,
                           COALESCE(ws.station_kind, 'sealing') AS station_kind
                    FROM workflow_stations ws
                    LEFT JOIN machines m ON m.id = ws.machine_id
                    ORDER BY ws.station_kind, ws.id
                    """
                ).fetchall()
                stations = [dict(r) for r in stations]
            except sqlite3.OperationalError:
                try:
                    stations = conn.execute(
                        """
                        SELECT id, label, station_scan_token, station_code, NULL AS machine_id,
                               NULL AS machine_name, 'sealing' AS station_kind
                        FROM workflow_stations
                        ORDER BY id
                        """
                    ).fetchall()
                    stations = [dict(r) for r in stations]
                except sqlite3.OperationalError:
                    pass
            try:
                sealing_machines = conn.execute(
                    """
                    SELECT id, machine_name
                    FROM machines
                    WHERE COALESCE(is_active, 1) = 1 AND machine_role = 'sealing'
                    ORDER BY machine_name
                    """
                ).fetchall()
                sealing_machines = [dict(r) for r in sealing_machines]
            except sqlite3.OperationalError:
                pass
            blister_machines = []
            try:
                blister_machines = conn.execute(
                    """
                    SELECT id, machine_name
                    FROM machines
                    WHERE COALESCE(is_active, 1) = 1 AND machine_role = 'blister'
                    ORDER BY machine_name
                    """
                ).fetchall()
                blister_machines = [dict(r) for r in blister_machines]
            except sqlite3.OperationalError:
                pass
            all_machines = []
            try:
                all_machines = conn.execute(
                    """
                    SELECT id, machine_name, machine_role
                    FROM machines
                    WHERE COALESCE(is_active, 1) = 1
                    ORDER BY machine_name
                    """
                ).fetchall()
                all_machines = [dict(r) for r in all_machines]
            except sqlite3.OperationalError:
                pass
            try:
                cards = conn.execute(
                    """
                    SELECT qc.id, qc.label, qc.scan_token, qc.status, qc.assigned_workflow_bag_id,
                           wb.inventory_bag_id
                    FROM qr_cards qc
                    LEFT JOIN workflow_bags wb ON wb.id = qc.assigned_workflow_bag_id
                    ORDER BY qc.id
                    """
                ).fetchall()
                cards = [dict(r) for r in cards]
            except sqlite3.OperationalError:
                # Older DBs may lack workflow_bags.inventory_bag_id; still list cards.
                try:
                    cards = conn.execute(
                        """
                        SELECT qc.id, qc.label, qc.scan_token, qc.status, qc.assigned_workflow_bag_id,
                               NULL AS inventory_bag_id
                        FROM qr_cards qc
                        ORDER BY qc.id
                        """
                    ).fetchall()
                    cards = [dict(r) for r in cards]
                except sqlite3.OperationalError:
                    pass
            for c in cards:
                c["bag_name"] = _workflow_inventory_bag_name(conn, c.get("inventory_bag_id"))
                c["status_display"] = c.get("status") or "idle"
                c["current_station_label"] = None
            for st in stations:
                sid = int(st["id"])
                station_live[sid] = {
                    "status": "idle",
                    "workflow_bag_id": None,
                    "card_token": None,
                    "occupancy_started_at": None,
                    "product_name": None,
                    "receipt_number": None,
                    "bag_name": None,
                }
            # Match floor API: latest BAG_CLAIMED/STATION_RESUMED *at this station*, not the bag's latest claim globally.
            for st in stations:
                sid = int(st["id"])
                occ = _current_station_occupancy(conn, sid)
                if not occ:
                    continue
                wid = int(occ["workflow_bag_id"])
                bag_row = conn.execute(
                    """
                    SELECT wb.id, wb.receipt_number, wb.product_id, pd.product_name, wb.inventory_bag_id
                    FROM workflow_bags wb
                    LEFT JOIN product_details pd ON pd.id = wb.product_id
                    WHERE wb.id = ?
                    """,
                    (wid,),
                ).fetchone()
                bd = dict(bag_row) if bag_row else {}
                station_live[sid] = {
                    "status": occ["status"],
                    "workflow_bag_id": wid,
                    "card_token": occ.get("card_token"),
                    "occupancy_started_at": occ.get("occupancy_started_at_ms"),
                    "product_name": bd.get("product_name"),
                    "flavor": bd.get("product_name"),
                    "receipt_number": bd.get("receipt_number"),
                    "bag_name": _workflow_inventory_bag_name(conn, bd.get("inventory_bag_id")),
                }
            bag_station_for_card_label = {}
            for st in stations:
                sid = int(st["id"])
                live = station_live.get(sid) or {}
                wb = live.get("workflow_bag_id")
                if wb:
                    bag_station_for_card_label[int(wb)] = sid
            for c in cards:
                bag_id = c.get("assigned_workflow_bag_id")
                if not bag_id:
                    continue
                sid = bag_station_for_card_label.get(int(bag_id))
                if sid is None:
                    continue
                live = station_live.get(sid) or {}
                station_label = next(
                    (str(s.get("label")) for s in stations if int(s.get("id") or 0) == sid),
                    f"Station {sid}",
                )
                c["current_station_label"] = station_label
                ost = live.get("status") or "idle"
                if ost == "paused":
                    c["status_display"] = f"{station_label} · paused"
                else:
                    c["status_display"] = station_label
        stations_by_kind = {k: [] for k in _STATION_KIND_ORDER}
        for s in stations:
            k = _normalize_station_kind(s.get("station_kind"))
            stations_by_kind.setdefault(k, []).append(s)
        bag_assign = None
        try:
            wf_products = _load_workflow_products(conn)
            bag_assign = {
                "products": wf_products,
                "ambiguous_matches": None,
                "form_product_id": None,
                "form_box_number": None,
                "form_bag_number": None,
                "form_card_scan_token": None,
                "form_receipt_number": None,
                "form_hand_packed": False,
                "return_to": ASSIGN_BAG_RETURN_COMMAND_CENTER,
                "restart_url": url_for("admin.workflow_qr_management"),
            }
        except Exception:
            bag_assign = None
        floor_station_day_stats: dict[int, dict] = {}
        floor_ops_date_label = ""
        try:
            start_ms, end_ms, floor_ops_date_label = _ny_today_bounds_ms()
            floor_station_day_stats = _floor_station_day_stats(conn, start_ms, end_ms)
        except Exception:
            floor_station_day_stats = {}
            floor_ops_date_label = ""
        floor_ops_overview = _floor_ops_overview(
            stations, station_live, floor_station_day_stats, cards
        )
        return render_template(
            "admin_workflow_qr.html",
            stations=stations,
            stations_by_kind=stations_by_kind,
            sealing_machines=sealing_machines,
            blister_machines=blister_machines,
            all_machines=all_machines,
            station_kind_options=_STATION_KIND_ORDER,
            cards=cards,
            station_live=station_live,
            floor_station_day_stats=floor_station_day_stats,
            floor_ops_date_label=floor_ops_date_label,
            floor_ops_overview=floor_ops_overview,
            bag_assign=bag_assign,
        )
    except Exception as e:
        current_app.logger.error("workflow_qr_management: %s", e)
        traceback.print_exc()
        flash("Could not load workflow QR data.", "error")
        empty_k = {k: [] for k in _STATION_KIND_ORDER}
        return render_template(
            "admin_workflow_qr.html",
            stations=[],
            stations_by_kind=empty_k,
            sealing_machines=[],
            blister_machines=[],
            all_machines=[],
            station_kind_options=_STATION_KIND_ORDER,
            cards=[],
            station_live={},
            floor_station_day_stats={},
            floor_ops_date_label="",
            floor_ops_overview=_floor_ops_overview([], {}, {}, []),
            bag_assign=None,
        )


@bp.route("/command-center/ops-tv")
@admin_required
def ops_tv_dashboard():
    """Full-screen TV operations board (no data tables; wall display)."""
    ver = read_version_constants().get("__version__", "1")
    return render_template(
        "ops_tv_dashboard.html",
        snapshot_api_url=url_for("admin.ops_tv_snapshot_api"),
        command_center_url=url_for("admin.workflow_qr_management"),
        app_version=ver,
    )


@bp.route("/command-center/ops-tv/api/snapshot")
@admin_required
def ops_tv_snapshot_api():
    try:
        with db_read_only() as conn:
            payload = build_ops_tv_snapshot(conn)
        return jsonify(payload)
    except Exception as e:
        current_app.logger.exception("ops_tv_snapshot_api")
        return jsonify({"error": str(e)}), 500


@bp.route("/admin/workflow-qr/release", methods=["POST"])
@admin_required
def workflow_qr_release_card():
    """Undo card assignment (same policy as staff force-release)."""
    workflow_bag_id = request.form.get("workflow_bag_id", type=int)
    qr_card_id = request.form.get("qr_card_id", type=int)
    reason = (request.form.get("reason") or "admin_panel_release").strip()
    uid = session.get("employee_id")
    if session.get("admin_authenticated"):
        uid = None
    if not workflow_bag_id or not qr_card_id:
        flash("workflow_bag_id and qr_card_id are required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    conn = get_db()
    try:

        def _run():
            return force_release_card(
                conn,
                workflow_bag_id=workflow_bag_id,
                qr_card_id=qr_card_id,
                reason=reason,
                user_id=uid,
            )

        try:
            st, body = run_with_busy_retry(_run, op_name="admin_force_release")
        except sqlite3.OperationalError:
            flash("Database busy; retry.", "error")
            return redirect(url_for("admin.workflow_qr_management"))

        if st == "reject":
            flash(body.get("code", "release rejected"), "error")
        elif st == "duplicate":
            flash("Card was already idle (no change).", "info")
        else:
            conn.commit()
            flash(f"Released QR card #{qr_card_id} from workflow bag #{workflow_bag_id}.", "success")
    finally:
        conn.close()
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/add-card", methods=["POST"])
@admin_required
def workflow_qr_add_card():
    """Insert an idle row in qr_cards (physical bag QR inventory)."""
    label = (request.form.get("label") or "").strip() or None
    if label and len(label) > 128:
        flash("Label must be 128 characters or less.", "error")
        return redirect(url_for("admin.workflow_qr_management"))
    token_in = _normalize_bag_scan_token_input(request.form.get("scan_token") or "")
    if token_in:
        if len(token_in) > 128:
            flash("Scan token is too long (maximum 128 characters).", "error")
            return redirect(url_for("admin.workflow_qr_management"))
        if not _validate_bag_card_scan_token(token_in):
            flash(_BAG_CARD_SCAN_TOKEN_INVALID_FLASH, "error")
            return redirect(url_for("admin.workflow_qr_management"))
        scan_token = token_in
    else:
        scan_token = None

    try:
        with db_transaction() as conn:
            if scan_token is None:
                scan_token = _allocate_unique_card_scan_token(conn)
            else:
                dup = conn.execute(
                    "SELECT id FROM qr_cards WHERE scan_token = ?",
                    (scan_token,),
                ).fetchone()
                if dup:
                    flash("That scan token is already used by another card.", "error")
                    return redirect(url_for("admin.workflow_qr_management"))
            conn.execute(
                """
                INSERT INTO qr_cards (label, scan_token, status)
                VALUES (?, ?, ?)
                """,
                (label, scan_token, WC.QR_CARD_STATUS_IDLE),
            )
        flash(
            f"Bag QR card added. Scan token: {scan_token} — use as card_token on the floor.",
            "success",
        )
    except sqlite3.IntegrityError:
        flash("Could not add card (duplicate scan token).", "error")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_add_card: %s", oe)
        flash("Could not add card (database error). Is the workflow migration applied?", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_add_card: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/remove-card", methods=["POST"])
@admin_required
def workflow_qr_remove_card():
    """Delete a qr_cards row only when idle and not linked to a workflow bag."""
    qr_card_id = request.form.get("qr_card_id", type=int)
    if not qr_card_id:
        flash("qr_card_id is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    try:
        with db_transaction() as conn:
            row = conn.execute(
                """
                SELECT id, status, assigned_workflow_bag_id
                FROM qr_cards WHERE id = ?
                """,
                (qr_card_id,),
            ).fetchone()
            if not row:
                flash("Unknown QR card.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            r = dict(row)
            if r.get("status") != WC.QR_CARD_STATUS_IDLE or r.get("assigned_workflow_bag_id") is not None:
                flash(
                    "Only idle cards with no assigned bag can be removed. Release the card first if it is in use.",
                    "error",
                )
                return redirect(url_for("admin.workflow_qr_management"))
            conn.execute("DELETE FROM qr_cards WHERE id = ?", (qr_card_id,))
        flash(f"Removed bag QR card #{qr_card_id}.", "success")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_remove_card: %s", oe)
        flash("Could not remove card (database error).", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_remove_card: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/edit-station-token", methods=["POST"])
@admin_required
def workflow_qr_edit_station_scan_token():
    """Update workflow_stations.station_scan_token (floor URL path)."""
    station_id = request.form.get("station_id", type=int)
    new_scan = (request.form.get("station_scan_token") or "").strip()
    if not station_id:
        flash("station_id is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))
    if not new_scan:
        flash("Scan token is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    try:
        with db_transaction() as conn:
            try:
                row = conn.execute(
                    """
                    SELECT id, station_scan_token, COALESCE(station_kind, 'sealing') AS station_kind
                    FROM workflow_stations WHERE id = ?
                    """,
                    (station_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    """
                    SELECT id, station_scan_token, 'sealing' AS station_kind
                    FROM workflow_stations WHERE id = ?
                    """,
                    (station_id,),
                ).fetchone()
            if not row:
                flash("Unknown workflow station.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            r = dict(row)
            sk = _normalize_station_kind(r.get("station_kind"))
            if new_scan == r["station_scan_token"]:
                flash("No change to scan token.", "info")
                return redirect(url_for("admin.workflow_qr_management"))
            if not _validate_station_scan_token_for_kind(sk, new_scan):
                pfx = _station_scan_token_prefix(sk)
                flash(
                    f"Scan token must start with {pfx} for this station type, and use only letters, numbers, dot, underscore, and hyphen (1–128 chars).",
                    "error",
                )
                return redirect(url_for("admin.workflow_qr_management"))
            dup = conn.execute(
                "SELECT id FROM workflow_stations WHERE station_scan_token = ? AND id != ?",
                (new_scan, station_id),
            ).fetchone()
            if dup:
                flash("That scan token is already used by another station.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            conn.execute(
                "UPDATE workflow_stations SET station_scan_token = ? WHERE id = ?",
                (new_scan, station_id),
            )
        flash(f"Station #{station_id} scan token updated.", "success")
    except sqlite3.IntegrityError:
        flash("That scan token is already in use.", "error")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_edit_station_scan_token: %s", oe)
        flash("Could not update scan token (database error).", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_edit_station_scan_token: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/edit-card-token", methods=["POST"])
@admin_required
def workflow_qr_edit_card_scan_token():
    """Update qr_cards.scan_token (bag QR value)."""
    qr_card_id = request.form.get("qr_card_id", type=int)
    new_scan = _normalize_bag_scan_token_input(request.form.get("scan_token") or "")
    if not qr_card_id:
        flash("qr_card_id is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))
    if not new_scan:
        flash("Scan token is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    if len(new_scan) > 128:
        flash("Scan token is too long (maximum 128 characters).", "error")
        return redirect(url_for("admin.workflow_qr_management"))
    if not _validate_bag_card_scan_token(new_scan):
        flash(_BAG_CARD_SCAN_TOKEN_INVALID_FLASH, "error")
        return redirect(url_for("admin.workflow_qr_management"))

    try:
        with db_transaction() as conn:
            row = conn.execute(
                "SELECT id, scan_token FROM qr_cards WHERE id = ?",
                (qr_card_id,),
            ).fetchone()
            if not row:
                flash("Unknown QR card.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            r = dict(row)
            if new_scan == r["scan_token"]:
                flash("No change to scan token.", "info")
                return redirect(url_for("admin.workflow_qr_management"))
            dup = conn.execute(
                "SELECT id FROM qr_cards WHERE scan_token = ? AND id != ?",
                (new_scan, qr_card_id),
            ).fetchone()
            if dup:
                flash("That scan token is already used by another card.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            conn.execute(
                "UPDATE qr_cards SET scan_token = ? WHERE id = ?",
                (new_scan, qr_card_id),
            )
        flash(f"Bag QR card #{qr_card_id} scan token updated.", "success")
    except sqlite3.IntegrityError:
        flash("That scan token is already in use.", "error")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_edit_card_scan_token: %s", oe)
        flash("Could not update scan token (database error).", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_edit_card_scan_token: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/station-machine", methods=["POST"])
@admin_required
def workflow_qr_map_station_machine():
    """Link a workflow sealing station to a production machine (machine count form)."""
    station_id = request.form.get("station_id", type=int)
    raw_mid = request.form.get("machine_id")
    machine_id = None
    if raw_mid is not None and str(raw_mid).strip() != "":
        machine_id = int(str(raw_mid).strip())
    if not station_id:
        flash("station_id is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    sk = "sealing"
    try:
        with db_transaction() as conn:
            try:
                st = conn.execute(
                    """
                    SELECT id, COALESCE(station_kind, 'sealing') AS station_kind
                    FROM workflow_stations WHERE id = ?
                    """,
                    (station_id,),
                ).fetchone()
                if st:
                    sk = _normalize_station_kind(dict(st).get("station_kind"))
            except sqlite3.OperationalError:
                st = conn.execute(
                    "SELECT id FROM workflow_stations WHERE id = ?", (station_id,)
                ).fetchone()
            if not st:
                flash("Unknown workflow station.", "error")
                return redirect(url_for("admin.workflow_qr_management"))
            if not _machine_allowed_for_station_kind(conn, sk, machine_id):
                flash(
                    "That machine does not match this station type (sealing vs blister vs packaging).",
                    "error",
                )
                return redirect(url_for("admin.workflow_qr_management"))
            conn.execute(
                "UPDATE workflow_stations SET machine_id = ? WHERE id = ?",
                (machine_id, station_id),
            )
        flash("Station ↔ machine mapping saved.", "success")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_map_station_machine: %s", oe)
        flash("Could not update mapping (database error).", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_map_station_machine: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))


@bp.route("/admin/workflow-qr/station", methods=["POST"])
@admin_required
def workflow_qr_add_station():
    """Create a workflow floor station row (QR URL + optional machine link)."""
    label = (request.form.get("label") or "").strip()
    station_kind = _normalize_station_kind(request.form.get("station_kind"))
    station_code = (request.form.get("station_code") or "").strip() or None
    if station_code and len(station_code) > 64:
        flash("Station code must be 64 characters or less.", "error")
        return redirect(url_for("admin.workflow_qr_management"))
    token_in = (request.form.get("station_scan_token") or "").strip()
    raw_mid = request.form.get("machine_id")
    machine_id = None
    if raw_mid is not None and str(raw_mid).strip() != "":
        machine_id = int(str(raw_mid).strip())

    if not label:
        flash("Label is required.", "error")
        return redirect(url_for("admin.workflow_qr_management"))

    if token_in:
        if not _validate_station_scan_token_for_kind(station_kind, token_in):
            pfx = _station_scan_token_prefix(station_kind)
            flash(
                f"Scan token must start with {pfx} for this station type, and use only letters, numbers, dot, underscore, and hyphen (1–128 chars).",
                "error",
            )
            return redirect(url_for("admin.workflow_qr_management"))
        scan_token = token_in
    else:
        scan_token = None

    try:
        with db_transaction() as conn:
            if scan_token is None:
                scan_token = _allocate_unique_station_scan_token(conn, station_kind)
            else:
                dup = conn.execute(
                    "SELECT id FROM workflow_stations WHERE station_scan_token = ?",
                    (scan_token,),
                ).fetchone()
                if dup:
                    flash("That scan token is already used by another station.", "error")
                    return redirect(url_for("admin.workflow_qr_management"))

            if machine_id is not None and not _machine_allowed_for_station_kind(
                conn, station_kind, machine_id
            ):
                flash("Invalid machine for this station type.", "error")
                return redirect(url_for("admin.workflow_qr_management"))

            try:
                conn.execute(
                    """
                    INSERT INTO workflow_stations (station_scan_token, label, station_code, machine_id, station_kind)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (scan_token, label, station_code, machine_id, station_kind),
                )
            except sqlite3.OperationalError:
                try:
                    conn.execute(
                        """
                        INSERT INTO workflow_stations (station_scan_token, label, station_code, machine_id)
                        VALUES (?, ?, ?, ?)
                        """,
                        (scan_token, label, station_code, machine_id),
                    )
                except sqlite3.OperationalError:
                    conn.execute(
                        """
                        INSERT INTO workflow_stations (station_scan_token, label, station_code)
                        VALUES (?, ?, ?)
                        """,
                        (scan_token, label, station_code),
                    )
        flash(
            f"Workflow station added ({station_kind}). Scan token: {scan_token} — use in QR: /workflow/station/{scan_token}",
            "success",
        )
    except sqlite3.IntegrityError:
        flash("Could not add station (duplicate scan token).", "error")
    except sqlite3.OperationalError as oe:
        current_app.logger.error("workflow_qr_add_station: %s", oe)
        flash("Could not add station (database error). Is the workflow migration applied?", "error")
    except Exception as e:
        current_app.logger.error("workflow_qr_add_station: %s", e)
        flash(str(e), "error")
    return redirect(url_for("admin.workflow_qr_management"))

