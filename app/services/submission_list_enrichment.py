"""
Chronological running totals and display fields shared by submission list UIs (dashboard, submissions).
"""

from __future__ import annotations

from typing import Any

from app.services.packaged_submission_display import normalize_packaged_case_fields_for_ui
from app.services.submission_query_service import common_receive_label_from_deductions


def new_running_totals_state() -> dict[str, dict[Any, int]]:
    return {
        "bag_cumulative_packaged": {},
        "bag_totals_bag": {},
        "bag_totals_machine": {},
        "bag_totals_packaged": {},
    }


def enrich_submission_row_running_totals(
    sub_dict: dict,
    state: dict[str, dict[Any, int]],
    *,
    bag_submission_use: str = "loose_tablets",
) -> None:
    """
    Update per-bag running totals for one row (caller iterates in chronological order).

    bag_submission_use:
      - ``loose_tablets`` — bag-type rows contribute ``loose_tablets`` (submissions list).
      - ``individual_calc`` — bag-type rows contribute ``calculated_total`` (dashboard recent list).
    """
    bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
    bag_key = (sub_dict.get("assigned_po_id"), sub_dict.get("product_name"), bag_identifier)

    individual_calc = sub_dict.get("calculated_total", 0) or 0
    submission_type = sub_dict.get("submission_type", "packaged")
    if submission_type == "packaged":
        normalize_packaged_case_fields_for_ui(sub_dict)

    bag_cumulative_packaged = state["bag_cumulative_packaged"]
    bag_totals_bag = state["bag_totals_bag"]
    bag_totals_machine = state["bag_totals_machine"]
    bag_totals_packaged = state["bag_totals_packaged"]

    if bag_key not in bag_cumulative_packaged:
        bag_cumulative_packaged[bag_key] = 0
    if bag_key not in bag_totals_bag:
        bag_totals_bag[bag_key] = 0
    if bag_key not in bag_totals_machine:
        bag_totals_machine[bag_key] = 0
    if bag_key not in bag_totals_packaged:
        bag_totals_packaged[bag_key] = 0

    if submission_type == "bag":
        if bag_submission_use == "individual_calc":
            bag_totals_bag[bag_key] += individual_calc
        else:
            bag_count_value = sub_dict.get("loose_tablets", 0) or 0
            bag_totals_bag[bag_key] += bag_count_value
    elif submission_type == "machine":
        bag_totals_machine[bag_key] += individual_calc
    elif submission_type == "repack":
        pass
    elif submission_type == "packaged":
        bag_totals_packaged[bag_key] += individual_calc

    if submission_type == "packaged":
        bag_cumulative_packaged[bag_key] += individual_calc

    sub_dict["individual_calc"] = individual_calc
    sub_dict["total_tablets"] = individual_calc
    sub_dict["bag_submission_tablets_total"] = bag_totals_bag[bag_key]
    sub_dict["machine_tablets_total"] = bag_totals_machine[bag_key]
    sub_dict["packaged_tablets_total"] = bag_totals_packaged[bag_key]
    sub_dict["cumulative_bag_tablets"] = bag_cumulative_packaged[bag_key]

    bag_count = sub_dict.get("bag_label_count", 0) or 0
    packaged_cumulative = bag_cumulative_packaged[bag_key]

    if not sub_dict.get("bag_id"):
        sub_dict["count_status"] = "no_bag"
    elif abs(packaged_cumulative - bag_count) <= 5:
        sub_dict["count_status"] = "match"
    elif packaged_cumulative < bag_count:
        sub_dict["count_status"] = "under"
    else:
        sub_dict["count_status"] = "over"

    if submission_type == "repack":
        sub_dict["count_status"] = "repack_po"
        sub_dict["has_discrepancy"] = 0
    else:
        sub_dict["has_discrepancy"] = (
            1 if sub_dict["count_status"] != "match" and bag_count > 0 else 0
        )


def attach_receive_name_for_submission_row(conn, sub_dict: dict) -> None:
    """Set ``receive_name`` from receive / PO / variety-pack deduction context."""
    submission_type = sub_dict.get("submission_type", "packaged")
    stored_receive_name = sub_dict.get("stored_receive_name")
    box_number = sub_dict.get("box_number")
    bag_number = sub_dict.get("bag_number")
    bag_id = sub_dict.get("bag_id")

    receive_name = None
    if bag_id:
        if stored_receive_name:
            if box_number is not None and bag_number is not None:
                receive_name = f"{stored_receive_name}-{box_number}-{bag_number}"
            elif bag_number is not None:
                receive_name = f"{stored_receive_name}-{bag_number}"
            else:
                receive_name = stored_receive_name
        elif sub_dict.get("receive_id") and sub_dict.get("po_number"):
            receive_number_result = conn.execute(
                """
                SELECT COUNT(*) + 1 as receive_number
                FROM receiving r2
                WHERE r2.po_id = ?
                AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                     OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?)
                         AND r2.id < ?))
                """,
                (
                    sub_dict.get("assigned_po_id"),
                    sub_dict.get("receive_id"),
                    sub_dict.get("receive_id"),
                    sub_dict.get("receive_id"),
                ),
            ).fetchone()
            receive_number = receive_number_result["receive_number"] if receive_number_result else 1
            if box_number is not None and bag_number is not None:
                receive_name = f"{sub_dict.get('po_number')}-{receive_number}-{box_number}-{bag_number}"
            elif bag_number is not None:
                receive_name = f"{sub_dict.get('po_number')}-{receive_number}-{bag_number}"
            else:
                receive_name = f"{sub_dict.get('po_number')}-{receive_number}"
    if not receive_name and submission_type == "bottle":
        from_ded = common_receive_label_from_deductions(conn, sub_dict.get("id"))
        if from_ded:
            receive_name = from_ded
        elif sub_dict.get("is_variety_pack") and sub_dict.get("po_number"):
            receive_name = sub_dict["po_number"]

    sub_dict["receive_name"] = receive_name
