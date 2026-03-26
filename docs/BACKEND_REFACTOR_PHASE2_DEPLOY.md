# Backend Refactor Phase 2 - PythonAnywhere Verification

This release keeps endpoint contracts stable and does not require new runtime tooling.

## Deploy Commands

```bash
cd ~/TabletTracker
git fetch origin
git checkout feature/frontend-ui-modernize-phase1
git pull --ff-only origin feature/frontend-ui-modernize-phase1
```

If your PythonAnywhere app uses a virtual environment:

```bash
cd ~/TabletTracker
source venv/bin/activate
pip install -r requirements.txt
```

If your deploy workflow applies migrations:

```bash
cd ~/TabletTracker
source venv/bin/activate
alembic upgrade head
```

Reload from PythonAnywhere Web tab after pull.

## Quick Smoke Checks

1. Login and open Dashboard.
2. Trigger `/api/reports/po-summary` by loading report selectors.
3. Open Purchase Orders page and preview PO details.
4. Trigger a non-destructive Zoho sync action in admin/dashboard.
5. Confirm no route-level regressions in submissions and receiving pages.

## Notes

- Backend now enforces SQLite foreign keys per connection.
- PO sync transaction commits are owned by route/service transaction context (safer rollback behavior).
