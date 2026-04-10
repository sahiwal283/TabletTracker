"""
Repack (tablet search): distribute finished repack tablets across PO bags for receiving visibility.

Sort: damage_metric DESC, remaining_capacity DESC. Water-fill up to per-bag capacity.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

# Allocation JSON version stored in warehouse_submissions.repack_bag_allocations
ALLOCATION_VERSION = 1


def _packaged_tablets_for_bag(conn, bag_id: int) -> int:
    """Good tablets already packaged from a bag (same logic as receiving_service.get_bag_with_packaged_count)."""
    packaged_count_row = conn.execute(
        """
        SELECT COALESCE(SUM(
            (COALESCE(ws.displays_made, 0) * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, 0)) +
            (COALESCE(ws.packs_remaining, 0) * COALESCE(pd.tablets_per_package, 0)) +
            COALESCE(ws.loose_tablets, 0)
        ), 0) as total_packaged
        FROM warehouse_submissions ws
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        WHERE ws.bag_id = ?
        AND ws.submission_type = 'packaged'
        """,
        (bag_id,),
    ).fetchone()
    bottle_direct_row = conn.execute(
        """
        SELECT COALESCE(SUM(
            COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
        ), 0) as total_bottle
        FROM warehouse_submissions ws
        LEFT JOIN product_details pd ON ws.product_name = pd.product_name
        WHERE ws.submission_type = 'bottle' AND ws.bag_id = ?
        """,
        (bag_id,),
    ).fetchone()
    bottle_junction_row = conn.execute(
        """
        SELECT COALESCE(SUM(sbd.tablets_deducted), 0) as total_junction
        FROM submission_bag_deductions sbd
        WHERE sbd.bag_id = ?
        """,
        (bag_id,),
    ).fetchone()
    return (
        (packaged_count_row["total_packaged"] if packaged_count_row else 0)
        + (bottle_direct_row["total_bottle"] if bottle_direct_row else 0)
        + (bottle_junction_row["total_junction"] if bottle_junction_row else 0)
    )


def _damaged_tablets_for_bag(conn, bag_id: int) -> int:
    """Sum cards re-opened (``damaged_tablets``) on submissions for this bag (packaging loss)."""
    row = conn.execute(
        """
        SELECT COALESCE(SUM(COALESCE(ws.damaged_tablets, 0)), 0) AS total_dmg
        FROM warehouse_submissions ws
        WHERE ws.bag_id = ?
        AND ws.submission_type IN ('packaged', 'machine', 'bag', 'bottle')
        """,
        (bag_id,),
    ).fetchone()
    return int(row["total_dmg"] if row else 0)


def load_bags_for_po_flavor(conn, po_id: int, tablet_type_id: int) -> List[Dict[str, Any]]:
    """All bags for PO with this tablet type, with damage and remaining capacity."""
    rows = conn.execute(
        """
        SELECT b.id AS bag_id, b.bag_number, b.bag_label_count, b.pill_count,
               sb.box_number, r.id AS receiving_id, r.receive_name, po.po_number
        FROM bags b
        JOIN small_boxes sb ON b.small_box_id = sb.id
        JOIN receiving r ON sb.receiving_id = r.id
        JOIN purchase_orders po ON r.po_id = po.id
        WHERE r.po_id = ? AND b.tablet_type_id = ?
        ORDER BY r.id, sb.box_number, b.bag_number
        """,
        (po_id, tablet_type_id),
    ).fetchall()

    bags: List[Dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        bag_id = r["bag_id"]
        label = r.get("bag_label_count") or r.get("pill_count") or 0
        packaged = _packaged_tablets_for_bag(conn, bag_id)
        remaining = max(0, int(label) - int(packaged))
        damage = _damaged_tablets_for_bag(conn, bag_id)
        receive_name = r.get("receive_name")
        if not receive_name and r.get("po_number") and r.get("receiving_id"):
            n = conn.execute(
                """
                SELECT COUNT(*) AS receive_number
                FROM receiving r2
                WHERE r2.po_id = ? AND r2.id <= ?
                """,
                (po_id, r["receiving_id"]),
            ).fetchone()
            seq = n["receive_number"] if n else 1
            receive_name = f"{r['po_number']}-{seq}"
        r["damage_metric"] = damage
        r["remaining_capacity"] = remaining
        r["receive_name"] = receive_name
        bags.append(r)
    return bags


def sort_bags_for_repack(bags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Damage DESC, then remaining capacity DESC."""
    return sorted(
        bags,
        key=lambda b: (b.get("damage_metric", 0), b.get("remaining_capacity", 0)),
        reverse=True,
    )


def allocate_repack_tablets(
    conn, po_id: int, tablet_type_id: int, output_tablets: int
) -> Tuple[Dict[str, Any], bool]:
    """
    Returns allocation payload and needs_review (True if overflow could not be placed).
    """
    if output_tablets <= 0:
        return (
            {
                "version": ALLOCATION_VERSION,
                "allocations": [],
                "overflow_tablets": 0,
                "needs_review": False,
            },
            False,
        )

    bags = load_bags_for_po_flavor(conn, po_id, tablet_type_id)
    ordered = sort_bags_for_repack(bags)
    allocations: List[Dict[str, Any]] = []
    left = output_tablets

    for b in ordered:
        if left <= 0:
            break
        cap = int(b.get("remaining_capacity") or 0)
        take = min(cap, left)
        if take > 0:
            allocations.append(
                {
                    "bag_id": b["bag_id"],
                    "tablets": take,
                    "box_number": b.get("box_number"),
                    "bag_number": b.get("bag_number"),
                    "receive_name": b.get("receive_name"),
                }
            )
            left -= take

    needs_review = left > 0
    if needs_review:
        allocations.append(
            {
                "bag_id": None,
                "tablets": left,
                "overflow": True,
                "box_number": None,
                "bag_number": None,
                "receive_name": None,
            }
        )

    payload = {
        "version": ALLOCATION_VERSION,
        "allocations": allocations,
        "overflow_tablets": left if needs_review else 0,
        "needs_review": needs_review,
    }
    return payload, needs_review


def allocation_payload_to_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def parse_allocation_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
