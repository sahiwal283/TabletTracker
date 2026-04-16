
"""Read-only queries and mechanical facts for workflow_events (no policy / no rule booleans)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

from app.services import workflow_constants as WC

_NY = ZoneInfo("America/New_York")


def production_day_for_event_ms(occurred_at_ms: int) -> date:
    """Factory-local calendar date bucket (America/New_York) for reporting."""
    dt = datetime.fromtimestamp(occurred_at_ms / 1000.0, tz=timezone.utc)
    return dt.astimezone(_NY).date()


def _parse_row_payload(row: sqlite3.Row) -> Dict[str, Any]:
    return json.loads(row["payload"])


def load_events_for_bag(conn: sqlite3.Connection, workflow_bag_id: int) -> List[Dict[str, Any]]:
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
    out: List[Dict[str, Any]] = []
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


def latest_event_row_for_bag(
    conn: sqlite3.Connection, workflow_bag_id: int
) -> Optional[Dict[str, Any]]:
    ev = load_events_for_bag(conn, workflow_bag_id)
    return ev[-1] if ev else None


def event_counts_by_type(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in events:
        t = e["event_type"]
        counts[t] = counts.get(t, 0) + 1
    return counts


def latest_event_type_tail(events: List[Dict[str, Any]]) -> Optional[str]:
    return events[-1]["event_type"] if events else None


def mechanical_bag_facts(conn: sqlite3.Connection, workflow_bag_id: int) -> Dict[str, Any]:
    """Facts + aggregates only (no is_complete / policy)."""
    events = load_events_for_bag(conn, workflow_bag_id)
    return {
        "workflow_bag_id": workflow_bag_id,
        "event_count": len(events),
        "event_counts_by_type": event_counts_by_type(events),
        "latest_event_type": latest_event_type_tail(events),
        "events": events,
    }


def floor_bag_verification(conn: sqlite3.Connection, workflow_bag_id: int) -> Dict[str, Any]:
    """Human-readable bag identity for floor verification (product, box, bag, PO, shipment).

    Denormalized ``workflow_bags`` fields are used; when ``inventory_bag_id`` is set, receiving/PO
    data supplements or overrides missing PO/shipment labels.
    """
    wid = int(workflow_bag_id)
    try:
        row = conn.execute(
            """
            SELECT wb.product_id, wb.box_number, wb.bag_number, wb.receipt_number, wb.inventory_bag_id,
                   pd.product_name AS product_name
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
    box_raw = wb.get("box_number")
    bag_raw = wb.get("bag_number")
    box_s = str(box_raw).strip() if box_raw is not None and str(box_raw).strip() else None
    bag_s = str(bag_raw).strip() if bag_raw is not None and str(bag_raw).strip() else None
    receipt_fallback = (wb.get("receipt_number") or "").strip() or None

    po_number: Optional[str] = None
    shipment_label: Optional[str] = receipt_fallback

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

    def _fmt_box_bag(label: str, raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        return f"{label} {raw}"

    return {
        "product_name": product_name,
        "box_display": _fmt_box_bag("Box", box_s),
        "bag_display": _fmt_box_bag("Bag", bag_s),
        "po_number": po_number,
        "receipt_number": receipt_fallback,
        "shipment_label": shipment_label,
    }


def display_stage_label(facts: Dict[str, Any]) -> str:
    """Cosmetic label from latest event type string — formatting only."""
    lt = facts.get("latest_event_type")
    if not lt:
        return "No events"
    pretty = {
        WC.EVENT_CARD_ASSIGNED: "Card assigned",
        WC.EVENT_BAG_CLAIMED: "Bag claimed",
        WC.EVENT_STATION_RESUMED: "Station resumed",
        WC.EVENT_BLISTER_COMPLETE: "Blister",
        WC.EVENT_SEALING_COMPLETE: "Sealing",
        WC.EVENT_PACKAGING_SNAPSHOT: "Packaging",
        WC.EVENT_PACKAGING_TAKEN_FOR_ORDER: "Taken for order",
        WC.EVENT_BAG_FINALIZED: "Complete",
        WC.EVENT_CARD_FORCE_RELEASED: "Card released (admin)",
    }
    return pretty.get(lt, lt.replace("_", " ").title())


def progress_summary(facts: Dict[str, Any]) -> str:
    """Human summary from counts — cosmetic; do not use as API contract for rules."""
    c = facts.get("event_counts_by_type") or {}
    parts = []
    if c.get(WC.EVENT_BAG_CLAIMED):
        parts.append(f"claimed×{c[WC.EVENT_BAG_CLAIMED]}")
    if c.get(WC.EVENT_BLISTER_COMPLETE):
        parts.append(f"blister×{c[WC.EVENT_BLISTER_COMPLETE]}")
    if c.get(WC.EVENT_SEALING_COMPLETE):
        parts.append(f"seal×{c[WC.EVENT_SEALING_COMPLETE]}")
    if c.get(WC.EVENT_PACKAGING_SNAPSHOT):
        parts.append(f"pkg×{c[WC.EVENT_PACKAGING_SNAPSHOT]}")
    if c.get(WC.EVENT_PACKAGING_TAKEN_FOR_ORDER):
        parts.append(f"taken×{c[WC.EVENT_PACKAGING_TAKEN_FOR_ORDER]}")
    if not parts:
        return "No progress events yet"
    return ", ".join(parts)


def card_lifecycle_events_for_card(
    conn: sqlite3.Connection, qr_card_id: int
) -> List[Dict[str, Any]]:
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
    out: List[Dict[str, Any]] = []
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


def card_idle_fact_from_fold(events: List[Dict[str, Any]]) -> bool:
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


def verify_qr_card_matches_fold(
    conn: sqlite3.Connection, qr_card_id: int, qr_row: sqlite3.Row
) -> bool:
    """Post-commit check: mutex row vs event fold (detect cache bugs)."""
    fold_idle = card_idle_fact_from_fold(card_lifecycle_events_for_card(conn, qr_card_id))
    row_idle = qr_row["status"] == WC.QR_CARD_STATUS_IDLE
    return fold_idle == row_idle


def get_finalize_row(conn: sqlite3.Connection, workflow_bag_id: int) -> Optional[Dict[str, Any]]:
    for e in load_events_for_bag(conn, workflow_bag_id):
        if e["event_type"] == WC.EVENT_BAG_FINALIZED:
            return e
    return None
