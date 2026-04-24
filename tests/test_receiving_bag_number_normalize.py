"""Tests for contiguous flavor bag_number assignment on save."""

from app.services.receiving_service import assign_contiguous_flavor_bag_numbers


def test_assign_contiguous_continues_after_po_max():
    boxes = [
        {
            "box_number": 35,
            "bags": [
                {"tablet_type_id": 10, "bag_count": 20000, "bag_number": 5},
                {"tablet_type_id": 10, "bag_count": 20000, "bag_number": 6},
            ],
        },
        {
            "box_number": 36,
            "bags": [
                {"tablet_type_id": 10, "bag_count": 20000, "bag_number": 99},
                {"tablet_type_id": 10, "bag_count": 20000, "bag_number": 100},
            ],
        },
    ]
    assign_contiguous_flavor_bag_numbers(boxes, {10: 4})
    assert boxes[0]["bags"][0]["bag_number"] == 5
    assert boxes[0]["bags"][1]["bag_number"] == 6
    assert boxes[1]["bags"][0]["bag_number"] == 7
    assert boxes[1]["bags"][1]["bag_number"] == 8


def test_assign_contiguous_sorts_boxes_before_numbering():
    boxes = [
        {"box_number": 36, "bags": [{"tablet_type_id": 1, "bag_count": 1, "bag_number": 8}]},
        {"box_number": 35, "bags": [{"tablet_type_id": 1, "bag_count": 1, "bag_number": 5}]},
    ]
    assign_contiguous_flavor_bag_numbers(boxes, {1: 4})
    assert boxes[1]["bags"][0]["bag_number"] == 5
    assert boxes[0]["bags"][0]["bag_number"] == 6


def test_assign_contiguous_no_po_starts_at_one():
    boxes = [
        {"box_number": 1, "bags": [{"tablet_type_id": 7, "bag_count": 100, "bag_number": 50}]},
        {"box_number": 2, "bags": [{"tablet_type_id": 7, "bag_count": 100, "bag_number": 51}]},
    ]
    assign_contiguous_flavor_bag_numbers(boxes, {})
    assert boxes[0]["bags"][0]["bag_number"] == 1
    assert boxes[1]["bags"][0]["bag_number"] == 2
