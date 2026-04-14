"""add_workflow_tables

QR workflow: workflow_stations, qr_cards, workflow_bags, workflow_events
+ partial UNIQUE on BAG_FINALIZED per bag.

Revision ID: f8e9a0b1c2d3
Revises: e7f8a9b0c1d2
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8e9a0b1c2d3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)

    if not insp.has_table("workflow_stations"):
        op.create_table(
            "workflow_stations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("station_scan_token", sa.String(length=128), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("station_code", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_workflow_stations_station_scan_token",
            "workflow_stations",
            ["station_scan_token"],
            unique=True,
        )

    if not insp.has_table("workflow_bags"):
        op.create_table(
            "workflow_bags",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("box_number", sa.String(length=128), nullable=True),
            sa.Column("bag_number", sa.String(length=128), nullable=True),
            sa.Column("receipt_number", sa.String(length=128), nullable=True),
            sa.ForeignKeyConstraint(["product_id"], ["product_details.id"]),
        )
        op.create_index("ix_workflow_bags_created_at", "workflow_bags", ["created_at"])

    if not insp.has_table("qr_cards"):
        op.create_table(
            "qr_cards",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("scan_token", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
            sa.Column("assigned_workflow_bag_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["assigned_workflow_bag_id"],
                ["workflow_bags.id"],
            ),
        )
        op.create_index("ix_qr_cards_scan_token", "qr_cards", ["scan_token"], unique=True)
        op.create_index("ix_qr_cards_status", "qr_cards", ["status"])

    if not insp.has_table("workflow_events"):
        op.create_table(
            "workflow_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("occurred_at", sa.Integer(), nullable=False),
            sa.Column("workflow_bag_id", sa.Integer(), nullable=False),
            sa.Column("station_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("device_id", sa.String(length=128), nullable=True),
            sa.ForeignKeyConstraint(["workflow_bag_id"], ["workflow_bags.id"]),
            sa.ForeignKeyConstraint(["station_id"], ["workflow_stations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["employees.id"]),
        )
        op.create_index("ix_workflow_events_bag", "workflow_events", ["workflow_bag_id"])
        op.create_index("ix_workflow_events_occurred", "workflow_events", ["occurred_at"])
        op.create_index("ix_workflow_events_type", "workflow_events", ["event_type"])
        op.create_index(
            "ix_workflow_events_bag_occurred_id",
            "workflow_events",
            ["workflow_bag_id", "occurred_at", "id"],
        )

    rows = conn.execute(
        sa.text(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='uq_workflow_events_one_bag_finalized'"
        )
    ).fetchall()
    if not rows:
        op.execute(
            """
            CREATE UNIQUE INDEX uq_workflow_events_one_bag_finalized
            ON workflow_events(workflow_bag_id)
            WHERE event_type = 'BAG_FINALIZED'
            """
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workflow_events_one_bag_finalized")
    op.drop_table("workflow_events")
    op.drop_table("qr_cards")
    op.drop_table("workflow_bags")
    op.drop_table("workflow_stations")
