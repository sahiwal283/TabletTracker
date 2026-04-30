"""Read-only queries and mechanical facts for workflow_events (no policy / no rule booleans)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services import workflow_constants as WC

_NY = ZoneInfo("America/New_York")


def production_day_for_event_ms(occurred_at_ms: int) -> date:
    """Factory-local calendar date bucket (America/New_York) for reporting."""
    dt = datetime.fromtimestamp(occurred_at_ms / 1000.0, tz=timezone.utc)
    return dt.astimezone(_NY).date()


def _parse_row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return json.loads(row["payload"])


def load_events_for_bag(conn: sqlite3.Connection, workflow_bag_id: int) -> list[dict[str, Any]]:
    """All events for a bag in lexicographic order (occurred_at, id)."""
    rows = conn.execute(
        """
        SELECT id, event_type, payload, occurred_at, workflow_bag_id, station_id, user_id, device_id
        FROM workflow_events
        WHERE workflow_bag_id = ?
        ORDER BY occurred_at ASC, id ASC
        """,
        (workflow_bag_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "payload": json.loads(r["payload"]),
                "occurred_at": r["occurred_at"],
                "workflow_bag_id": r["workflow_bag_id"],
                "station_id": r["station_id"],
                "user_id": r["user_id"],
                "device_id": r["device_id"],
            }
        )
    return out


def latest_event_row_for_bag(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, Any] | None:
    ev = load_events_for_bag(conn, workflow_bag_id)
    return ev[-1] if ev else None


def event_counts_by_type(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in events:
        t = e["event_type"]
        counts[t] = counts.get(t, 0) + 1
    return counts


def latest_event_type_tail(events: list[dict[str, Any]]) -> str | None:
    return events[-1]["event_type"] if events else None


def mechanical_bag_facts(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, Any]:
    """Facts + aggregates only (no is_complete / policy)."""
    events = load_events_for_bag(conn, workflow_bag_id)
    return {
        "workflow_bag_id": workflow_bag_id,
        "event_count": len(events),
        "event_counts_by_type": event_counts_by_type(events),
        "latest_event_type": latest_event_type_tail(events),
        "events": events,
    }


def production_flow_for_bag(conn: sqlite3.Connection, workflow_bag_id: int) -> str:
    """Machine-readable flow derived from product config: ``card`` or ``bottle``."""
    try:
        row = conn.execute(
            """
            SELECT COALESCE(pd.is_bottle_product, 0) AS is_bottle_product,
                   COALESCE(pd.is_variety_pack, 0) AS is_variety_pack
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            WHERE wb.id = ?
            """,
            (int(workflow_bag_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            row = conn.execute(
                """
                SELECT COALESCE(pd.is_bottle_product, 0) AS is_bottle_product,
                       0 AS is_variety_pack
                FROM workflow_bags wb
                LEFT JOIN product_details pd ON pd.id = wb.product_id
                WHERE wb.id = ?
                """,
                (int(workflow_bag_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            return "card"
    if row:
        r = dict(row)
        if int(r.get("is_bottle_product") or 0) == 1 or int(r.get("is_variety_pack") or 0) == 1:
            return "bottle"
    return "card"


def floor_bag_verification(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, Any]:
    """Human-readable bag identity for floor verification (product, box, bag, PO, shipment).

    Denormalized ``workflow_bags`` fields are used; when ``inventory_bag_id`` is set, receiving/PO
    data supplements or overrides missing PO/shipment labels.
    """
    wid = int(workflow_bag_id)
    try:
        row = conn.execute(
            """
            SELECT wb.product_id, wb.box_number, wb.bag_number, wb.receipt_number, wb.inventory_bag_id,
                   pd.product_name AS product_name,
                   tt.tablet_type_name AS tablet_type_name
            FROM workflow_bags wb
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            LEFT JOIN bags b ON b.id = wb.inventory_bag_id
            LEFT JOIN tablet_types tt ON tt.id = b.tablet_type_id
            WHERE wb.id = ?
            """,
            (wid,),
        ).fetchone()
    except sqlite3.OperationalError:
        try:
            row = conn.execute(
                """
                SELECT wb.product_id, wb.box_number, wb.bag_number, wb.receipt_number, wb.inventory_bag_id,
                       pd.product_name AS product_name, NULL AS tablet_type_name
                FROM workflow_bags wb
                LEFT JOIN product_details pd ON pd.id = wb.product_id
                WHERE wb.id = ?
                """,
                (wid,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {}
    if not row:
        return {}
    wb = dict(row)
    product_name = (wb.get("product_name") or "").strip() or None
    tablet_type_name = (wb.get("tablet_type_name") or "").strip() or None
    box_raw = wb.get("box_number")
    bag_raw = wb.get("bag_number")
    box_s = str(box_raw).strip() if box_raw is not None and str(box_raw).strip() else None
    bag_s = str(bag_raw).strip() if bag_raw is not None and str(bag_raw).strip() else None
    receipt_fallback = (wb.get("receipt_number") or "").strip() or None

    po_number: str | None = None
    shipment_label: str | None = receipt_fallback

    inv_id = wb.get("inventory_bag_id")
    if inv_id:
        try:
            inv = conn.execute(
                """
                SELECT po.po_number AS po_number,
                       r.receive_name AS receive_name,
                       sb.box_number AS inv_box,
                       b.bag_number AS inv_bag
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                WHERE b.id = ?
                """,
                (int(inv_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            inv = None
        if inv:
            invd = dict(inv)
            po = invd.get("po_number")
            if po is not None and str(po).strip():
                po_number = str(po).strip()
            rn = invd.get("receive_name")
            if (not receipt_fallback) and rn is not None and str(rn).strip():
                shipment_label = str(rn).strip()
            if not box_s:
                ib = invd.get("inv_box")
                if ib is not None and str(ib).strip():
                    box_s = str(ib).strip()
            if not bag_s:
                ig = invd.get("inv_bag")
                if ig is not None and str(ig).strip():
                    bag_s = str(ig).strip()

    def _fmt_box_bag(label: str, raw: str | None) -> str | None:
        if not raw:
            return None
        return f"{label} {raw}"

    return {
        "product_name": product_name,
        "tablet_type_name": tablet_type_name,
        "production_flow": production_flow_for_bag(conn, workflow_bag_id),
        "box_display": _fmt_box_bag("Box", box_s),
        "bag_display": _fmt_box_bag("Bag", bag_s),
        "po_number": po_number,
        "receipt_number": receipt_fallback,
        "shipment_label": shipment_label,
    }


def display_stage_label(facts: dict[str, Any]) -> str:
    """Cosmetic label from latest event type string — formatting only."""
    lt = facts.get("latest_event_type")
    if not lt:
        return "No events"
    pretty = {
        WC.EVENT_CARD_ASSIGNED: "Card assigned",
        WC.EVENT_PRODUCT_MAPPED: "Product mapped",
        WC.EVENT_BAG_CLAIMED: "Bag claimed",
        WC.EVENT_STATION_RESUMED: "Station resumed",
        WC.EVENT_BLISTER_COMPLETE: "Blister",
        WC.EVENT_SEALING_COMPLETE: "Sealing",
        WC.EVENT_BOTTLE_HANDPACK_COMPLETE: "Bottle hand pack",
        WC.EVENT_BOTTLE_STICKER_COMPLETE: "Bottle sticker",
        WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE: "Bottle cap seal",
        WC.EVENT_PACKAGING_SNAPSHOT: "Packaging",
        WC.EVENT_PACKAGING_TAKEN_FOR_ORDER: "Taken for order",
        WC.EVENT_SUBMISSION_CORRECTED: "Submission corrected",
        WC.EVENT_BAG_FINALIZED: "Complete",
        WC.EVENT_CARD_FORCE_RELEASED: "Card released (admin)",
    }
    return pretty.get(lt, lt.replace("_", " ").title())


def progress_summary(facts: dict[str, Any]) -> str:
    """Human summary from counts — cosmetic; do not use as API contract for rules."""
    c = facts.get("event_counts_by_type") or {}
    parts = []
    if c.get(WC.EVENT_BAG_CLAIMED):
        parts.append(f"claimed×{c[WC.EVENT_BAG_CLAIMED]}")
    if c.get(WC.EVENT_BLISTER_COMPLETE):
        parts.append(f"blister×{c[WC.EVENT_BLISTER_COMPLETE]}")
    if c.get(WC.EVENT_SEALING_COMPLETE):
        parts.append(f"seal×{c[WC.EVENT_SEALING_COMPLETE]}")
    if c.get(WC.EVENT_BOTTLE_HANDPACK_COMPLETE):
        parts.append(f"bottle handpack×{c[WC.EVENT_BOTTLE_HANDPACK_COMPLETE]}")
    if c.get(WC.EVENT_BOTTLE_STICKER_COMPLETE):
        parts.append(f"sticker×{c[WC.EVENT_BOTTLE_STICKER_COMPLETE]}")
    if c.get(WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE):
        parts.append(f"bottle seal×{c[WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE]}")
    if c.get(WC.EVENT_PACKAGING_SNAPSHOT):
        parts.append(f"pkg×{c[WC.EVENT_PACKAGING_SNAPSHOT]}")
    if c.get(WC.EVENT_PACKAGING_TAKEN_FOR_ORDER):
        parts.append(f"taken×{c[WC.EVENT_PACKAGING_TAKEN_FOR_ORDER]}")
    if c.get(WC.EVENT_SUBMISSION_CORRECTED):
        parts.append(f"corrected×{c[WC.EVENT_SUBMISSION_CORRECTED]}")
    if not parts:
        return "No progress events yet"
    return ", ".join(parts)


_SUBMISSION_EVENT_TYPES = {
    WC.EVENT_BLISTER_COMPLETE,
    WC.EVENT_SEALING_COMPLETE,
    WC.EVENT_OPERATOR_CHANGE,
    WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
    WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
    WC.EVENT_BOTTLE_STICKER_COMPLETE,
    WC.EVENT_PACKAGING_SNAPSHOT,
    WC.EVENT_PACKAGING_TAKEN_FOR_ORDER,
    WC.EVENT_SUBMISSION_CORRECTED,
}


def _format_event_time_ms(ms: Any) -> str:
    if ms is None:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OSError):
        return str(ms)


def _payload_pause_reason(event_type: str, payload: dict[str, Any]) -> str | None:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    reason = str(payload.get("reason") or payload.get("pause_reason") or meta.get("reason") or "").strip()
    if bool(meta.get("paused")):
        return reason or "paused"
    if reason in {"paused_end_of_day", "end_of_day", "out_of_packaging", "material_change"}:
        return reason
    if event_type == WC.EVENT_BLISTER_COMPLETE and payload.get("pause_reason"):
        return str(payload.get("pause_reason"))
    return None


def _event_entry_kind(event_type: str, payload: dict[str, Any]) -> str:
    pause_reason = _payload_pause_reason(event_type, payload)
    if pause_reason:
        return f"Pause: {pause_reason.replace('_', ' ')}"
    if event_type == WC.EVENT_PACKAGING_SNAPSHOT and payload.get("reason") == "final_submit":
        return "End submit"
    if event_type == WC.EVENT_BAG_FINALIZED:
        return "Finalized"
    if event_type == WC.EVENT_CARD_ASSIGNED:
        return "Assignment"
    if event_type == WC.EVENT_BAG_CLAIMED:
        return "Claim"
    if event_type == WC.EVENT_STATION_RESUMED:
        return "Resume"
    if event_type == WC.EVENT_SUBMISSION_CORRECTED:
        return "Correction"
    if event_type == WC.EVENT_CARD_FORCE_RELEASED:
        return "Admin release"
    if event_type in _SUBMISSION_EVENT_TYPES:
        return "Submit"
    return "Event"


def _payload_detail_parts(payload: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    labels = (
        ("count_total", "count"),
        ("display_count", "displays"),
        ("case_count", "cases"),
        ("loose_display_count", "loose displays"),
        ("packs_remaining", "packs remaining"),
        ("loose_tablets", "loose tablets"),
        ("cards_reopened", "cards reopened"),
        ("bottles_made", "bottles"),
        ("bottle_sealing_machine_count", "bottle machine"),
        ("displays_taken", "displays taken"),
    )
    for key, label in labels:
        val = payload.get(key)
        if val is not None and str(val).strip() != "":
            parts.append(f"{label}: {val}")
    employee = payload.get("employee_name")
    if employee:
        parts.append(f"employee: {employee}")
    reason = payload.get("reason") or payload.get("pause_reason")
    if reason:
        parts.append(f"reason: {str(reason).replace('_', ' ')}")
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if meta.get("material_type"):
        parts.append(f"material: {meta.get('material_type')}")
    if payload.get("corrected_event_type"):
        parts.append(f"corrected: {payload.get('corrected_event_type')}")
    if payload.get("target_event_id"):
        parts.append(f"target event: {payload.get('target_event_id')}")
    return parts


def _event_count_summary(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == WC.EVENT_PACKAGING_SNAPSHOT:
        displays = payload.get("display_count")
        if displays is not None:
            reason = str(payload.get("reason") or "").replace("_", " ")
            suffix = f" ({reason})" if reason else ""
            return f"pkg {displays} displays{suffix}"
    if event_type == WC.EVENT_PACKAGING_TAKEN_FOR_ORDER and payload.get("displays_taken") is not None:
        return f"taken {payload.get('displays_taken')} displays"
    if event_type in {
        WC.EVENT_BLISTER_COMPLETE,
        WC.EVENT_SEALING_COMPLETE,
        WC.EVENT_OPERATOR_CHANGE,
        WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
        WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE,
        WC.EVENT_BOTTLE_STICKER_COMPLETE,
    } and payload.get("count_total") is not None:
        label = {
            WC.EVENT_BLISTER_COMPLETE: "blister",
            WC.EVENT_SEALING_COMPLETE: "seal",
            WC.EVENT_OPERATOR_CHANGE: "operator",
            WC.EVENT_BOTTLE_HANDPACK_COMPLETE: "handpack",
            WC.EVENT_BOTTLE_CAP_SEAL_COMPLETE: "bottle seal",
            WC.EVENT_BOTTLE_STICKER_COMPLETE: "sticker",
        }.get(event_type, event_type.lower())
        return f"{label} {payload.get('count_total')}"
    return None


def _fetch_workflow_event_rows(conn: sqlite3.Connection, workflow_bag_id: int) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT we.id, we.event_type, we.payload, we.occurred_at, we.workflow_bag_id,
                   we.station_id, we.user_id, we.device_id,
                   ws.label AS station_label,
                   ws.station_kind AS station_kind,
                   ws.station_code AS station_code
            FROM workflow_events we
            LEFT JOIN workflow_stations ws ON ws.id = we.station_id
            WHERE we.workflow_bag_id = ?
            ORDER BY we.occurred_at ASC, we.id ASC
            """,
            (int(workflow_bag_id),),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            """
            SELECT id, event_type, payload, occurred_at, workflow_bag_id,
                   station_id, user_id, device_id
            FROM workflow_events
            WHERE workflow_bag_id = ?
            ORDER BY occurred_at ASC, id ASC
            """,
            (int(workflow_bag_id),),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        payload = json.loads(d.get("payload") or "{}")
        station_id = d.get("station_id") or payload.get("station_id")
        station_label = d.get("station_label") or None
        station_kind = d.get("station_kind") or payload.get("station_kind") or None
        if station_label and station_kind:
            station_display = f"{station_label} ({station_kind})"
        elif station_label:
            station_display = str(station_label)
        elif station_kind:
            station_display = str(station_kind).replace("_", " ").title()
        elif station_id:
            station_display = f"Station #{station_id}"
        else:
            station_display = "—"
        out.append(
            {
                "id": d.get("id"),
                "event_type": d.get("event_type"),
                "label": display_stage_label({"latest_event_type": d.get("event_type")}),
                "payload": payload,
                "occurred_at": d.get("occurred_at"),
                "occurred_display": _format_event_time_ms(d.get("occurred_at")),
                "station_id": station_id,
                "station_display": station_display,
                "entry_kind": _event_entry_kind(str(d.get("event_type") or ""), payload),
                "detail_parts": _payload_detail_parts(payload),
                "count_summary": _event_count_summary(str(d.get("event_type") or ""), payload),
            }
        )
    return out


