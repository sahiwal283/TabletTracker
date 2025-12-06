"""
Business logic calculations for tablet counts and production
"""
from typing import Dict, Optional


def calculate_tablet_totals(
    displays_made: int,
    packs_remaining: int,
    loose_tablets: int,
    damaged_tablets: int,
    packages_per_display: int,
    tablets_per_package: int
) -> Dict[str, int]:
    """
    Calculate total tablets from production submission.
    
    Returns:
        dict with 'good' and 'damaged' tablet counts
    """
    good_tablets = (
        (displays_made * packages_per_display * tablets_per_package) +
        (packs_remaining * tablets_per_package) +
        loose_tablets
    )
    
    return {
        'good': good_tablets,
        'damaged': damaged_tablets,
        'total': good_tablets + damaged_tablets
    }


def calculate_machine_tablets(
    machine_count: int,
    cards_per_turn: int,
    tablets_per_card: int
) -> int:
    """
    Calculate total tablets from machine count.
    
    Formula: machine_count * cards_per_turn * tablets_per_card
    """
    return machine_count * cards_per_turn * tablets_per_card

