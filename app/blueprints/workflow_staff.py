
"""Staff workflow UI (CSRF) — bag creation, force-release, reporting."""

from __future__ import annotations

import logging
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.services.workflow_assign_form import (
    ASSIGN_BAG_RETURN_COMMAND_CENTER,
    build_assign_bag_context,
    load_workflow_products,
    parse_nonnegative_int,
)
from app.services.workflow_bag_lookup import find_unassigned_inventory_bags_for_product
from app.services.workflow_finalize import (
    assign_inventory_bag_to_card,
    assign_variety_pack_run_to_card,
    force_release_card,
)
from app.services.workflow_read import production_day_for_event_ms
from app.services.workflow_txn import run_with_busy_retry
from app.utils.auth_utils import employee_required
from app.utils.db_utils import get_db

LOGGER = logging.getLogger(__name__)

bp = Blueprint("workflow_staff", __name__, url_prefix="/workflow")


def _bag_display_name(conn: sqlite3.Connection, inventory_bag_id: int) -> str:
    """PO-shipment-box-bag display used across receiving/workflow UI."""
    try:
        row = conn.execute(
            """
            SELECT po.po_number, COALESCE(r.shipment_number, 1) AS shipment_number,
                   sb.box_number, b.bag_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE b.id = ?
            """,
            (inventory_bag_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        # Older databases may not have receiving.shipment_number yet.
        row = conn.execute(
            """
            SELECT po.po_number, 1 AS shipment_number, sb.box_number, b.bag_number
            FROM bags b
            JOIN small_boxes sb ON b.small_box_id = sb.id
            JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN purchase_orders po ON r.po_id = po.id
            WHERE b.id = ?
            """,
            (inventory_bag_id,),
        ).fetchone()
    if not row:
        return f"bag-{inventory_bag_id}"
    po_num = (row["po_number"] or f"REC{inventory_bag_id}").strip()
    return f"{po_num}-{int(row['shipment_number'])}-{row['box_number']}-{row['bag_number']}"


def assign_bag_redirect_after_post():
    rt = (request.form.get("return_to") or "").strip()
    if rt == ASSIGN_BAG_RETURN_COMMAND_CENTER:
        return redirect(url_for("admin.workflow_qr_management"))
    return redirect(url_for("workflow_staff.new_bag"))


def _assign_bag_restart_url_from_form():
    rt = (request.form.get("return_to") or "").strip()
    if rt == ASSIGN_BAG_RETURN_COMMAND_CENTER:
        return url_for("admin.workflow_qr_management")
    return url_for("workflow_staff.new_bag")


@bp.route("/staff/new-variety-run", methods=["POST"])
@employee_required
def new_variety_run():
    """Assign a dedicated traveling QR card to a variety-pack run."""
    conn = get_db()
    try:
        product_id = request.form.get("product_id", type=int)
        card_scan_token = (request.form.get("card_scan_token") or "").strip()
        receipt_number = (request.form.get("receipt_number") or "").strip()
        uid = session.get("employee_id")
        if session.get("admin_authenticated"):
            uid = None
        if not product_id:
            flash("Variety product is required.", "error")
            return assign_bag_redirect_after_post()
        if not card_scan_token:
            flash("Scan or enter the variety QR card token before assigning.", "error")
            return assign_bag_redirect_after_post()
        try:
            bag_id, card_id = run_with_busy_retry(
                lambda: assign_variety_pack_run_to_card(
                    conn,
                    product_id=product_id,
                    user_id=uid,
                    card_scan_token=card_scan_token,
                    receipt_number_override=receipt_number,
                ),
                op_name="assign_variety_pack_run_to_card",
            )
            conn.commit()
            flash(f"Assigned variety pack QR card #{card_id} to workflow bag #{bag_id}.", "success")
        except RuntimeError as re:
            err = str(re)
            if "invalid_variety_product" in err:
                flash("Choose a product configured as a variety pack.", "error")
            elif "card_token_not_found" in err:
                flash(f"Card token '{card_scan_token}' was not found. Scan the variety QR again.", "error")
            elif "card_not_idle" in err:
                flash(f"Card token '{card_scan_token}' is already in use. Release/finalize it first.", "error")
            elif "card_token_required" in err:
                flash("A dedicated variety QR card token is required.", "error")
            else:
                LOGGER.warning("new_variety_run runtime error: %s", err)
                flash("Could not assign variety pack QR card. Try again.", "error")
            conn.rollback()
        return assign_bag_redirect_after_post()
    finally:
        conn.close()


@bp.route("/staff/new-bag", methods=["GET", "POST"])
@employee_required
def new_bag():
    """Assign a receiving/shipment bag to a specific scanned/manual QR card token."""
    conn = get_db()
    try:
        if request.method == "GET":
            products = load_workflow_products(conn)
            rt = (request.args.get("return_to") or "").strip()
            if rt != ASSIGN_BAG_RETURN_COMMAND_CENTER:
                rt = ""
            restart = (
                url_for("admin.workflow_qr_management")
                if rt == ASSIGN_BAG_RETURN_COMMAND_CENTER
                else url_for("workflow_staff.new_bag")
            )
            return render_template(
                "workflow_new_bag.html",
                bag_assign=build_assign_bag_context(
                    products=products,
                    return_to=rt,
                    restart_url=restart,
                ),
            )

        product_id = request.form.get("product_id", type=int)
        box_number = parse_nonnegative_int(request.form.get("box_number"))
        bag_number = parse_nonnegative_int(request.form.get("bag_number"))
        card_scan_token = (request.form.get("card_scan_token") or "").strip()
        receipt_number = (request.form.get("receipt_number") or "").strip()
        hand_packed = (request.form.get("hand_packed") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        inventory_bag_id = request.form.get("inventory_bag_id", type=int)
        disambiguate = (request.form.get("disambiguate") or "").strip() == "1"

        uid = session.get("employee_id")
        if session.get("admin_authenticated"):
            uid = None

        if not product_id or box_number is None or bag_number is None:
            flash("Product, box number, and bag number are required.", "error")
            return assign_bag_redirect_after_post()
        if not card_scan_token:
            flash("Scan or enter the bag card token before assigning.", "error")
            return assign_bag_redirect_after_post()
        if not receipt_number:
            flash("Receipt number is required.", "error")
            return assign_bag_redirect_after_post()

        prow = conn.execute(
            """
            SELECT id FROM product_details
            WHERE id = ?
            """,
            (product_id,),
        ).fetchone()
        if not prow:
            flash("Invalid product for workflow assignment.", "error")
            return assign_bag_redirect_after_post()

        matches = find_unassigned_inventory_bags_for_product(
            conn,
            product_id=product_id,
            box_number=box_number,
            bag_number=bag_number,
        )

        if disambiguate and inventory_bag_id is not None:
            valid_ids = {int(m["id"]) for m in matches}
            if inventory_bag_id not in valid_ids:
                flash("That bag is no longer available for assignment. Try again.", "error")
                return assign_bag_redirect_after_post()
        elif not disambiguate:
            if len(matches) == 0:
                flash(
                    "No unassigned bag found for that flavor, box, and bag number "
                    "(check receiving is open, or the bag may already be linked to a workflow).",
                    "error",
                )
                return assign_bag_redirect_after_post()
            if len(matches) > 1:
                products = load_workflow_products(conn)
                return render_template(
                    "workflow_new_bag.html",
                    bag_assign=build_assign_bag_context(
                        products=products,
                        ambiguous_matches=matches,
                        form_product_id=product_id,
                        form_box_number=box_number,
                        form_bag_number=bag_number,
                        form_card_scan_token=card_scan_token,
                        form_receipt_number=receipt_number,
                        form_hand_packed=hand_packed,
                        return_to=(request.form.get("return_to") or "").strip(),
                        restart_url=_assign_bag_restart_url_from_form(),
                    ),
                )
            inventory_bag_id = int(matches[0]["id"])
        else:
            flash("Select which bag to use.", "error")
            return assign_bag_redirect_after_post()

        def _run():
            return assign_inventory_bag_to_card(
                conn,
                inventory_bag_id=inventory_bag_id,
                product_id=product_id,
                user_id=uid,
                card_scan_token=card_scan_token,
                receipt_number_override=receipt_number,
                hand_packed=hand_packed,
            )

        try:
            bag_id, card_id = run_with_busy_retry(_run, op_name="assign_bag_to_card")
        except RuntimeError as re:
            err = str(re)
            if "no_idle_card" in err:
                flash("No idle QR cards available. Add cards or finalize existing bags.", "error")
                return assign_bag_redirect_after_post()
            if "card_token_not_found" in err:
                flash(f"Card token '{card_scan_token}' was not found. Scan the bag card QR again.", "error")
                return assign_bag_redirect_after_post()
            if "card_not_idle" in err:
                flash(
                    f"Card token '{card_scan_token}' is already in use. Release/finalize it first, then retry.",
                    "error",
                )
                return assign_bag_redirect_after_post()
            if "card_claim_failed" in err:
                flash("Could not claim card (concurrency). Retry.", "error")
                return assign_bag_redirect_after_post()
            if "inventory_bag_already_assigned" in err:
                flash(
                    f"Bag {_bag_display_name(conn, inventory_bag_id)} is already linked to a workflow.",
                    "error",
                )
                return assign_bag_redirect_after_post()
            if "inventory_bag_not_found" in err:
                flash(
                    f"Bag {_bag_display_name(conn, inventory_bag_id)} was not found.",
                    "error",
                )
                return assign_bag_redirect_after_post()
            if "inventory_bag_missing_tablet_type" in err:
                flash("That bag has no tablet type; fix receiving data first.", "error")
                return assign_bag_redirect_after_post()
            if "invalid_product" in err:
                flash("Invalid product selection.", "error")
                return assign_bag_redirect_after_post()
            if "product_bag_tablet_type_mismatch" in err:
                flash(
                    "This product is not configured to use that bag’s tablet type. "
                    "Add the flavor under Product Configuration → allowed tablets, or pick the correct product.",
                    "error",
                )
                return assign_bag_redirect_after_post()
            raise
        except sqlite3.OperationalError as oe:
            if "locked" in str(oe).lower():
                flash("Database busy; retry.", "error")
                return assign_bag_redirect_after_post()
            raise

        conn.commit()
        card_row = conn.execute(
            "SELECT scan_token FROM qr_cards WHERE id = ?",
            (card_id,),
        ).fetchone()
        card_token = card_row["scan_token"] if card_row else card_scan_token
        bag_name = _bag_display_name(conn, inventory_bag_id)
        flash(
            f"Assigned bag {bag_name} to QR card {card_token}.",
            "success",
        )
        return assign_bag_redirect_after_post()
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
