# Agent notes (TabletTracker)

## QR workflow (v3.0+)

- **Reads:** use `app/services/workflow_read.py` only for routes and reports. Do not scatter raw `workflow_events` SQL in blueprints or Jinja.
- **Writes:** `append_workflow_event` (events) and `try_finalize` / `create_workflow_bag_with_card` / `assign_inventory_bag_to_card` (staff: link receiving `bags` row → workflow + card) / `force_release_card` (policy plus `qr_cards` mutex). Terminal policy lives in `workflow_finalize.py`, not the read layer.
- **Do not** add policy booleans (`is_complete`, etc.) to `workflow_read` return shapes. Presentation strings (`display_stage_label`, `progress_summary`) are cosmetic only. Branch the floor UI on API **codes** and machine-readable **facts**, not labels.
- **Floor JSON** (`/workflow/floor/api/*`) is CSRF-exempt. **Staff** forms under `/workflow/staff/*` require session plus CSRF.
- **`device_id` / `page_session_id`:** accepted on floor JSON bodies for **logging correlation only** (see `workflow_floor._log_floor_correlation`). They are **not** identity, authorization, or reporting dimensions. They must not appear in `workflow_read` DTOs used for analytics.

### Full contract (human review)

The Cursor plan at `~/.cursor/plans/qr_workflow_tracking_a7719a49.plan.md` is the execution contract, including **Transaction convergence**, **Silent correctness drift**, **Dual timelines**, and **Semantic interpretation gaps**.

### Runbook: timeline SQL (SQLite)

Replace `?` with the integer `workflow_bag_id` or `qr_card_id` as noted.

**All events for one bag (lexicographic order):**

```sql
SELECT id, event_type, occurred_at, payload, station_id
FROM workflow_events
WHERE workflow_bag_id = ?
ORDER BY occurred_at ASC, id ASC;
```

**Card lifecycle slice (same fold as `workflow_read.card_lifecycle_events_for_card`):**

```sql
SELECT we.id, we.event_type, we.occurred_at, we.workflow_bag_id, we.payload
FROM workflow_events we
WHERE we.workflow_bag_id IN (
    SELECT DISTINCT workflow_bag_id FROM workflow_events
    WHERE event_type = 'CARD_ASSIGNED'
      AND CAST(json_extract(payload, '$.qr_card_id') AS INTEGER) = ?
)
   OR (
       we.event_type = 'CARD_FORCE_RELEASED'
       AND CAST(json_extract(we.payload, '$.qr_card_id') AS INTEGER) = ?
   )
ORDER BY we.occurred_at ASC, we.id ASC;
```

**Compare mutex row to assignment (support):**

```sql
SELECT id, status, scan_token, assigned_workflow_bag_id FROM qr_cards WHERE id = ?;
```

If the event fold and `qr_cards` disagree after a successful client operation, treat it as a **data bug** or manual SQL, not normal drift.
