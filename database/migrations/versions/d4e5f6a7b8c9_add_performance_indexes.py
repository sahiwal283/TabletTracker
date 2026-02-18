"""add_performance_indexes

Adds indexes for dashboard and report query performance.
Targets: warehouse_submissions filters/joins, receiving chain (small_boxes, bags), purchase_orders stats.

Revision ID: d4e5f6a7b8c9
Revises: a1b2c3d4e5f6
Create Date: 2026-02-18

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # warehouse_submissions: PO and bag joins, recent list, verification/review filters
    op.create_index('ix_ws_assigned_po_id', 'warehouse_submissions', ['assigned_po_id'], unique=False)
    op.create_index('ix_ws_bag_id', 'warehouse_submissions', ['bag_id'], unique=False)
    op.create_index('ix_ws_created_at', 'warehouse_submissions', ['created_at'], unique=False)
    op.create_index('ix_ws_po_assignment_verified', 'warehouse_submissions', ['po_assignment_verified'], unique=False)
    op.create_index('ix_ws_needs_review', 'warehouse_submissions', ['needs_review'], unique=False)
    # receiving chain: receive -> boxes -> bags
    op.create_index('ix_small_boxes_receiving_id', 'small_boxes', ['receiving_id'], unique=False)
    op.create_index('ix_bags_small_box_id', 'bags', ['small_box_id'], unique=False)
    # purchase_orders: dashboard active list and stats
    op.create_index('ix_po_closed', 'purchase_orders', ['closed'], unique=False)
    op.create_index('ix_po_zoho_po_id', 'purchase_orders', ['zoho_po_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_po_zoho_po_id', table_name='purchase_orders')
    op.drop_index('ix_po_closed', table_name='purchase_orders')
    op.drop_index('ix_bags_small_box_id', table_name='bags')
    op.drop_index('ix_small_boxes_receiving_id', table_name='small_boxes')
    op.drop_index('ix_ws_needs_review', table_name='warehouse_submissions')
    op.drop_index('ix_ws_po_assignment_verified', table_name='warehouse_submissions')
    op.drop_index('ix_ws_created_at', table_name='warehouse_submissions')
    op.drop_index('ix_ws_bag_id', table_name='warehouse_submissions')
    op.drop_index('ix_ws_assigned_po_id', table_name='warehouse_submissions')
