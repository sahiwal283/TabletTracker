"""add bottle_sealing_machine_count to warehouse_submissions

Revision ID: j5k6l7m8n9p0
Revises: i3j4k5l6m7n8
Create Date: 2026-04-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j5k6l7m8n9p0"
down_revision: Union[str, None] = "i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("warehouse_submissions"):
        return
    cols = {c["name"] for c in inspector.get_columns("warehouse_submissions")}
    if "bottle_sealing_machine_count" not in cols:
        with op.batch_alter_table("warehouse_submissions", schema=None) as batch_op:
            batch_op.add_column(sa.Column("bottle_sealing_machine_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("warehouse_submissions"):
        return
    cols = {c["name"] for c in inspector.get_columns("warehouse_submissions")}
    if "bottle_sealing_machine_count" in cols:
        with op.batch_alter_table("warehouse_submissions", schema=None) as batch_op:
            batch_op.drop_column("bottle_sealing_machine_count")
