"""Normalize packaged submission case/display fields for UI."""

from __future__ import annotations

from typing import Any


def normalize_packaged_case_fields_for_ui(
    sub_dict: dict[str, Any],
    *,
    warehouse_submission_type: str | None = None,
) -> None:
    """
    Before the case/loose split, operators entered a single **display count** stored in
    ``displays_made``. Schema migration added ``case_count`` and ``loose_display_count`` with
    DEFAULT 0, so old rows looked like (0 cases, 0 loose displays) while ``displays_made`` still
    held the real number.

    When both stored case fields are 0, treat that as the backfill pattern (or cards-only submit
    with no case UI): expose the entered display total as ``loose_display_count`` so every consumer
    that reads loose displays sees the same number as ``displays_made``, and clear ``case_count``
    for display (cases were not captured on that row).
    """
    # Use the row's warehouse_submissions.submission_type when provided so product-config coercion
    # (e.g. variety → bottle for workflow) does not skip rows that are still packaged in the DB.
    eff = (
        warehouse_submission_type
        if warehouse_submission_type is not None
        else (sub_dict.get("submission_type") or "packaged")
    )
    if eff != "packaged":
        return
    if "case_count" not in sub_dict or "loose_display_count" not in sub_dict:
        return
    dm = int(sub_dict.get("displays_made") or 0)
    ec = int(sub_dict.get("case_count") or 0)
    el = int(sub_dict.get("loose_display_count") or 0)
    if ec == 0 and el == 0:
        sub_dict["packaged_legacy_displays_only"] = True
        sub_dict["case_count"] = None
        sub_dict["loose_display_count"] = dm
        sub_dict["cases_made_total"] = None
