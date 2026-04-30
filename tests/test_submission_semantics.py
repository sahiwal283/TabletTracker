from app.services.command_center_metrics_inputs import packaging_display_total_from_payload
from app.services.submission_semantics import add_submission_semantic_aliases, packaging_total_displays


def test_packaging_total_displays_uses_loose_not_total_display_count():
    assert packaging_total_displays(case_count=2, loose_display_count=3, displays_per_case=12) == 27


def test_command_center_payload_total_prefers_case_breakdown():
    payload = {"case_count": 2, "display_count": 3, "loose_display_count": 3}
    assert packaging_display_total_from_payload(payload, 12) == 27


def test_submission_aliases_card_and_bottle_singles():
    card = {
        "submission_type": "packaged",
        "displays_made": 27,
        "case_count": 2,
        "loose_display_count": 3,
        "displays_per_case": 12,
        "packs_remaining": 4,
    }
    bottle = {
        "submission_type": "bottle",
        "displays_made": 5,
        "packs_remaining": 2,
    }

    add_submission_semantic_aliases(card)
    add_submission_semantic_aliases(bottle)

    assert card["total_displays_made"] == 27
    assert card["cards_remaining"] == 4
    assert bottle["full_displays_made"] == 5
    assert bottle["bottles_remaining"] == 2


def test_machine_alias_uses_press_count():
    row = {"submission_type": "machine", "displays_made": 17}
    add_submission_semantic_aliases(row)
    assert row["press_count"] == 17
    assert row["machine_count_label"] == "Presses"
