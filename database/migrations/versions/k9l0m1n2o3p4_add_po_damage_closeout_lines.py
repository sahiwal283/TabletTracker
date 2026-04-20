"""add_po_damage_closeout_lines

Adds po_damage_closeout_lines table to store PO closeout damage weight entries per flavor.

Revision ID: k9l0m1n2o3p4
Revises: e7f8a9b0c1d2
Create Date: 2026-04-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k9l0m1n2o3p4'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = set(inspector.get_table_names())
    if 'po_damage_closeout_lines' in table_names:
        return
    op.create_table(
        'po_damage_closeout_lines',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('po_id', sa.Integer(), nullable=False),
        sa.Column('po_line_id', sa.Integer(), nullable=False, unique=True),
        sa.Column('inventory_item_id', sa.Text(), nullable=True),
        sa.Column('damage_weight_kg', sa.Float(), nullable=True),
        sa.Column('estimated_damaged_tablets', sa.Integer(), nullable=True),
        sa.Column('grams_per_tablet', sa.Float(), nullable=True),
        sa.Column('weight_missing', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('weight_source', sa.Text(), nullable=True, server_default='zoho_item_weight'),
        sa.Column('updated_by', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.Text(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('created_at', sa.Text(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id']),
        sa.ForeignKeyConstraint(['po_line_id'], ['po_lines.id']),
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    table_names = set(inspector.get_table_names())
    if 'po_damage_closeout_lines' in table_names:
        op.drop_table('po_damage_closeout_lines')
