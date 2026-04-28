"""
Purchase Orders routes — legacy list UI removed; deep links redirect to Reports.
"""

from flask import Blueprint, redirect, url_for

from app.utils.auth_utils import role_required

bp = Blueprint('purchase_orders', __name__)


@bp.route('/purchase-orders')
@bp.route('/purchase_orders')
@role_required('dashboard')
def purchase_orders_list():
    return redirect(url_for('reports.reports_view'), code=302)
