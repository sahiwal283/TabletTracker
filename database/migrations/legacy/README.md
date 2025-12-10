# Legacy Migration Scripts

This folder contains ad-hoc migration scripts that were used prior to v2.0 when Alembic was adopted for proper database versioning.

## Migration History

These scripts were created as needed to modify the database schema during development:

- **migrate_db.py** - General database migration script
- **migrate_to_v1.21.0.py** - Migration for v1.21.0 release
- **migrate_roles.py** - Added role-based access control to employees table
- **migrate_language_column.py** - Added preferred_language column to employees
- **migrate_routes.py** - Helper script for route reorganization
- **fix_schema.py** - Schema fixes and corrections
- **add_needs_review_column.py** - Added needs_review flag for duplicate bag handling

## Important Notes

- **DO NOT RUN THESE SCRIPTS ON v2.0+** - They are archived for reference only
- All changes from these scripts have been captured in the v2.0 baseline migration (`001_baseline_schema.py`)
- For v2.0+, use Alembic migrations: `alembic upgrade head`

## For Developers

If you need to understand how a specific column or table was added, refer to these scripts for historical context.