def _submission_row_summary(row: dict[str, Any]) -> str:
    stype = str(row.get("submission_type") or "packaged")
    parts: list[str] = []
    if stype == "machine":
        for key, label in (
            ("tablets_pressed_into_cards", "pressed"),
            ("packs_remaining", "packs remaining"),
            ("loose_tablets", "loose tablets"),
        ):
            val = row.get(key)
            if val is not None and str(val).strip() != "":
                parts.append(f"{label}: {val}")
    elif stype == "bottle":
        for key, label in (
            ("bottles_made", "bottles"),
            ("bottle_sealing_machine_count", "machine count"),
            ("packs_remaining", "packs remaining"),
            ("loose_tablets", "loose tablets"),
        ):
            val = row.get(key)
            if val is not None and str(val).strip() != "":
                parts.append(f"{label}: {val}")
    else:
        for key, label in (
            ("displays_made", "displays"),
            ("case_count", "cases"),
            ("loose_display_count", "loose displays"),
            ("packs_remaining", "packs remaining"),
            ("loose_tablets", "loose tablets"),
        ):
            val = row.get(key)
            if val is not None and str(val).strip() != "":
                parts.append(f"{label}: {val}")
    return ", ".join(parts) if parts else "No count fields"


def _fetch_synced_submission_rows(conn: sqlite3.Connection, workflow_bag_id: int, receipt_number: str | None) -> list[dict[str, Any]]:
    base_receipt = (receipt_number or f"WORKFLOW-{workflow_bag_id}").strip()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM warehouse_submissions
            WHERE receipt_number = ?
               OR receipt_number LIKE ?
               OR receipt_number LIKE ?
               OR receipt_number LIKE ?
            ORDER BY created_at ASC, id ASC
            """,
            (
                base_receipt,
                base_receipt + "-pkg-e%",
                base_receipt + "-seal%",
                base_receipt + "-blister%",
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["type_display"] = str(d.get("submission_type") or "packaged").replace("_", " ").title()
        d["summary"] = _submission_row_summary(d)
        d["created_display"] = d.get("created_at") or d.get("submission_date") or "—"
        out.append(d)
    return out


def workflow_submission_details(conn: sqlite3.Connection, workflow_bag_id: int, receipt_number: str | None = None) -> dict[str, Any]:
    """Timeline + editable synced rows for the QR submissions page."""
    events = _fetch_workflow_event_rows(conn, int(workflow_bag_id))
    submission_events = [e for e in events if e["event_type"] in _SUBMISSION_EVENT_TYPES]
    count_parts = [e["count_summary"] for e in submission_events if e.get("count_summary")]
    synced_rows = _fetch_synced_submission_rows(conn, int(workflow_bag_id), receipt_number)
    return {
        "timeline_events": events,
        "submission_events": submission_events,
        "submission_event_count": len(submission_events),
        "count_summary": ", ".join(count_parts[-4:]) if count_parts else "No entered counts yet",
        "latest_entry_display": count_parts[-1] if count_parts else "—",
        "synced_rows": synced_rows,
        "synced_row_count": len(synced_rows),
    }


def card_lifecycle_events_for_card(conn: sqlite3.Connection, qr_card_id: int) -> list[dict[str, Any]]:
    """Union of bag timelines for bags that had this card + standalone force-release rows."""
    rows = conn.execute(
        """
        SELECT we.id, we.event_type, we.payload, we.occurred_at, we.workflow_bag_id,
               we.station_id, we.user_id, we.device_id
        FROM workflow_events we
        WHERE we.workflow_bag_id IN (
            SELECT DISTINCT workflow_bag_id FROM workflow_events
            WHERE event_type = ?
              AND CAST(json_extract(payload, '$.qr_card_id') AS INTEGER) = ?
        )
           OR (
               we.event_type = ?
               AND CAST(json_extract(we.payload, '$.qr_card_id') AS INTEGER) = ?
           )
        ORDER BY we.occurred_at ASC, we.id ASC
        """,
        (
            WC.EVENT_CARD_ASSIGNED,
            qr_card_id,
            WC.EVENT_CARD_FORCE_RELEASED,
            qr_card_id,
        ),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "payload": json.loads(r["payload"]),
                "occurred_at": r["occurred_at"],
                "workflow_bag_id": r["workflow_bag_id"],
                "station_id": r["station_id"],
                "user_id": r["user_id"],
                "device_id": r["device_id"],
            }
        )
    return out


def card_idle_fact_from_fold(events: list[dict[str, Any]]) -> bool:
    """True if canonical idle: tail lifecycle outcome is release (finalize or force)."""
    if not events:
        return True
    tail = events[-1]["event_type"]
    if tail == WC.EVENT_BAG_FINALIZED:
        return True
    if tail == WC.EVENT_CARD_FORCE_RELEASED:
        return True
    if tail == WC.EVENT_CARD_ASSIGNED:
        return False
    # Other event types should not appear in this fold; treat as not idle (safe)
    return False


def verify_qr_card_matches_fold(conn: sqlite3.Connection, qr_card_id: int, qr_row: sqlite3.Row) -> bool:
    """Post-commit check: mutex row vs event fold (detect cache bugs)."""
    fold_idle = card_idle_fact_from_fold(card_lifecycle_events_for_card(conn, qr_card_id))
    row_idle = qr_row["status"] == WC.QR_CARD_STATUS_IDLE
    return fold_idle == row_idle


def get_finalize_row(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, Any] | None:
    for e in load_events_for_bag(conn, workflow_bag_id):
        if e["event_type"] == WC.EVENT_BAG_FINALIZED:
            return e
    return None
