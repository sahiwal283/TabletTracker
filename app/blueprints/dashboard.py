"""
/dashboard kept for bookmarks and legacy links — redirects to Reports.
"""

from flask import Blueprint, redirect, url_for

from app.utils.auth_utils import role_required

bp = Blueprint('dashboard', __name__)


@bp.route('/dashboard')
@role_required('dashboard')
def dashboard_view():
    """Former desktop dashboard removed; managers land on Reports."""
    return redirect(url_for('reports.reports_view'), code=302)
