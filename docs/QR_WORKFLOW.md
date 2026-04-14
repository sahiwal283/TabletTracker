# QR workflow (implemented)

TabletTracker **v3.0.0** ships the QR-based workflow described in the Cursor plan:

- Authoritative spec (full contract): `~/.cursor/plans/qr_workflow_tracking_a7719a49.plan.md`
- Short index: `~/.cursor/plans/qr_workflow_tracking_66e615a9.plan.md`

Repository implementation:

| Area | Location |
|------|----------|
| Schema | `database/migrations/versions/f8e9a0b1c2d3_add_workflow_tables.py`, `app/models/migrations.py` (`_migrate_workflow`) |
| Read / write services | `app/services/workflow_read.py`, `workflow_append.py`, `workflow_finalize.py`, `workflow_txn.py`, … |
| Floor + staff routes | `app/blueprints/workflow_floor.py`, `app/blueprints/workflow_staff.py` |
| Agent / runbook | `AGENTS.md` |

Deploy: `alembic upgrade head` then pull on PythonAnywhere or your host.
