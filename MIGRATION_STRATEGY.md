# Migration Strategy

## Current Migration Files

### Standalone Migration Scripts (Root Directory)
These are **manual migration scripts** run for specific version upgrades:

1. **`migrate_db.py`** - General database migration (creates tables, adds columns)
2. **`migrate_to_v1.21.0.py`** - Version-specific migration for v1.21.0
3. **`migrate_roles.py`** - Adds role-based access control
4. **`migrate_language_column.py`** - Adds language preference column

**Purpose**: Run manually when upgrading to specific versions or adding features.

### Integrated Migration System (`app/models/migrations.py`)
This is an **automatic migration runner** integrated into `init_db()`:

**Purpose**: Automatically runs migrations during database initialization to ensure schema is up-to-date.

## Recommendation

The new `app/models/migrations.py` consolidates the migration logic that's currently scattered in `app.py`'s `init_db()` function. It's designed to:

1. Run automatically when `init_db()` is called
2. Be idempotent (safe to run multiple times)
3. Handle all schema changes in one place

## Options

### Option 1: Keep Both (Recommended)
- **Standalone scripts**: Keep for manual migrations and version-specific upgrades
- **Integrated migrations**: Use for automatic schema updates during initialization

### Option 2: Consolidate Everything
- Move all migration logic into `app/models/migrations.py`
- Keep standalone scripts as thin wrappers that call the migration system

### Option 3: Remove New File
- Keep only standalone migration scripts
- Continue using inline migrations in `init_db()`

## Current Status

The new `app/models/migrations.py` duplicates some logic from `app.py`'s `init_db()` function. This was intentional to:
- Extract migration logic into a reusable class
- Make migrations testable
- Prepare for future route migration to blueprints

However, it creates some duplication. We should consolidate to avoid confusion.

