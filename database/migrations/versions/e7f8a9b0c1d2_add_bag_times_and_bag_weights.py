"""add_bag_times_and_bag_weights

- warehouse_submissions.bag_start_time, bag_end_time (UTC naive strings, same convention as created_at)
- bags.bag_weight_kg, estimated_tablets_from_weight (intake estimate from Zoho item weight)

Revision ID: e7f8a9b0c1d2
Revises: d4e5f6a7b8c9
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    ws_cols = {c['name'] for c in inspector.get_columns('warehouse_submissions')}
    with op.batch_alter_table('warehouse_submissions', schema=None) as batch_op:
        if 'bag_start_time' not in ws_cols:
            batch_op.add_column(sa.Column('bag_start_time', sa.Text(), nullable=True))
        if 'bag_end_time' not in ws_cols:
            batch_op.add_column(sa.Column('bag_end_time', sa.Text(), nullable=True))

    bag_cols = {c['name'] for c in inspector.get_columns('bags')}
    with op.batch_alter_table('bags', schema=None) as batch_op:
        if 'bag_weight_kg' not in bag_cols:
            batch_op.add_column(sa.Column('bag_weight_kg', sa.Float(), nullable=True))
        if 'estimated_tablets_from_weight' not in bag_cols:
            batch_op.add_column(sa.Column('estimated_tablets_from_weight', sa.Integer(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    ws_cols = {c['name'] for c in inspector.get_columns('warehouse_submissions')}
    with op.batch_alter_table('warehouse_submissions', schema=None) as batch_op:
        if 'bag_end_time' in ws_cols:
            batch_op.drop_column('bag_end_time')
        if 'bag_start_time' in ws_cols:
            batch_op.drop_column('bag_start_time')

    bag_cols = {c['name'] for c in inspector.get_columns('bags')}
    with op.batch_alter_table('bags', schema=None) as batch_op:
        if 'estimated_tablets_from_weight' in bag_cols:
            batch_op.drop_column('estimated_tablets_from_weight')
        if 'bag_weight_kg' in bag_cols:
            batch_op.drop_column('bag_weight_kg')
