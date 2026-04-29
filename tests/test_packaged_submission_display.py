from app.services.packaged_submission_display import normalize_packaged_case_fields_for_ui


def test_normalize_legacy_backfilled_zeros():
    row = {
        "submission_type": "packaged",
        "displays_made": 12,
        "case_count": 0,
        "loose_display_count": 0,
    }
    normalize_packaged_case_fields_for_ui(row)
    assert row["packaged_legacy_displays_only"] is True
    assert row["case_count"] is None
    assert row["loose_display_count"] is None
    assert row["cases_made_total"] is None


def test_normalize_modern_row_unchanged():
    row = {
        "submission_type": "packaged",
        "displays_made": 25,
        "case_count": 2,
        "loose_display_count": 1,
    }
    normalize_packaged_case_fields_for_ui(row)
    assert "packaged_legacy_displays_only" not in row
    assert row["case_count"] == 2
    assert row["loose_display_count"] == 1


def test_normalize_true_zero_displays():
    row = {
        "submission_type": "packaged",
        "displays_made": 0,
        "case_count": 0,
        "loose_display_count": 0,
        "packs_remaining": 10,
    }
    normalize_packaged_case_fields_for_ui(row)
    assert "packaged_legacy_displays_only" not in row
    assert row["case_count"] == 0
    assert row["loose_display_count"] == 0


def test_non_packaged_skipped():
    row = {
        "submission_type": "repack",
        "displays_made": 5,
        "case_count": 0,
        "loose_display_count": 0,
    }
    normalize_packaged_case_fields_for_ui(row)
    assert "packaged_legacy_displays_only" not in row
    assert row["case_count"] == 0
