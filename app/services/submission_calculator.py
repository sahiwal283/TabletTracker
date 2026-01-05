"""
Submission calculation service for computing tablet totals.

This service extracts and centralizes the submission total calculation logic
that was previously duplicated across multiple blueprint files.
"""
from typing import Dict, Optional, Any


def calculate_packaged_submission_total(
    submission: Dict[str, Any],
    packages_per_display: Optional[int] = None,
    tablets_per_package: Optional[int] = None
) -> int:
    """
    Calculate total tablets for a packaged submission.
    
    Formula: (displays_made * packages_per_display * tablets_per_package) +
             (packs_remaining * tablets_per_package) +
             loose_tablets + damaged_tablets
    
    Args:
        submission: Submission dictionary with fields:
            - displays_made (int, optional)
            - packs_remaining (int, optional)
            - loose_tablets (int, optional)
            - damaged_tablets (int, optional)
        packages_per_display: Number of packages per display (from product_details)
        tablets_per_package: Number of tablets per package (from product_details)
    
    Returns:
        Total number of tablets (int)
    """
    displays_made = submission.get('displays_made', 0) or 0
    packs_remaining = submission.get('packs_remaining', 0) or 0
    loose_tablets = submission.get('loose_tablets', 0) or 0
    damaged_tablets = submission.get('damaged_tablets', 0) or 0
    
    packages_per_display = packages_per_display or 0
    tablets_per_package = tablets_per_package or 0
    
    displays_total = displays_made * packages_per_display * tablets_per_package
    packs_total = packs_remaining * tablets_per_package
    
    return displays_total + packs_total + loose_tablets + damaged_tablets


def calculate_bag_submission_total(submission: Dict[str, Any]) -> int:
    """
    Calculate total tablets for a bag count submission.
    
    For bag submissions, the total is simply the loose_tablets count
    (which represents the actual count from the bag count form).
    
    Args:
        submission: Submission dictionary with field:
            - loose_tablets (int, optional)
    
    Returns:
        Total number of tablets (int)
    """
    return submission.get('loose_tablets', 0) or 0


def calculate_machine_submission_total(
    submission: Dict[str, Any],
    tablets_per_package: Optional[int] = None
) -> int:
    """
    Calculate total tablets for a machine count submission.
    
    Priority order:
    1. tablets_pressed_into_cards (if available)
    2. loose_tablets (fallback)
    3. packs_remaining * tablets_per_package (calculated fallback)
    4. 0 (default)
    
    Args:
        submission: Submission dictionary with fields:
            - tablets_pressed_into_cards (int, optional)
            - loose_tablets (int, optional)
            - packs_remaining (int, optional)
        tablets_per_package: Number of tablets per package (for fallback calculation)
    
    Returns:
        Total number of tablets (int)
    """
    # Priority 1: tablets_pressed_into_cards
    tablets_pressed = submission.get('tablets_pressed_into_cards')
    if tablets_pressed is not None:
        return tablets_pressed or 0
    
    # Priority 2: loose_tablets
    loose_tablets = submission.get('loose_tablets')
    if loose_tablets is not None:
        return loose_tablets or 0
    
    # Priority 3: Calculate from packs_remaining
    packs_remaining = submission.get('packs_remaining', 0) or 0
    tablets_per_package = tablets_per_package or 0
    if packs_remaining > 0 and tablets_per_package > 0:
        return packs_remaining * tablets_per_package
    
    # Priority 4: Default to 0
    return 0


def calculate_submission_total(
    submission: Dict[str, Any],
    submission_type: Optional[str] = None,
    packages_per_display: Optional[int] = None,
    tablets_per_package: Optional[int] = None,
    fallback_tablets_per_package: Optional[int] = None
) -> int:
    """
    Calculate total tablets for any submission type.
    
    This is the main entry point that routes to the appropriate
    calculation method based on submission type.
    
    Args:
        submission: Submission dictionary with all relevant fields
        submission_type: Type of submission ('packaged', 'bag', 'machine', or None)
            If None, defaults to 'packaged'
        packages_per_display: Number of packages per display (for packaged type)
        tablets_per_package: Primary tablets per package value
        fallback_tablets_per_package: Fallback tablets per package (used for machine type)
    
    Returns:
        Total number of tablets (int)
    """
    # Default to 'packaged' if not specified
    submission_type = submission_type or submission.get('submission_type', 'packaged')
    
    if submission_type == 'machine':
        # Use fallback if provided, otherwise use primary
        tablets_per_pkg = fallback_tablets_per_package or tablets_per_package
        return calculate_machine_submission_total(submission, tablets_per_pkg)
    elif submission_type == 'bag':
        return calculate_bag_submission_total(submission)
    else:  # 'packaged' or default
        return calculate_packaged_submission_total(
            submission,
            packages_per_display,
            tablets_per_package
        )


def calculate_submission_total_with_fallback(
    submission: Dict[str, Any],
    product_details: Optional[Dict[str, Any]] = None,
    fallback_product_details: Optional[Dict[str, Any]] = None
) -> int:
    """
    Calculate submission total with automatic fallback to alternative product details.
    
    This handles the common pattern where product_details might not be available
    for a submission, so we fall back to tablet_type-based product_details.
    
    Args:
        submission: Submission dictionary
        product_details: Primary product_details dict with:
            - packages_per_display (int, optional)
            - tablets_per_package (int, optional)
        fallback_product_details: Fallback product_details dict (same structure)
    
    Returns:
        Total number of tablets (int)
    """
    submission_type = submission.get('submission_type', 'packaged')
    
    # Extract values with fallback
    packages_per_display = None
    tablets_per_package = None
    fallback_tablets_per_package = None
    
    if product_details:
        packages_per_display = product_details.get('packages_per_display')
        tablets_per_package = product_details.get('tablets_per_package')
    
    if fallback_product_details:
        fallback_tablets_per_package = fallback_product_details.get('tablets_per_package')
    
    return calculate_submission_total(
        submission,
        submission_type,
        packages_per_display,
        tablets_per_package,
        fallback_tablets_per_package
    )

