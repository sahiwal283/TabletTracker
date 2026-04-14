
"""Staff workflow UI (CSRF) — bag creation, force-release, reporting."""

from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.services.workflow_finalize import create_workflow_bag_with_card, force_release_card
from app.services.workflow_read import production_day_for_event_ms
from app.services.workflow_txn import run_with_busy_retry
from app.utils.auth_utils import employee_required
from app.utils.db_utils import get_db

LOGGER = logging.getLogger(__name__)

bp = Blueprint("workflow_staff", __name__, url_prefix="/workflow")


@bp.route("/staff/new-bag", methods=["GET", "POST"])
@employee_required
def new_bag():
    """Create workflow bag + assign next idle card (same transaction)."""
    conn = get_db()
    try:
        if request.method == "GET":
            products = conn.execute(
                """
                SELECT pd.id, pd.product_name, tt.tablet_type_name
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE COALESCE(pd.is_variety_pack, 0) = 0
                ORDER BY pd.product_name
                LIMIT 500
                """
            ).fetchall()
            return render_template("workflow_new_bag.html", products=products)

        product_id = request.form.get("product_id", type=int)
        box_number = (request.form.get("box_number") or "").strip() or None
        bag_number = (request.form.get("bag_number") or "").strip() or None
        receipt_number = (request.form.get("receipt_number") or "").strip() or None
        uid = session.get("employee_id")
        if session.get("admin_authenticated"):
            uid = None

        def _run():
            return create_workflow_bag_with_card(
                conn,
                product_id=product_id,
                box_number=box_number,
                bag_number=bag_number,
                receipt_number=receipt_number,
                user_id=uid,
            )

        try:
            bag_id, card_id = run_with_busy_retry(_run, op_name="create_bag")
        except RuntimeError as re:
            if "no_idle_card" in str(re) or "no_idle_card" in repr(re):
                flash("No idle QR cards available. Add cards or finalize existing bags.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "card_claim_failed" in str(re):
                flash("Could not claim card (concurrency). Retry.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            raise
        except sqlite3.OperationalError as oe:
            if "locked" in str(oe).lower():
                flash("Database busy; retry.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            raise

        conn.commit()
        flash(f"Created workflow bag #{bag_id} with card #{card_id}.", "success")
        return redirect(url_for("workflow_staff.new_bag"))
    finally:
        conn.close()


@bp.route("/staff/force-release", methods=["POST"])
@employee_required
def force_release():
    workflow_bag_id = request.form.get("workflow_bag_id", type=int)
    qr_card_id = request.form.get("qr_card_id", type=int)
    reason = (request.form.get("reason") or "admin_release").strip()
    uid = session.get("employee_id")
    if session.get("admin_authenticated"):
        uid = None
    if not workflow_bag_id or not qr_card_id:
        flash("bag id and card id required", "error")
        return redirect(url_for("workflow_staff.new_bag"))

    conn = get_db()

    def _run():
        return force_release_card(
            conn,
            workflow_bag_id=workflow_bag_id,
            qr_card_id=qr_card_id,
            reason=reason,
            user_id=uid,
        )

    try:
        st, body = run_with_busy_retry(_run, op_name="staff_force_release")
    except sqlite3.OperationalError:
        flash("Database busy; retry.", "error")
        return redirect(url_for("workflow_staff.new_bag"))

    if st == "reject":
        flash(body.get("code", "rejected"), "error")
    elif st == "duplicate":
        flash("Card already released (idempotent).", "info")
    else:
        conn.commit()
        flash("Card force-released.", "success")
    conn.close()
    return redirect(url_for("workflow_staff.new_bag"))


@bp.route("/reports/workflow")
@employee_required
def workflow_reports():
    """Event-backed counts by factory-local day (America/New_York)."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT event_type, occurred_at, workflow_bag_id
            FROM workflow_events
            ORDER BY occurred_at DESC
            LIMIT 2000
            """
        ).fetchall()
        by_day = {}
        for r in rows:
            d = production_day_for_event_ms(int(r["occurred_at"]))
            key = d.isoformat()
            by_day.setdefault(key, {})
            by_day[key][r["event_type"]] = by_day[key].get(r["event_type"], 0) + 1
        return render_template("workflow_reports.html", by_day=by_day)
    finally:
        conn.close()
