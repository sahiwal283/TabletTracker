"""baseline_schema

Captures the existing database schema as of v1.15.8.
This migration documents the current state and serves as the starting point for Alembic.

Existing tables:
- purchase_orders: PO tracking with counts
- po_lines: Individual line items per PO
- tablet_types: Master list of tablet types with inventory_item_id
- product_details: Product packaging configuration
- warehouse_submissions: Production submissions (packaged/bag count/machine)
- shipments: Shipment tracking
- receiving: Receiving records with photos
- small_boxes: Boxes in receives
- bags: Individual bags in boxes
- employees: Employee authentication
- categories: Product categories
- machines: Production machines
- machine_counts: Machine count records
- app_settings: Application settings

Revision ID: 1401330edfe1
Revises: 
Create Date: 2025-12-10 14:26:04.173158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1401330edfe1'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This is a baseline migration for existing database.
    # All tables already exist from init_db() function.
    # To apply this migration to existing database, use: alembic stamp head
    pass


def downgrade() -> None:
    # Baseline migration cannot be downgraded
    pass
