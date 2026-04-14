
"""Staff workflow UI (CSRF) — bag creation, force-release, reporting."""

from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.services.workflow_finalize import assign_inventory_bag_to_card, force_release_card
from app.services.workflow_read import production_day_for_event_ms
from app.services.workflow_txn import run_with_busy_retry
from app.utils.auth_utils import employee_required
from app.utils.db_utils import get_db

LOGGER = logging.getLogger(__name__)

bp = Blueprint("workflow_staff", __name__, url_prefix="/workflow")


@bp.route("/staff/new-bag", methods=["GET", "POST"])
@employee_required
def new_bag():
    """Assign a receiving/shipment bag to the next idle QR card (same transaction)."""
    conn = get_db()
    try:
        if request.method == "GET":
            products = conn.execute(
                """
                SELECT pd.id, pd.product_name, pd.tablet_type_id,
                       pd.category,
                       tt.category AS tablet_category
                FROM product_details pd
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE COALESCE(pd.is_variety_pack, 0) = 0
                AND (pd.is_bottle_product = 0 OR pd.is_bottle_product IS NULL)
                ORDER BY COALESCE(pd.category, tt.category, 'ZZZ'), pd.product_name
                LIMIT 500
                """
            ).fetchall()
            products = [dict(p) for p in products]
            eligible_bags = conn.execute(
                """
                SELECT b.id, b.bag_number, sb.box_number, b.tablet_type_id,
                       tt.tablet_type_name, r.id AS receiving_id, po.po_number, r.received_date
                FROM bags b
                JOIN small_boxes sb ON b.small_box_id = sb.id
                JOIN receiving r ON sb.receiving_id = r.id
                LEFT JOIN purchase_orders po ON r.po_id = po.id
                JOIN tablet_types tt ON b.tablet_type_id = tt.id
                LEFT JOIN workflow_bags wb ON wb.inventory_bag_id = b.id
                WHERE wb.id IS NULL AND b.tablet_type_id IS NOT NULL
                ORDER BY r.received_date DESC, po.po_number, sb.box_number, b.bag_number
                LIMIT 500
                """
            ).fetchall()
            eligible_bags = [dict(r) for r in eligible_bags]
            return render_template(
                "workflow_new_bag.html",
                products=products,
                eligible_bags=eligible_bags,
            )

        inventory_bag_id = request.form.get("inventory_bag_id", type=int)
        product_id = request.form.get("product_id", type=int)
        uid = session.get("employee_id")
        if session.get("admin_authenticated"):
            uid = None

        if not inventory_bag_id or not product_id:
            flash("Shipment bag and product are required.", "error")
            return redirect(url_for("workflow_staff.new_bag"))

        def _run():
            return assign_inventory_bag_to_card(
                conn,
                inventory_bag_id=inventory_bag_id,
                product_id=product_id,
                user_id=uid,
            )

        try:
            bag_id, card_id = run_with_busy_retry(_run, op_name="assign_bag_to_card")
        except RuntimeError as re:
            err = str(re)
            if "no_idle_card" in err:
                flash("No idle QR cards available. Add cards or finalize existing bags.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "card_claim_failed" in err:
                flash("Could not claim card (concurrency). Retry.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "inventory_bag_already_assigned" in err:
                flash("That shipment bag is already linked to a workflow.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "inventory_bag_not_found" in err:
                flash("Shipment bag not found.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "inventory_bag_missing_tablet_type" in err:
                flash("That bag has no tablet type; fix receiving data first.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "invalid_product" in err:
                flash("Invalid product selection.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            if "product_bag_tablet_type_mismatch" in err:
                flash("Product must match the bag’s tablet type (flavor).", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            raise
        except sqlite3.OperationalError as oe:
            if "locked" in str(oe).lower():
                flash("Database busy; retry.", "error")
                return redirect(url_for("workflow_staff.new_bag"))
            raise

        conn.commit()
        flash(
            f"Assigned shipment bag to workflow #{bag_id} and QR card #{card_id}.",
            "success",
        )
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
