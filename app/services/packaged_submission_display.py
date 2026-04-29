"""Normalize packaged submission case/display fields for UI."""

from __future__ import annotations

from typing import Any


def normalize_packaged_case_fields_for_ui(sub_dict: dict[str, Any]) -> None:
    """
    Rows created before case capture stored operator-entered display totals in ``displays_made``.
    Adding ``case_count`` / ``loose_display_count`` with DEFAULT 0 backfilled zeros on old rows, so
    the UI showed 0 displays while tablet totals (from displays_made) were still correct.

    When both stored case fields are zero but ``displays_made`` is positive, treat as legacy:
    clear the synthetic zeros so consumers fall back to ``displays_made``.
    """
    if (sub_dict.get("submission_type") or "packaged") != "packaged":
        return
    if "case_count" not in sub_dict or "loose_display_count" not in sub_dict:
        return
    dm = int(sub_dict.get("displays_made") or 0)
    ec = int(sub_dict.get("case_count") or 0)
    el = int(sub_dict.get("loose_display_count") or 0)
    if ec == 0 and el == 0 and dm > 0:
        sub_dict["packaged_legacy_displays_only"] = True
        sub_dict["case_count"] = None
        sub_dict["loose_display_count"] = None
        sub_dict["cases_made_total"] = None
