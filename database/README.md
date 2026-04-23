# Database layout

## Alembic (team migrations)

- **`migrations/`** — Alembic environment and version chain under `migrations/versions/`. Use `alembic upgrade head` against the configured database when operating in the Alembic workflow.
- **`migrations/README`** — Alembic-oriented notes.
- **`migrations/legacy/`** — Older SQLite migration helpers and docs (`README.md`). Not the primary path for new schema work if the team standard is Alembic.

## App startup (SQLite runtime path)

On a normal app boot, incremental DDL is driven by:

- **`app/models/schema.py`** — table creation / baseline structure.
- **`app/models/migrations.py`** — `MigrationRunner`: idempotent column/table additions for existing SQLite files.

These are not a substitute for Alembic on shared Postgres-style workflows; they keep the embedded SQLite app self-healing.

## One-off and maintenance scripts (`database/*.py`)

Scripts in the repo root of `database/` are mostly **historical or operational** utilities (column adds, backfills, checks). Prefer Alembic for new schema changes when that is your process; otherwise run these only when you understand the data impact.

| Script | Purpose (short) |
|--------|-------------------|
| `add_bottle_columns.py` | Add bottle-related columns |
| `add_closed_column.py` | Add closed/status column where applicable |
| `add_inventory_item_id_column.py` | Add `inventory_item_id` column |
| `add_product_category_column.py` | Product category column |
| `add_product_variety_columns.py` | Variety pack product columns |
| `add_receipt_number_column.py` | Receipt number on submissions |
| `add_receive_status_column.py` | Receive status column |
| `add_tablets_pressed_column.py` | Machine/tablets pressed column |
| `add_variety_pack_columns.py` | Variety pack columns |
| `backfill_inventory_item_id.py` | Backfill inventory item ids |
| `backfill_machine_id_submissions.py` | Backfill machine id on submissions |
| `backfill_machine_submissions.py` | Machine submission backfill |
| `backfill_missing_data.py` | General missing-data backfill |
| `backfill_receive_names.py` | Backfill receive display names |
| `backup_manager.py` | Backup helper |
| `check_backup_schedule.py` | Backup schedule check |
| `check_categories.py` | Category configuration check |
| `check_machine_submissions.py` | Machine submission sanity check |
| `check_schema_packaging.py` | Packaging-related schema check |
| `check_spearmint_config.py` | Config check (spearmint) |
| `comprehensive_migration.py` | Legacy comprehensive migration helper |
| `db_utils.py` | Shared DB helpers for scripts |
| `fix_bag_assignments.py` | Repair bag assignment data |
| `restore_to_alembic_db.py` | Restore / align DB with Alembic expectations |
| `run_v2_migrations.py` | Legacy v2 migration runner |
| `setup_db.py` | Initial DB setup helper |
| `verify_admin_notes.py` | Verify admin notes column / data |
| `verify_bag_assignments.py` | Verify bag assignments |

## Archive

There is no separate `archive/` subtree yet; one-off scripts remain in `database/` so existing runbooks and paths stay valid. New retired scripts can be moved under `database/archive/` over time with a row added here.
