"""
Submissions routes
"""
import io
import sqlite3
import traceback
import csv
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response, current_app, session

from app.services import workflow_constants as WC
from app.services.submission_query_service import apply_resolved_bag_fields
from app.services.submissions_view_service import (
    append_submission_common_filters,
    append_submission_archive_tab_filters,
    append_submission_sort,
)
from app.blueprints.workflow_staff import _bag_display_name
from app.services.workflow_read import display_stage_label, mechanical_bag_facts, progress_summary
from app.services.workflow_txn import is_sqlite_busy_retryable, run_with_busy_retry
from app.services.workflow_warehouse_bridge import delete_synced_warehouse_artifacts_for_workflow_bag
from app.utils.auth_utils import role_required
from app.utils.db_utils import db_read_only, db_transaction


def _format_workflow_created_at_ms(ms) -> str:
    if ms is None:
        return "—"
    try:
        dt = datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError, OSError):
        return str(ms)

bp = Blueprint('submissions', __name__)


def _empty_pagination():
    return {
        "page": 1,
        "per_page": 15,
        "total": 0,
        "total_pages": 0,
        "has_prev": False,
        "has_next": False,
        "prev_page": None,
        "next_page": None,
    }


def _workflow_submissions_page(conn):
    """Paginated workflow_bags list with stage/progress from workflow_read."""
    page = request.args.get("page", 1, type=int) or 1
    page = max(1, page)
    per_page = 15
    wf_status = (request.args.get("wf_status") or "").strip().lower()
    if wf_status not in ("", "active", "finalized"):
        wf_status = ""

    where_clauses = []
    params = []
    if wf_status == "finalized":
        where_clauses.append(
            "EXISTS (SELECT 1 FROM workflow_events we WHERE we.workflow_bag_id = wb.id AND we.event_type = ?)"
        )
        params.append(WC.EVENT_BAG_FINALIZED)
    elif wf_status == "active":
        where_clauses.append(
            "NOT EXISTS (SELECT 1 FROM workflow_events we WHERE we.workflow_bag_id = wb.id AND we.event_type = ?)"
        )
        params.append(WC.EVENT_BAG_FINALIZED)

    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    count_sql = f"SELECT COUNT(*) AS c FROM workflow_bags wb WHERE 1=1{where_sql}"
    total = conn.execute(count_sql, params).fetchone()["c"]

    total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * per_page

    list_sql = f"""
        SELECT wb.id, wb.created_at, wb.product_id, wb.receipt_number,
               wb.inventory_bag_id, pd.product_name
        FROM workflow_bags wb
        LEFT JOIN product_details pd ON wb.product_id = pd.id
        WHERE 1=1
        {where_sql}
        ORDER BY wb.created_at DESC
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(list_sql, params + [per_page, offset]).fetchall()

    workflow_bags = []
    for r in rows:
        d = dict(r)
        bid = d["id"]
        facts = mechanical_bag_facts(conn, bid)
        d["stage_label"] = display_stage_label(facts)
        d["progress_summary"] = progress_summary(facts)
        d["created_at_display"] = _format_workflow_created_at_ms(d.get("created_at"))
        d["is_finalized"] = any(
            e["event_type"] == WC.EVENT_BAG_FINALIZED for e in facts["events"]
        )
        inv_id = d.get("inventory_bag_id")
        if inv_id:
            d["bag_name"] = _bag_display_name(conn, int(inv_id))
        else:
            d["bag_name"] = "—"
        workflow_bags.append(d)

    tp = total_pages
    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": tp,
        "has_prev": page > 1,
        "has_next": page < tp,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < tp else None,
    }

    return {"workflow_bags": workflow_bags, "wf_status": wf_status, "pagination": pagination}


def _workflow_submissions_template_kwargs(workflow_bags, wf_status, pagination):
    return {
        "view": "workflow",
        "submissions": [],
        "receipt_groups": [],
        "workflow_bags": workflow_bags,
        "wf_status": wf_status,
        "pagination": pagination,
        "filter_info": {},
        "unverified_count": 0,
        "tablet_types": [],
        "filter_date_from": None,
        "filter_date_to": None,
        "filter_tablet_type_id": None,
        "filter_submission_type": None,
        "filter_receipt_number": None,
        "sort_by": "created_at",
        "sort_order": "desc",
        "show_archived": False,
        "active_tab": "packaged_machine",
        "archived_count": 0,
    }


def _workflow_bag_label(conn, workflow_bag_id: int) -> str:
    try:
        row = conn.execute(
            """
            SELECT wb.id, po.po_number, COALESCE(r.shipment_number, 1) AS shipment_number,
                   sb.box_number, b.bag_number
            FROM workflow_bags wb
            LEFT JOIN bags b ON b.id = wb.inventory_bag_id
            LEFT JOIN small_boxes sb ON sb.id = b.small_box_id
            LEFT JOIN receiving r ON r.id = sb.receiving_id
            LEFT JOIN purchase_orders po ON po.id = r.po_id
            WHERE wb.id = ?
            """,
            (workflow_bag_id,),
        ).fetchone()
    except sqlite3.OperationalError as oe:
        # Some older production DBs do not have receiving.shipment_number yet.
        if "shipment_number" not in str(oe).lower():
            raise
        row = conn.execute(
            """
            SELECT wb.id, po.po_number, 1 AS shipment_number,
                   sb.box_number, b.bag_number
            FROM workflow_bags wb
            LEFT JOIN bags b ON b.id = wb.inventory_bag_id
            LEFT JOIN small_boxes sb ON sb.id = b.small_box_id
            LEFT JOIN receiving r ON r.id = sb.receiving_id
            LEFT JOIN purchase_orders po ON po.id = r.po_id
            WHERE wb.id = ?
            """,
            (workflow_bag_id,),
        ).fetchone()
    if not row:
        return f"workflow bag #{workflow_bag_id}"
    if row["po_number"] and row["box_number"] is not None and row["bag_number"] is not None:
        return f"{row['po_number']}-{int(row['shipment_number'])}-{row['box_number']}-{row['bag_number']}"
    return f"workflow bag #{workflow_bag_id}"


def _quote_sqlite_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _best_effort_cleanup_workflow_children(conn, workflow_bag_id: int) -> None:
    """
    Remove unknown child rows that reference this bag/events in older/custom DBs.

    This keeps delete usable for testing even when extra tables/constraints exist.
    """
    table_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    table_names = [r["name"] for r in table_rows]
    for table_name in table_names:
        if table_name in {"workflow_bags", "workflow_events"}:
            continue
        try:
            fk_rows = conn.execute(f"PRAGMA foreign_key_list({_quote_sqlite_ident(table_name)})").fetchall()
        except sqlite3.Error:
            continue

        for fk in fk_rows:
            parent = (fk["table"] or "").strip().lower()
            from_col = fk["from"]
            if not from_col:
                continue
            q_table = _quote_sqlite_ident(table_name)
            q_col = _quote_sqlite_ident(from_col)
            if parent == "workflow_bags":
                conn.execute(
                    f"DELETE FROM {q_table} WHERE {q_col} = ?",
                    (workflow_bag_id,),
                )
            elif parent == "workflow_events":
                conn.execute(
                    f"""
                    DELETE FROM {q_table}
                    WHERE {q_col} IN (
                        SELECT id FROM workflow_events WHERE workflow_bag_id = ?
                    )
                    """,
                    (workflow_bag_id,),
                )


@bp.route("/submissions/workflow/<int:workflow_bag_id>/delete", methods=["POST"])
@role_required("dashboard")
def delete_workflow_bag(workflow_bag_id: int):
    """Testing helper: remove one workflow bag + timeline and release any linked card."""
    is_admin = bool(session.get("admin_authenticated"))
    role = (session.get("employee_role") or "").strip().lower()
    if not is_admin and role not in {"admin", "manager"}:
        flash("Only admin/manager can delete workflow bags.", "error")
        return redirect(url_for("submissions.submissions_list", view="workflow"))

    next_view = request.form.get("view") or "workflow"
    next_wf_status = (request.form.get("wf_status") or "").strip().lower()
    next_page = request.form.get("page", type=int)

    try:
        def _run_delete() -> str:
            with db_transaction() as conn:
                row = conn.execute(
                    "SELECT id FROM workflow_bags WHERE id = ?",
                    (workflow_bag_id,),
                ).fetchone()
                if not row:
                    return ""
                bag_label = _workflow_bag_label(conn, workflow_bag_id)
                try:
                    delete_synced_warehouse_artifacts_for_workflow_bag(conn, workflow_bag_id)
                except Exception:
                    # Do not block test cleanup if optional warehouse sync cleanup fails.
                    current_app.logger.exception(
                        "delete_workflow_bag: warehouse artifact cleanup skipped for bag=%s",
                        workflow_bag_id,
                    )
                # If a card still points to this bag, release it to idle.
                conn.execute(
                    """
                    UPDATE qr_cards
                    SET status = ?, assigned_workflow_bag_id = NULL
                    WHERE assigned_workflow_bag_id = ?
                    """,
                    (WC.QR_CARD_STATUS_IDLE, workflow_bag_id),
                )
                conn.execute(
                    "DELETE FROM workflow_events WHERE workflow_bag_id = ?",
                    (workflow_bag_id,),
                )
                _best_effort_cleanup_workflow_children(conn, workflow_bag_id)
                conn.execute(
                    "DELETE FROM workflow_bags WHERE id = ?",
                    (workflow_bag_id,),
                )
                return bag_label

        bag_label = run_with_busy_retry(_run_delete, op_name="delete_workflow_bag")
        if not bag_label:
            flash("Workflow bag not found.", "error")
        else:
            flash(
                f"Deleted workflow bag {bag_label} for testing.",
                "success",
            )
    except sqlite3.OperationalError as oe:
        current_app.logger.error("delete_workflow_bag: %s", oe)
        if is_sqlite_busy_retryable(oe):
            flash("Could not delete workflow bag right now (database busy). Retry once.", "error")
        else:
            current_app.logger.error("delete_workflow_bag (non-busy OperationalError): %r", oe)
            flash("Could not delete workflow bag (database error).", "error")
    except sqlite3.IntegrityError as ie:
        current_app.logger.error("delete_workflow_bag integrity: %s", ie, exc_info=True)
        flash("Could not delete workflow bag (related records still reference it).", "error")
    except Exception as e:
        current_app.logger.error("delete_workflow_bag: %s", e, exc_info=True)
        flash("Could not delete workflow bag.", "error")

    q = {"view": next_view}
    if next_wf_status in {"active", "finalized"}:
        q["wf_status"] = next_wf_status
    if next_page and next_page > 1:
        q["page"] = next_page
    return redirect(url_for("submissions.submissions_list", **q))


def group_by_receipt(submissions, sort_by='created_at', sort_order='desc', filter_submission_type=None):
    """
    Group submissions by receipt_number while maintaining sort order within groups.
    
    Args:
        submissions: List of submission dictionaries
        sort_by: Current sort column
        sort_order: 'asc' or 'desc'
        filter_submission_type: If set, skip grouping
    
    Returns:
        List of submissions grouped by receipt_number
    """
    # Skip grouping if filtering by a single submission type
    if filter_submission_type:
        return submissions
    
    # Group by receipt_number
    groups = {}
    null_receipts = []
    
    for sub in submissions:
        receipt = sub.get('receipt_number')
        if receipt is None or receipt == '':
            null_receipts.append(sub)
        else:
            if receipt not in groups:
                groups[receipt] = []
            groups[receipt].append(sub)
    
    # Sort groups by the newest/most relevant submission in each group
    # For default sort (created_at desc), use newest submission's created_at
    # For other sorts, use the primary sort value from first submission in group
    def get_group_sort_key(receipt_group):
        if sort_by == 'created_at':
            # Use newest submission's created_at (max for desc, min for asc)
            if sort_order == 'desc':
                return max(sub.get('created_at', '') for sub in receipt_group)
            else:
                return min(sub.get('created_at', '') for sub in receipt_group)
        elif sort_by == 'receipt_number':
            # Sort numerically by receipt_number (e.g., "2786-13" should come after "2786-9")
            receipt = receipt_group[0].get('receipt_number', '')
            if not receipt or '-' not in receipt:
                return (999999, 999999)  # Put invalid receipts at end
            try:
                parts = receipt.split('-', 1)
                return (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                return (999999, 999999)  # Put invalid receipts at end
        elif sort_by == 'total':
            # Use calculated_total/individual_calc
            if sort_order == 'desc':
                return max(sub.get('individual_calc', 0) or sub.get('calculated_total', 0) or 0 for sub in receipt_group)
            else:
                return min(sub.get('individual_calc', 0) or sub.get('calculated_total', 0) or 0 for sub in receipt_group)
        else:
            # Use the sort value from first submission (already sorted)
            # For string fields, get the first one in sort order
            if sort_order == 'desc':
                # For desc, we want the "highest" value (last alphabetically for strings)
                values = [sub.get(sort_by, '') for sub in receipt_group if sub.get(sort_by)]
                return max(values) if values else ''
            else:
                # For asc, we want the "lowest" value (first alphabetically for strings)
                values = [sub.get(sort_by, '') for sub in receipt_group if sub.get(sort_by)]
                return min(values) if values else ''
    
    # Sort groups
    sorted_groups = sorted(groups.items(), 
                          key=lambda x: get_group_sort_key(x[1]),
                          reverse=(sort_order == 'desc'))
    
    # Flatten groups back into list
    result = []
    for receipt, group in sorted_groups:
        result.extend(group)
    
    # Handle NULL receipts - merge them properly based on sort order instead of appending at end
    # This ensures bottle/variety pack submissions appear in correct chronological position
    if null_receipts:
        if sort_by == 'created_at':
            # Merge null_receipts with result based on created_at
            all_submissions = result + null_receipts
            all_submissions.sort(key=lambda x: x.get('created_at', ''), reverse=(sort_order == 'desc'))
            return all_submissions
        else:
            # For other sort types, append null receipts at end (existing behavior)
            result.extend(null_receipts)
    
    return result


def _created_at_sort_timestamp(val) -> float:
    """
    Parse a naive UTC-ish timestamp string (or datetime) for ordering.
    Missing/invalid values return ``-inf`` so they sort last when using descending order.
    """
    if val is None:
        return float("-inf")
    if isinstance(val, datetime):
        try:
            return val.replace(tzinfo=timezone.utc).timestamp()
        except (OSError, ValueError, OverflowError):
            pass
    s = str(val).strip()
    if not s:
        return float("-inf")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:26], fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return float("-inf")


def _submission_calendar_date_end_ts(sub: dict) -> float:
    """
    Business calendar day from submission_date / filter_date (date-only), end-of-day UTC.
    Catches cases where submission_date reflects \"today\" while created_at lags for some paths.
    """
    fd = sub.get("submission_date") or sub.get("filter_date")
    if fd is None:
        return float("-inf")
    if hasattr(fd, "strftime"):
        sfd = fd.strftime("%Y-%m-%d")[:10]
    else:
        sfd = str(fd).strip()[:10]
    if len(sfd) < 10:
        return float("-inf")
    try:
        return (
            datetime.strptime(sfd + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return float("-inf")


def _row_latest_activity_ts(s: dict) -> float:
    """Latest instant associated with this submission row (for receipt-group ordering)."""
    return max(
        _created_at_sort_timestamp(s.get("created_at")),
        _created_at_sort_timestamp(s.get("bag_end_time")),
        _created_at_sort_timestamp(s.get("bag_start_time")),
        _submission_calendar_date_end_ts(s),
    )


def _aggregate_bag_time_sort_value(raw_ts, reverse: bool) -> float:
    """
    Single scalar for sorting by bag start/end on the parent row.
    Repeating groups with *no* aggregated time sort **last** for both asc and desc.
    """
    t = _created_at_sort_timestamp(raw_ts) if raw_ts else float("-inf")
    if t == float("-inf"):
        # Nulls last: smallest in desc (sink), largest in asc (sink)
        return float("-inf") if reverse else float("inf")
    return t


def _pick_parent_bag_submission(children):
    """Prefer a row with receive_name (highest id wins); else max id."""
    with_name = [s for s in children if s.get("receive_name")]
    if with_name:
        return max(with_name, key=lambda s: (s.get("id") or 0))
    return max(children, key=lambda s: (s.get("id") or 0))


def build_receipt_groups(submissions_processed):
    """
    One group per distinct receipt_number; each submission without a receipt is its own group.
    Returns list of dicts: group_key, receipt_number, children, receipt_total, bag_start_time,
    bag_end_time, product_label, parent_bag_sub (for Bag column on parent row).
    """
    groups_map = {}
    order = []

    for sub in submissions_processed:
        r = sub.get("receipt_number")
        if r is None or r == "":
            key = ("__null__", sub.get("id"))
        else:
            key = ("receipt", r)
        if key not in groups_map:
            groups_map[key] = []
            order.append(key)
        groups_map[key].append(sub)

    out = []
    for key in order:
        ch = groups_map[key]
        ch = sorted(ch, key=lambda s: (s.get("created_at") or "", s.get("id") or 0))

        receipt_total = sum((s.get("individual_calc") or 0) or 0 for s in ch)

        bag_starts = [s.get("bag_start_time") for s in ch if s.get("bag_start_time")]
        bag_ends = [s.get("bag_end_time") for s in ch if s.get("bag_end_time")]
        bag_start_min = min(bag_starts) if bag_starts else None
        bag_end_max = max(bag_ends) if bag_ends else None

        names = sorted({s.get("product_name") for s in ch if s.get("product_name")})
        if len(names) == 0:
            product_label = ""
        elif len(names) == 1:
            product_label = names[0]
        else:
            product_label = f"{names[0]} (+{len(names) - 1} more)"

        rid = ch[0].get("receipt_number") if key[0] == "receipt" else None
        if rid:
            gk = f"rec:{rid}"
        else:
            gk = f"null:{ch[0].get('id')}"

        parent_bag = _pick_parent_bag_submission(ch)

        # Order parent rows by latest activity in the receipt (any line; max over created/bag times/submission date).
        latest_ts = float("-inf")
        for s in ch:
            latest_ts = max(latest_ts, _row_latest_activity_ts(s))
        max_child_id = max((s.get("id") or 0) for s in ch) if ch else 0
        latest_submission_sort_key = (latest_ts, max_child_id)

        out.append(
            {
                "group_key": gk,
                "receipt_number": rid or "",
                "children": ch,
                "receipt_total": receipt_total,
                "bag_start_time": bag_start_min,
                "bag_end_time": bag_end_max,
                "product_label": product_label,
                "parent_bag_sub": parent_bag,
                "latest_submission_sort_key": latest_submission_sort_key,
            }
        )
    return out


def sort_receipt_groups(groups, sort_by, sort_order):
    """
    Sort aggregated receipt groups (warehouse list).

    ``sort_by=created_at`` (Recent) orders receipts by the latest **activity** among
    child rows: max of ``created_at``, ``bag_start_time``, ``bag_end_time``, and end of
    ``submission_date`` / ``filter_date`` calendar day.

    ``sort_by=bag_end`` / ``bag_start`` use aggregated bag times; receipts with no time
    sort last (fixed: previously missing times could incorrectly rank first when sort_desc).
    """
    sort_by = (sort_by or "created_at").strip()
    sort_order = (sort_order or "desc").strip().lower()
    reverse = sort_order == "desc"

    def receipt_tuple(receipt_str):
        if not receipt_str or "-" not in receipt_str:
            return (999999, 999999)
        try:
            parts = str(receipt_str).split("-", 1)
            return (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return (999999, 999999)

    def sort_key(g):
        ch = g["children"]
        if sort_by == "receipt_number":
            return receipt_tuple(g.get("receipt_number"))
        if sort_by == "total":
            return g["receipt_total"]
        if sort_by == "product_name":
            return g.get("product_label") or ""
        if sort_by == "employee_name":
            vals = [s.get("employee_name") or "" for s in ch]
            if not vals:
                return ""
            return max(vals) if reverse else min(vals)
        if sort_by == "bag_start":
            return _aggregate_bag_time_sort_value(g.get("bag_start_time"), reverse)
        if sort_by == "bag_end":
            return _aggregate_bag_time_sort_value(g.get("bag_end_time"), reverse)
        if sort_by == "created_at":
            return g.get("latest_submission_sort_key") or (float("-inf"), 0)
        # Fallback: same as created_at — latest submission time in receipt
        return g.get("latest_submission_sort_key") or (float("-inf"), 0)

    if sort_by == "receipt_number":
        return sorted(groups, key=lambda g: receipt_tuple(g.get("receipt_number")), reverse=reverse)
    if sort_by in ("bag_start", "bag_end", "created_at"):
        return sorted(groups, key=sort_key, reverse=reverse)

    return sorted(groups, key=sort_key, reverse=reverse)


@bp.route('/submissions')
@role_required('dashboard')
def submissions_list():
    """Full submissions page: warehouse submissions or QR workflow bags."""
    view = (request.args.get('view') or 'warehouse').strip().lower()
    if view not in ('warehouse', 'workflow'):
        view = 'warehouse'

    if view == 'workflow':
        try:
            with db_read_only() as conn:
                try:
                    conn.execute("SELECT 1 FROM workflow_bags LIMIT 1").fetchone()
                except sqlite3.OperationalError:
                    flash(
                        "QR workflow tables are not available in this database.",
                        "warning",
                    )
                    kwargs = _workflow_submissions_template_kwargs(
                        [], "", _empty_pagination()
                    )
                    return render_template("submissions.html", **kwargs)

                w = _workflow_submissions_page(conn)
                kwargs = _workflow_submissions_template_kwargs(
                    w["workflow_bags"], w["wf_status"], w["pagination"]
                )
                return render_template("submissions.html", **kwargs)
        except Exception as e:
            current_app.logger.error("Error in workflow submissions list: %s", e)
            traceback.print_exc()
            flash(
                "An error occurred while loading workflow submissions. Please try again.",
                "error",
            )
            kwargs = _workflow_submissions_template_kwargs(
                [], "", _empty_pagination()
            )
            return render_template("submissions.html", **kwargs)

    try:
        with db_read_only() as conn:
            # Get filter parameters from query string
            filter_po_id = request.args.get('po_id', type=int)
            filter_item_id = request.args.get('item_id', type=str)
            filter_date_from = request.args.get('date_from', type=str)
            filter_date_to = request.args.get('date_to', type=str)
            filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
            filter_submission_type = request.args.get('submission_type', type=str)
            filter_receipt_number = request.args.get('receipt_number', type=str)
            
            # Get archive and tab parameters
            show_archived = request.args.get('show_archived', 'false', type=str).lower() == 'true'
            active_tab = request.args.get('tab', 'packaged_machine', type=str)
            
            # Get sort parameters
            sort_by = request.args.get('sort_by', 'created_at')  # Default sort by created_at
            sort_order = request.args.get('sort_order', 'desc')  # Default descending
            
            # Build query with optional filters
            # Use stored receive_name from receiving table
            query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed, po.id as po_id_for_filter, po.zoho_po_id,
                   m.machine_name AS machine_display_name,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(pd.tablets_per_package, (
                       SELECT pd2.tablets_per_package 
                       FROM product_details pd2
                       JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                       WHERE tt2.inventory_item_id = ws.inventory_item_id
                       LIMIT 1
                   )) as tablets_per_package_final,
                   tt.inventory_item_id, tt.id as tablet_type_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   COALESCE(ws.needs_review, 0) as needs_review,
                   ws.admin_notes,
                   COALESCE(ws.submission_type, 'packaged') as submission_type,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   COALESCE(b.bag_label_count, ws.bag_label_count, 0) as bag_label_count,
                   b.bag_label_count as receive_bag_count,
                   ws.bag_id,
                   r.id as receive_id,
                   r.received_date,
                   r.receive_name as stored_receive_name,
                   COALESCE(sb.box_number, ws.box_number) AS resolved_box_number,
                   COALESCE(b.bag_number, ws.bag_number) AS resolved_bag_number,
                   CASE COALESCE(ws.submission_type, 'packaged')
                       WHEN 'machine' THEN COALESCE(
                           ws.tablets_pressed_into_cards,
                           ws.loose_tablets,
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)),
                           0
                       )
                       WHEN 'bottle' THEN COALESCE(
                           (SELECT SUM(sbd.tablets_deducted) FROM submission_bag_deductions sbd WHERE sbd.submission_id = ws.id),
                           COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
                       )
                       WHEN 'repack' THEN (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) +
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0))
                       )
                       ELSE (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) +
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) + 
                       ws.loose_tablets
                       )
                   END as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            LEFT JOIN bags b ON ws.bag_id = b.id
            LEFT JOIN small_boxes sb ON b.small_box_id = sb.id
            LEFT JOIN receiving r ON sb.receiving_id = r.id
            LEFT JOIN machines m ON ws.machine_id = m.id
            WHERE 1=1
            '''
            
            params = []
            
            query, params = append_submission_common_filters(
                query,
                params,
                {
                    'po_id': filter_po_id,
                    'item_id': filter_item_id,
                    'date_from': filter_date_from,
                    'date_to': filter_date_to,
                    'tablet_type_id': filter_tablet_type_id,
                    'submission_type': filter_submission_type,
                    'receipt_number': filter_receipt_number,
                },
            )
            query = append_submission_archive_tab_filters(query, show_archived, active_tab)
            
            # Get submissions ordered by created_at ASC for running total calculation
            # Always use created_at ASC for running totals regardless of user's sort preference
            query_asc = query + ' ORDER BY ws.created_at ASC'
            submissions_raw_asc = conn.execute(query_asc, params).fetchall()
            
            # Calculate running totals by bag PER PO (each PO has its own physical bags)
            # Separate running totals for each submission type
            # Process in chronological order (oldest first) for correct running totals
            bag_running_totals = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (all types)
            bag_running_totals_bag = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (bag type only)
            bag_running_totals_machine = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (machine type only)
            bag_running_totals_packaged = {}  # Key: (po_id, product_name, "box/bag"), Value: running_total (packaged type only)
            submissions_dict = {}  # Store by submission ID for later lookup
            
            # First pass: Calculate running totals in chronological order (oldest first)
            for sub in submissions_raw_asc:
                sub_dict = dict(sub)
                apply_resolved_bag_fields(sub_dict)
                # Create bag identifier from box_number/bag_number
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                # Key includes PO ID so each PO tracks its own bag totals independently
                bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
                
                # Individual calculation for this submission
                individual_calc = sub_dict.get('calculated_total', 0) or 0
                submission_type = sub_dict.get('submission_type', 'packaged')
                
                # Initialize running totals for this bag if not exists
                if bag_key not in bag_running_totals:
                    bag_running_totals[bag_key] = 0
                if bag_key not in bag_running_totals_bag:
                    bag_running_totals_bag[bag_key] = 0
                if bag_key not in bag_running_totals_machine:
                    bag_running_totals_machine[bag_key] = 0
                if bag_key not in bag_running_totals_packaged:
                    bag_running_totals_packaged[bag_key] = 0
                
                # Update appropriate running total based on submission type
                if submission_type == 'bag':
                    # For bag count submissions, use loose_tablets (the actual count from form)
                    bag_count_value = sub_dict.get('loose_tablets', 0) or 0
                    bag_running_totals_bag[bag_key] += bag_count_value
                elif submission_type == 'machine':
                    bag_running_totals_machine[bag_key] += individual_calc
                elif submission_type == 'repack':
                    pass
                elif submission_type == 'packaged':
                    bag_running_totals_packaged[bag_key] += individual_calc
                
                # Update total running total (only packaged counts - machine counts are consumed, not in bag)
                # Bag counts are also separate inventory counts, not added to total
                if submission_type == 'packaged':
                    bag_running_totals[bag_key] += individual_calc
                
                # Add running total and comparison fields
                sub_dict['individual_calc'] = individual_calc
                sub_dict['total_tablets'] = individual_calc  # Set total_tablets for frontend compatibility
                sub_dict['bag_running_total'] = bag_running_totals_bag[bag_key]
                sub_dict['machine_running_total'] = bag_running_totals_machine[bag_key]
                sub_dict['packaged_running_total'] = bag_running_totals_packaged[bag_key]
                sub_dict['running_total'] = bag_running_totals[bag_key]
                
                # Compare running total to bag label count
                bag_count = sub_dict.get('bag_label_count', 0) or 0
                running_total = bag_running_totals[bag_key]
                
                # Determine status - check if bag_id is NULL, not just bag_label_count
                # A bag can exist with label_count=0, but if bag_id is NULL, there's no bag assigned
                if not sub_dict.get('bag_id'):
                    sub_dict['count_status'] = 'no_bag'
                elif abs(running_total - bag_count) <= 5:  # Allow 5 tablet tolerance
                    sub_dict['count_status'] = 'match'
                elif running_total < bag_count:
                    sub_dict['count_status'] = 'under'
                else:
                    sub_dict['count_status'] = 'over'
                
                if submission_type == 'repack':
                    sub_dict['count_status'] = 'repack_po'
                    sub_dict['has_discrepancy'] = 0
                else:
                    sub_dict['has_discrepancy'] = 1 if sub_dict['count_status'] != 'match' and bag_count > 0 else 0
                
                # Build receive name using stored receive_name from database
                # Format: PO-receive-box-bag (e.g., PO-00164-1-1-2) or PO-receive-bag for flavor-based
                # If bag_id exists, we should always be able to build a receive_name
                receive_name = None
                stored_receive_name = sub_dict.get('stored_receive_name')
                box_number = sub_dict.get('box_number')
                bag_number = sub_dict.get('bag_number')
                bag_id = sub_dict.get('bag_id')
                
                # Only build receive_name if bag_id exists (submission is assigned to a bag)
                if bag_id:
                    if stored_receive_name:
                        # Use stored receive_name and append box-bag if available
                        if box_number is not None and bag_number is not None:
                            receive_name = f"{stored_receive_name}-{box_number}-{bag_number}"
                        elif bag_number is not None:
                            # Flavor-based: no box number, just append bag
                            receive_name = f"{stored_receive_name}-{bag_number}"
                        else:
                            # Just use stored receive_name
                            receive_name = stored_receive_name
                    elif sub_dict.get('receive_id') and sub_dict.get('po_number'):
                        # Fallback for legacy records: calculate receive_number dynamically
                        # This should only happen if receive_name wasn't backfilled
                        receive_number_result = conn.execute('''
                            SELECT COUNT(*) + 1 as receive_number
                            FROM receiving r2
                            WHERE r2.po_id = ?
                            AND (r2.received_date < (SELECT received_date FROM receiving WHERE id = ?)
                                 OR (r2.received_date = (SELECT received_date FROM receiving WHERE id = ?) 
                                     AND r2.id < ?))
                        ''', (sub_dict.get('assigned_po_id'), sub_dict.get('receive_id'), 
                              sub_dict.get('receive_id'), sub_dict.get('receive_id'))).fetchone()
                        receive_number = receive_number_result['receive_number'] if receive_number_result else 1
                        if box_number is not None and bag_number is not None:
                            receive_name = f"{sub_dict.get('po_number')}-{receive_number}-{box_number}-{bag_number}"
                        elif bag_number is not None:
                            # Flavor-based: no box number
                            receive_name = f"{sub_dict.get('po_number')}-{receive_number}-{bag_number}"
                        else:
                            receive_name = f"{sub_dict.get('po_number')}-{receive_number}"
                
                sub_dict['receive_name'] = receive_name
                
                # Store in dict by submission ID for lookup
                submissions_dict[sub_dict.get('id')] = sub_dict
            
            # Second pass: Get submissions in display order (based on user's sort preference) and apply pre-calculated running totals
            query = append_submission_sort(query, sort_by, sort_order)
            
            submissions_raw = conn.execute(query, params).fetchall()
            submissions_processed = []
            
            for sub in submissions_raw:
                sub_dict = dict(sub)
                apply_resolved_bag_fields(sub_dict)
                sub_id = sub_dict.get('id')
                # Get the pre-calculated running totals from the first pass
                if sub_id in submissions_dict:
                    pre_calculated = submissions_dict[sub_id]
                    sub_dict['bag_running_total'] = pre_calculated.get('bag_running_total', 0)
                    sub_dict['machine_running_total'] = pre_calculated.get('machine_running_total', 0)
                    sub_dict['packaged_running_total'] = pre_calculated.get('packaged_running_total', 0)
                    sub_dict['running_total'] = pre_calculated.get('running_total', 0)
                    sub_dict['count_status'] = pre_calculated.get('count_status', 'no_bag')
                    sub_dict['has_discrepancy'] = pre_calculated.get('has_discrepancy', 0)
                    sub_dict['receive_name'] = pre_calculated.get('receive_name')
                
                # Individual calculation for display
                individual_calc = sub_dict.get('calculated_total', 0) or 0
                sub_dict['individual_calc'] = individual_calc
                sub_dict['total_tablets'] = individual_calc  # Set total_tablets for frontend compatibility
                
                submissions_processed.append(sub_dict)
            
            receipt_groups_all = sort_receipt_groups(
                build_receipt_groups(submissions_processed), sort_by, sort_order
            )

            # Pagination (one row per receipt group)
            page = request.args.get('page', 1, type=int)
            per_page = 15
            total_groups = len(receipt_groups_all)
            if total_groups == 0:
                total_pages = 0
                page = 1
                receipt_groups = []
            else:
                total_pages = (total_groups + per_page - 1) // per_page
                if page > total_pages:
                    page = total_pages
                if page < 1:
                    page = 1
                start_idx = (page - 1) * per_page
                end_idx = start_idx + per_page
                receipt_groups = receipt_groups_all[start_idx:end_idx]
            
            # Count unverified submissions (respecting current filters)
            unverified_query = '''
                SELECT COUNT(*) as count
                FROM warehouse_submissions ws
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                LEFT JOIN product_details pd ON ws.product_name = pd.product_name
                LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
                WHERE COALESCE(ws.po_assignment_verified, 0) = 0
            '''
            unverified_params = []
            if filter_po_id:
                unverified_query += ' AND ws.assigned_po_id = ?'
                unverified_params.append(filter_po_id)
            if filter_item_id:
                unverified_query += ' AND tt.inventory_item_id = ?'
                unverified_params.append(filter_item_id)
            if filter_date_from:
                unverified_query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) >= ?'
                unverified_params.append(filter_date_from)
            if filter_date_to:
                unverified_query += ' AND COALESCE(ws.submission_date, DATE(ws.created_at)) <= ?'
                unverified_params.append(filter_date_to)
            if filter_tablet_type_id:
                unverified_query += ' AND tt.id = ?'
                unverified_params.append(filter_tablet_type_id)
            if filter_submission_type:
                unverified_query += ' AND COALESCE(ws.submission_type, \'packaged\') = ?'
                unverified_params.append(filter_submission_type)
            # Apply archive filter to unverified count
            if not show_archived:
                unverified_query += ' AND (po.closed IS NULL OR po.closed = FALSE)'
            else:
                unverified_query += ' AND po.closed = TRUE'
            # Apply tab filter to unverified count
            if active_tab == 'packaged_machine':
                unverified_query += ' AND COALESCE(ws.submission_type, \'packaged\') IN (\'packaged\', \'machine\', \'repack\')'
            elif active_tab == 'bottles':
                unverified_query += ' AND COALESCE(ws.submission_type, \'packaged\') = \'bottle\''
            elif active_tab == 'bag':
                unverified_query += ' AND COALESCE(ws.submission_type, \'packaged\') = \'bag\''
            
            unverified_count = conn.execute(unverified_query, unverified_params).fetchone()['count']
            
            # Pagination info
            pagination = {
                'page': page,
                'per_page': per_page,
                'total': total_groups,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
                'prev_page': page - 1 if page > 1 else None,
                'next_page': page + 1 if page < total_pages else None
            }
            
            # Get filter info for display
            filter_info = {}
            if filter_po_id:
                po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
                if po_info:
                    filter_info['po_number'] = po_info['po_number']
                    filter_info['po_id'] = filter_po_id
            
            if filter_item_id:
                item_info = conn.execute('SELECT line_item_name FROM po_lines WHERE inventory_item_id = ? LIMIT 1', (filter_item_id,)).fetchone()
                if item_info:
                    filter_info['item_name'] = item_info['line_item_name']
                    filter_info['item_id'] = filter_item_id
            
            if filter_date_from:
                filter_info['date_from'] = filter_date_from
            if filter_date_to:
                filter_info['date_to'] = filter_date_to
            if filter_tablet_type_id:
                tablet_type_info = conn.execute('SELECT tablet_type_name FROM tablet_types WHERE id = ?', (filter_tablet_type_id,)).fetchone()
                if tablet_type_info:
                    filter_info['tablet_type_name'] = tablet_type_info['tablet_type_name']
                    filter_info['tablet_type_id'] = filter_tablet_type_id
            
            if filter_submission_type:
                filter_info['submission_type'] = filter_submission_type
            
            if filter_receipt_number:
                filter_info['receipt_number'] = filter_receipt_number
            
            # Get all tablet types for the filter dropdown
            tablet_types = conn.execute('SELECT id, tablet_type_name FROM tablet_types ORDER BY tablet_type_name').fetchall()
            
            # Count archived submissions for display
            archived_count_query = '''
                SELECT COUNT(*) as count
                FROM warehouse_submissions ws
                LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
                WHERE po.closed = TRUE
            '''
            archived_count = conn.execute(archived_count_query).fetchone()['count']
            
            return render_template(
                'submissions.html',
                view='warehouse',
                submissions=[],
                receipt_groups=receipt_groups,
                pagination=pagination,
                filter_info=filter_info,
                unverified_count=unverified_count,
                tablet_types=tablet_types,
                filter_date_from=filter_date_from,
                filter_date_to=filter_date_to,
                filter_tablet_type_id=filter_tablet_type_id,
                filter_submission_type=filter_submission_type,
                filter_receipt_number=filter_receipt_number,
                sort_by=sort_by,
                sort_order=sort_order,
                show_archived=show_archived,
                active_tab=active_tab,
                archived_count=archived_count,
                workflow_bags=[],
                wf_status='',
            )
    except Exception as e:
        current_app.logger.error(f"Error in all_submissions: {e}")
        traceback.print_exc()
        flash('An error occurred while loading submissions. Please try again.', 'error')
        return render_template(
            'submissions.html',
            view='warehouse',
            submissions=[],
            receipt_groups=[],
            workflow_bags=[],
            wf_status='',
            pagination={'page': 1, 'per_page': 15, 'total': 0, 'total_pages': 0, 'has_prev': False, 'has_next': False},
            filter_info={},
            unverified_count=0,
        )

@bp.route('/submissions/export')
@role_required('dashboard')
def export_submissions_csv():
    """Export submissions to CSV with all active filters applied"""
    try:
        with db_read_only() as conn:
            # Get filter parameters from query string (same as all_submissions)
            filter_po_id = request.args.get('po_id', type=int)
            filter_item_id = request.args.get('item_id', type=str)
            filter_date_from = request.args.get('date_from', type=str)
            filter_date_to = request.args.get('date_to', type=str)
            filter_tablet_type_id = request.args.get('tablet_type_id', type=int)
            filter_submission_type = request.args.get('submission_type', type=str)
            filter_receipt_number = request.args.get('receipt_number', type=str)
            
            # Get archive and tab parameters
            show_archived = request.args.get('show_archived', 'false', type=str).lower() == 'true'
            active_tab = request.args.get('tab', 'packaged_machine', type=str)
            
            # Get sort parameters
            sort_by = request.args.get('sort_by', 'created_at')
            sort_order = request.args.get('sort_order', 'asc')  # Default ASC for CSV export
            
            # Build query with optional filters (same logic as all_submissions)
            query = '''
            SELECT ws.*, po.po_number, po.closed as po_closed,
                   m.machine_name AS machine_display_name,
                   pd.packages_per_display, pd.tablets_per_package,
                   COALESCE(pd.tablets_per_package, (
                       SELECT pd2.tablets_per_package 
                       FROM product_details pd2
                       JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                       WHERE tt2.inventory_item_id = ws.inventory_item_id
                       LIMIT 1
                   )) as tablets_per_package_final,
                   tt.inventory_item_id, tt.tablet_type_name,
                   COALESCE(ws.po_assignment_verified, 0) as po_verified,
                   ws.admin_notes,
                   COALESCE(ws.submission_date, DATE(ws.created_at)) as filter_date,
                   CASE COALESCE(ws.submission_type, 'packaged')
                       WHEN 'machine' THEN COALESCE(
                           ws.tablets_pressed_into_cards,
                           ws.loose_tablets,
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)),
                           0
                       )
                       WHEN 'bottle' THEN COALESCE(
                           (SELECT SUM(sbd.tablets_deducted) FROM submission_bag_deductions sbd WHERE sbd.submission_id = ws.id),
                           COALESCE(ws.bottles_made, 0) * COALESCE(pd.tablets_per_bottle, 0)
                       )
                       WHEN 'repack' THEN (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) +
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0))
                       )
                       ELSE (
                           (ws.displays_made * COALESCE(pd.packages_per_display, 0) * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) +
                           (ws.packs_remaining * COALESCE(pd.tablets_per_package, (
                               SELECT pd2.tablets_per_package 
                               FROM product_details pd2
                               JOIN tablet_types tt2 ON pd2.tablet_type_id = tt2.id
                               WHERE tt2.inventory_item_id = ws.inventory_item_id
                               LIMIT 1
                           ), 0)) + 
                       ws.loose_tablets
                       )
                   END as calculated_total
            FROM warehouse_submissions ws
            LEFT JOIN purchase_orders po ON ws.assigned_po_id = po.id
            LEFT JOIN product_details pd ON ws.product_name = pd.product_name
            LEFT JOIN tablet_types tt ON pd.tablet_type_id = tt.id
            LEFT JOIN machines m ON ws.machine_id = m.id
            WHERE 1=1
            '''
            
            params = []
            
            query, params = append_submission_common_filters(
                query,
                params,
                {
                    'po_id': filter_po_id,
                    'item_id': filter_item_id,
                    'date_from': filter_date_from,
                    'date_to': filter_date_to,
                    'tablet_type_id': filter_tablet_type_id,
                    'submission_type': filter_submission_type,
                    'receipt_number': filter_receipt_number,
                },
            )
            query = append_submission_archive_tab_filters(query, show_archived, active_tab)
            query = append_submission_sort(query, sort_by, sort_order)
            
            submissions_raw = conn.execute(query, params).fetchall()
            
            # Calculate running totals by bag PER PO (same logic as all_submissions)
            bag_running_totals = {}
            submissions_processed = []
            
            for sub in submissions_raw:
                sub_dict = dict(sub)
                bag_identifier = f"{sub_dict.get('box_number', '')}/{sub_dict.get('bag_number', '')}"
                bag_key = (sub_dict.get('assigned_po_id'), sub_dict.get('product_name'), bag_identifier)
                
                individual_calc = sub_dict.get('calculated_total', 0) or 0
                submission_type = sub_dict.get('submission_type', 'packaged')
                
                # Update total running total (only packaged counts - machine counts are consumed, not in bag)
                # Bag counts are also separate inventory counts, not added to total
                if bag_key not in bag_running_totals:
                    bag_running_totals[bag_key] = 0
                if submission_type == 'packaged':
                    bag_running_totals[bag_key] += individual_calc
                # repack: PO-level only; do not affect per-bag running totals (matches list view)
                
                sub_dict['individual_calc'] = individual_calc
                sub_dict['total_tablets'] = individual_calc  # Set total_tablets for frontend compatibility
                sub_dict['running_total'] = bag_running_totals[bag_key]
                
                bag_count = sub_dict.get('bag_label_count', 0) or 0
                running_total = bag_running_totals[bag_key]
                
                if bag_count == 0:
                    sub_dict['count_status'] = 'No Bag Label'
                elif abs(running_total - bag_count) <= 5:
                    sub_dict['count_status'] = 'Match'
                elif running_total < bag_count:
                    sub_dict['count_status'] = 'Under'
                else:
                    sub_dict['count_status'] = 'Over'
                
                if submission_type == 'repack':
                    sub_dict['count_status'] = 'Repack PO'
                
                submissions_processed.append(sub_dict)
            
            # Group submissions by receipt_number while maintaining sort order within groups
            submissions_processed = group_by_receipt(submissions_processed, sort_by, sort_order, filter_submission_type)
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header row
            writer.writerow([
            'Submission Date',
            'Created At',
            'Employee Name',
            'Product Name',
            'Submission Type',
            'Machine',
            'Tablet Type',
            'PO Number',
            'PO Closed',
            'Box Number',
            'Bag Number',
            'Displays Made',
            'Packs Remaining',
            'Loose Tablets',
            'Damaged Tablets',
            'Total Tablets (Individual)',
            'Running Total (Bag)',
            'Bag Label Count',
            'Count Status',
            'PO Assignment Verified',
            'Admin Notes'
            ])
            
            # Write data rows (respecting sort order)
            for sub in submissions_processed:
                submission_date = sub.get('submission_date') or sub.get('filter_date') or ''
                created_at = sub.get('created_at', '')
                if isinstance(created_at, str):
                    # Format datetime for CSV.
                    created_at = created_at[:19]  # Truncate to seconds
                
                writer.writerow([
                    submission_date,
                    created_at,
                    sub.get('employee_name', ''),
                    sub.get('product_name', ''),
                    sub.get('submission_type', 'packaged'),
                    sub.get('machine_display_name') or '',
                    sub.get('tablet_type_name', ''),
                    sub.get('po_number', ''),
                    'Yes' if sub.get('po_closed') else 'No',
                    sub.get('box_number', ''),
                    sub.get('bag_number', ''),
                    sub.get('displays_made', 0),
                    sub.get('packs_remaining', 0),
                    sub.get('loose_tablets', 0),
                    sub.get('damaged_tablets', 0),
                    sub.get('individual_calc', 0),
                    sub.get('running_total', 0),
                    sub.get('bag_label_count', 0),
                    sub.get('count_status', ''),
                    'Yes' if sub.get('po_verified', 0) else 'No',
                    sub.get('admin_notes', '')
                ])
            
            # Generate filename with date range if applicable
            filename_parts = ['submissions']
            if filter_date_from:
                filename_parts.append(f'from_{filter_date_from}')
            if filter_date_to:
                filename_parts.append(f'to_{filter_date_to}')
            if filter_tablet_type_id:
                filename_parts.append(f'type_{submissions_processed[0].get("tablet_type_name", "unknown") if submissions_processed else "unknown"}')
            if filter_po_id:
                po_info = conn.execute('SELECT po_number FROM purchase_orders WHERE id = ?', (filter_po_id,)).fetchone()
                if po_info:
                    filename_parts.append(f'po_{po_info["po_number"]}')
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{'_'.join(filename_parts)}_{timestamp}.csv"
            
            # Create response
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response
    except Exception as e:
        current_app.logger.error(f"Error exporting submissions CSV: {e}")
        traceback.print_exc()
        flash('An error occurred while exporting submissions. Please try again.', 'error')
        return redirect(url_for('submissions.submissions_list'))

