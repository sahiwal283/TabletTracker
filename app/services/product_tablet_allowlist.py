"""Allowed physical tablet types per finished product (primary + configured alternates)."""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Sequence


def allowed_tablet_type_ids_for_product(conn: sqlite3.Connection, product_id: int) -> list[int]:
    """Return ordered unique tablet_type ids allowed for this product (receiving / bag match)."""
    pid = int(product_id)
    try:
        rows = conn.execute(
            """
            SELECT tablet_type_id FROM product_allowed_tablet_types
            WHERE product_details_id = ?
            ORDER BY tablet_type_id
            """,
            (pid,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = ()
    if rows:
        return [int(dict(r)["tablet_type_id"]) for r in rows]
    try:
        prow = conn.execute(
            """
            SELECT tablet_type_id, COALESCE(is_variety_pack, 0) AS is_variety_pack,
                   variety_pack_contents
            FROM product_details
            WHERE id = ?
            """,
            (pid,),
        ).fetchone()
    except sqlite3.OperationalError:
        prow = conn.execute(
            "SELECT tablet_type_id, 0 AS is_variety_pack, NULL AS variety_pack_contents FROM product_details WHERE id = ?",
            (pid,),
        ).fetchone()
    if prow and int(dict(prow).get("is_variety_pack") or 0) == 1:
        raw = dict(prow).get("variety_pack_contents")
        try:
            contents = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            contents = []
        ids: list[int] = []
        seen: set[int] = set()
        for item in contents if isinstance(contents, list) else []:
            if not isinstance(item, dict):
                continue
            tid = item.get("tablet_type_id")
            try:
                tid_i = int(tid)
            except (TypeError, ValueError):
                continue
            if tid_i not in seen:
                seen.add(tid_i)
                ids.append(tid_i)
        if ids:
            return ids
    if prow and prow["tablet_type_id"] is not None:
        return [int(prow["tablet_type_id"])]
    return []


def product_allows_tablet_type(conn: sqlite3.Connection, product_id: int, tablet_type_id: int) -> bool:
    allowed = allowed_tablet_type_ids_for_product(conn, product_id)
    return int(tablet_type_id) in allowed


def sync_product_allowed_tablets(
    conn: sqlite3.Connection,
    *,
    product_details_id: int,
    primary_tablet_type_id: int | None,
    extra_tablet_type_ids: Sequence[int] | None = None,
    clear_only: bool = False,
) -> None:
    """
    Replace allowlist rows. When ``clear_only`` or no primary, table is cleared for this product.
    Otherwise primary is always included plus any extras (deduped).
    """
    pid = int(product_details_id)
    try:
        conn.execute("DELETE FROM product_allowed_tablet_types WHERE product_details_id = ?", (pid,))
    except sqlite3.OperationalError:
        return
    if clear_only or primary_tablet_type_id is None:
        return
    ids = {int(primary_tablet_type_id)}
    for x in extra_tablet_type_ids or []:
        try:
            ids.add(int(x))
        except (TypeError, ValueError):
            continue
    for tid in sorted(ids):
        try:
            conn.execute(
                """
                INSERT INTO product_allowed_tablet_types (product_details_id, tablet_type_id)
                VALUES (?, ?)
                """,
                (pid, tid),
            )
        except sqlite3.OperationalError:
            return


def inventory_item_id_for_bag_tablet(conn: sqlite3.Connection, bag_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT tt.inventory_item_id
        FROM bags b
        JOIN tablet_types tt ON tt.id = b.tablet_type_id
        WHERE b.id = ?
        """,
        (int(bag_id),),
    ).fetchone()
    if not row or not row["inventory_item_id"]:
        return None
    return str(row["inventory_item_id"]).strip() or None
