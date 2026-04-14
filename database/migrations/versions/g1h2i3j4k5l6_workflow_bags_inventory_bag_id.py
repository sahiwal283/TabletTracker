"""workflow_bags link to receiving bags (shipment)

Revision ID: g1h2i3j4k5l6
Revises: f8e9a0b1c2d3
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "f8e9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c["name"] for c in insp.get_columns("workflow_bags")}
    if "inventory_bag_id" not in cols:
        with op.batch_alter_table("workflow_bags") as batch:
            batch.add_column(
                sa.Column("inventory_bag_id", sa.Integer(), nullable=True),
            )
            batch.create_foreign_key(
                "fk_workflow_bags_inventory_bag_id",
                "bags",
                ["inventory_bag_id"],
                ["id"],
            )
    rows = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_workflow_bags_inventory_bag_id'"
        )
    ).fetchall()
    if not rows:
        op.execute(
            """
            CREATE UNIQUE INDEX uq_workflow_bags_inventory_bag_id
            ON workflow_bags(inventory_bag_id)
            WHERE inventory_bag_id IS NOT NULL
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workflow_bags_inventory_bag_id")
    with op.batch_alter_table("workflow_bags") as batch:
        batch.drop_constraint("fk_workflow_bags_inventory_bag_id", type_="foreignkey")
    with op.batch_alter_table("workflow_bags") as batch:
        batch.drop_column("inventory_bag_id")
