"""Semantic aliases for overloaded warehouse submission count columns."""

from __future__ import annotations

from typing import Any


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return default
    return max(0, n)


def packaging_total_displays(*, case_count: Any, loose_display_count: Any, displays_per_case: Any) -> int:
    """Return total displays from case/loose packaging fields."""
    cases = _nonnegative_int(case_count)
    loose = _nonnegative_int(loose_display_count)
    dpc = _nonnegative_int(displays_per_case)
    return (cases * dpc) + loose


def _has_stored_case_breakdown(submission: dict[str, Any]) -> bool:
    if submission.get("case_count") is None:
        return False
    cases = _nonnegative_int(submission.get("case_count"))
    loose = _nonnegative_int(submission.get("loose_display_count"))
    displays_made = _nonnegative_int(submission.get("displays_made"))
    return cases > 0 or loose > 0 or displays_made == 0


def add_submission_semantic_aliases(submission: dict[str, Any]) -> None:
    """
    Add explicit business names while preserving legacy DB field names.

    ``warehouse_submissions`` has old generic columns whose meaning depends on
    ``submission_type``. These aliases let templates/API clients stop guessing.
    """
    submission_type = str(submission.get("submission_type") or "packaged").lower()
    displays_made = _nonnegative_int(submission.get("displays_made"))
    packs_remaining = _nonnegative_int(submission.get("packs_remaining"))

    if submission_type == "machine":
        submission["press_count"] = displays_made
        submission["machine_count_label"] = "Presses"
        submission["cards_remaining"] = None
        submission["bottles_remaining"] = None
        return

    if submission_type == "bottle":
        submission["full_displays_made"] = displays_made
        submission["bottles_remaining"] = _nonnegative_int(
            submission.get("bottles_remaining")
            if submission.get("bottles_remaining") is not None
            else packs_remaining
        )
        submission["singles_remaining"] = submission["bottles_remaining"]
        dpc = _nonnegative_int(submission.get("displays_per_case"))
        if _has_stored_case_breakdown(submission):
            submission["total_displays_made"] = packaging_total_displays(
                case_count=submission.get("case_count"),
                loose_display_count=submission.get("loose_display_count"),
                displays_per_case=dpc,
            )
        else:
            submission["total_displays_made"] = displays_made
        return

    if submission_type == "bag":
        submission["bag_count_tablets"] = _nonnegative_int(submission.get("loose_tablets"))
        return

    # Packaged/repack card output.
    submission["cards_remaining"] = packs_remaining
    submission["singles_remaining"] = packs_remaining
    dpc = _nonnegative_int(submission.get("displays_per_case"))
    if _has_stored_case_breakdown(submission):
        submission["total_displays_made"] = packaging_total_displays(
            case_count=submission.get("case_count"),
            loose_display_count=submission.get("loose_display_count"),
            displays_per_case=dpc,
        )
    else:
        submission["total_displays_made"] = displays_made
