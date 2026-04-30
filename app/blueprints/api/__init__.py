"""
API routes - all /api/* endpoints (package; routes registered from submodules).
"""

from flask import Blueprint

bp = Blueprint("api", __name__)

# Blister machine: each press produces this many blister units (display: blisters_made = presses × this).
BLISTER_BLISTERS_PER_CUT = 2

from . import (
    context_processors,
    routes_auth_counts,
    routes_po_admin,
    routes_po_zoho_misc,
    routes_submissions,
    template_filters,
)
