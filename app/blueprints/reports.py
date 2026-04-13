"""
HTML route for the dynamic reporting / analytics page.
"""
from flask import Blueprint, render_template

from app.utils.auth_utils import role_required

bp = Blueprint("reports", __name__)


@bp.route("/reports")
@role_required("reports")
def reports_view():
    """Interactive reports dashboard (JSON data loaded via /api/reports/*)."""
    return render_template("reports.html")
