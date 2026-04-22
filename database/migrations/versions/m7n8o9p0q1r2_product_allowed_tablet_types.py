"""product_allowed_tablet_types junction for alternate tablets per product

Revision ID: m7n8o9p0q1r2
Revises: l0m1n2o3p4q5
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m7n8o9p0q1r2"
down_revision: Union[str, Sequence[str], None] = "l0m1n2o3p4q5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_allowed_tablet_types",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_details_id", sa.Integer(), nullable=False),
        sa.Column("tablet_type_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("product_details_id", "tablet_type_id", name="uq_pat_product_tablet"),
        sa.ForeignKeyConstraint(
            ["product_details_id"],
            ["product_details.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tablet_type_id"],
            ["tablet_types.id"],
        ),
    )
    op.create_index(
        "ix_pat_product",
        "product_allowed_tablet_types",
        ["product_details_id"],
        unique=False,
    )
    op.execute(
        """
        INSERT OR IGNORE INTO product_allowed_tablet_types (product_details_id, tablet_type_id)
        SELECT id, tablet_type_id FROM product_details
        WHERE tablet_type_id IS NOT NULL AND COALESCE(is_variety_pack, 0) = 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_pat_product", table_name="product_allowed_tablet_types")
    op.drop_table("product_allowed_tablet_types")
