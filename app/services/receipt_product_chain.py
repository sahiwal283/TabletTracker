"""Receipt chain: blister / seal / packaging share one finished product per logical receipt."""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

from app.services.production_submission_helpers import ProductionSubmissionError


def receipt_chain_key(receipt_number: Optional[str]) -> str:
    """Strip workflow suffixes so ``BASE-seal``, ``BASE-blister-e1``, ``BASE-pkg-e2`` share one key."""
    s = (receipt_number or "").strip()
    if not s:
        return ""
    s = re.sub(r"-pkg-e\d+$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"-take-e\d+$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"-(?:seal|blister)(?:-e\d+)?$", "", s, flags=re.IGNORECASE)
    return s.strip()


def assert_receipt_product_chain(
    conn: sqlite3.Connection,
    *,
    receipt_number: Optional[str],
    product_name: str,
) -> None:
    """
    If ``receipt_number`` is set and other submissions exist in the same chain,
    require the same ``product_name``.
    """
    rn = (receipt_number or "").strip()
    pn = (product_name or "").strip()
    if not rn or not pn:
        return
    key = receipt_chain_key(rn)
    if not key:
        return
    rows = conn.execute(
        """
        SELECT DISTINCT TRIM(product_name) AS product_name, receipt_number
        FROM warehouse_submissions
        WHERE receipt_number IS NOT NULL AND TRIM(receipt_number) != ''
          AND (
            TRIM(receipt_number) = ?
            OR TRIM(receipt_number) LIKE ? || '-%'
          )
        """,
        (key, key),
    ).fetchall()
    for row in rows:
        r = dict(row)
        other_rn = (r.get("receipt_number") or "").strip()
        if receipt_chain_key(other_rn) != key:
            continue
        other_pn = (r.get("product_name") or "").strip()
        if not other_pn:
            continue
        if other_pn != pn:
            raise ProductionSubmissionError(
                400,
                {
                    "error": (
                        f'Receipt chain "{key}" already has product **{other_pn}**. '
                        f'You are submitting **{pn}**. All steps (blister, sealing, packaging) '
                        "must use the same finished product for this receipt."
                    )
                },
            )
