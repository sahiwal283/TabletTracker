"""Helpers for parent variety QR runs and their child bag QR sources."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from app.services import workflow_constants as WC

SOURCE_EVENT_TYPES = (
    WC.EVENT_VARIETY_SOURCES_ASSIGNED,
    WC.EVENT_BOTTLE_HANDPACK_COMPLETE,
)


def parse_source_card_tokens(raw: Any) -> list[str]:
    """Normalize pasted/scanned source card tokens while preserving first-seen order."""
    if raw is None:
        parts: list[Any] = []
    elif isinstance(raw, str):
        parts = re.split(r"[\s,]+", raw)
    elif isinstance(raw, list):
        parts = raw
    else:
        parts = [raw]
    seen: set[str] = set()
    out: list[str] = []
    for item in parts:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def source_payload_for_parent(conn: sqlite3.Connection, workflow_bag_id: int) -> dict[str, list]:
    """Union source ids/tokens already assigned or scanned for a parent variety workflow."""
    try:
        qmarks = ",".join("?" for _ in SOURCE_EVENT_TYPES)
        rows = conn.execute(
            f"""
            SELECT payload
            FROM workflow_events
            WHERE workflow_bag_id = ?
              AND event_type IN ({qmarks})
            ORDER BY occurred_at ASC, id ASC
            """,
            (int(workflow_bag_id), *SOURCE_EVENT_TYPES),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []

    fields = {
        "source_card_tokens": [],
        "source_qr_card_ids": [],
        "source_workflow_bag_ids": [],
        "source_inventory_bag_ids": [],
    }
    seen: dict[str, set] = {k: set() for k in fields}
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in fields:
            for raw in payload.get(key) or []:
                value = str(raw).strip() if key == "source_card_tokens" else _coerce_int(raw)
                if value is None or value in seen[key]:
                    continue
                seen[key].add(value)
                fields[key].append(value)
    return fields


def active_variety_parent_for_source_bag(
    conn: sqlite3.Connection,
    source_workflow_bag_id: int,
    *,
    excluding_parent_workflow_bag_id: int | None = None,
) -> dict | None:
    """Return the active variety parent that owns a source bag, if any."""
    try:
        qmarks = ",".join("?" for _ in SOURCE_EVENT_TYPES)
        rows = conn.execute(
            f"""
            SELECT we.workflow_bag_id AS parent_workflow_bag_id, we.payload,
                   wb.receipt_number, pd.product_name, qc.scan_token
            FROM workflow_events we
            JOIN workflow_bags wb ON wb.id = we.workflow_bag_id
            LEFT JOIN product_details pd ON pd.id = wb.product_id
            LEFT JOIN qr_cards qc
              ON qc.assigned_workflow_bag_id = we.workflow_bag_id
             AND qc.status = ?
            WHERE we.event_type IN ({qmarks})
              AND we.workflow_bag_id != ?
              AND NOT EXISTS (
                SELECT 1
                FROM workflow_events fin
                WHERE fin.workflow_bag_id = we.workflow_bag_id
                  AND fin.event_type = ?
              )
            ORDER BY we.occurred_at DESC, we.id DESC
            """,
            (
                WC.QR_CARD_STATUS_ASSIGNED,
                *SOURCE_EVENT_TYPES,
                int(excluding_parent_workflow_bag_id or 0),
                WC.EVENT_BAG_FINALIZED,
            ),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    source_id = int(source_workflow_bag_id)
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for raw in payload.get("source_workflow_bag_ids") or []:
            child_id = _coerce_int(raw)
            if child_id != source_id:
                continue
            parent = dict(row)
            label = (
                parent.get("receipt_number")
                or parent.get("product_name")
                or parent.get("scan_token")
                or f"workflow bag #{parent.get('parent_workflow_bag_id')}"
            )
            return {**parent, "parent_label": str(label)}
    return None


def resolve_source_cards(
    conn: sqlite3.Connection,
    *,
    source_card_tokens: Any,
    parent_card_token: str | None = None,
    excluding_parent_workflow_bag_id: int | None = None,
) -> dict[str, list]:
    """Resolve source QR card tokens to workflow and inventory bag ids."""
    parent_token = str(parent_card_token or "").strip()
    tokens = [t for t in parse_source_card_tokens(source_card_tokens) if t != parent_token]
    if not tokens:
        return {
            "source_card_tokens": [],
            "source_qr_card_ids": [],
            "source_workflow_bag_ids": [],
            "source_inventory_bag_ids": [],
        }
    qmarks = ",".join("?" for _ in tokens)
    rows = conn.execute(
        f"""
        SELECT qc.id AS qr_card_id, qc.scan_token, qc.assigned_workflow_bag_id,
               wb.inventory_bag_id, wb.product_id
        FROM qr_cards qc
        JOIN workflow_bags wb ON wb.id = qc.assigned_workflow_bag_id
        WHERE qc.status = ?
          AND qc.scan_token IN ({qmarks})
        """,
        (WC.QR_CARD_STATUS_ASSIGNED, *tokens),
    ).fetchall()
    by_token = {str(r["scan_token"]): dict(r) for r in rows}
    missing = [t for t in tokens if t not in by_token]
    if missing:
        raise ValueError(f"source_card_not_assigned:{missing[0]}")

    qr_card_ids: list[int] = []
    workflow_ids: list[int] = []
    inventory_ids: list[int] = []
    for token in tokens:
        row = by_token[token]
        if row.get("inventory_bag_id") is None:
            raise ValueError("source_card_missing_inventory_bag")
        workflow_bag_id = int(row["assigned_workflow_bag_id"])
        locked = active_variety_parent_for_source_bag(
            conn,
            workflow_bag_id,
            excluding_parent_workflow_bag_id=excluding_parent_workflow_bag_id,
        )
        if locked:
            label = locked.get("parent_label") or locked.get("parent_workflow_bag_id")
            raise ValueError(f"source_card_already_variety_assigned:{label}")
        qr_card_ids.append(int(row["qr_card_id"]))
        workflow_ids.append(workflow_bag_id)
        inventory_ids.append(int(row["inventory_bag_id"]))
    return {
        "source_card_tokens": tokens,
        "source_qr_card_ids": qr_card_ids,
        "source_workflow_bag_ids": workflow_ids,
        "source_inventory_bag_ids": inventory_ids,
    }


def _coerce_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
