"""workflow_stations.station_kind: sealing / blister / packaging / combined

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i3j4k5l6m7n8"
down_revision: Union[str, None] = "h2i3j4k5l6m7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("workflow_stations"):
        return
    cols = {c["name"] for c in insp.get_columns("workflow_stations")}
    if "station_kind" not in cols:
        with op.batch_alter_table("workflow_stations") as batch:
            batch.add_column(
                sa.Column("station_kind", sa.String(length=32), nullable=True),
            )
    op.execute("UPDATE workflow_stations SET station_kind = 'sealing' WHERE station_kind IS NULL OR TRIM(station_kind) = ''")


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("workflow_stations"):
        return
    cols = {c["name"] for c in insp.get_columns("workflow_stations")}
    if "station_kind" in cols:
        with op.batch_alter_table("workflow_stations") as batch:
            batch.drop_column("station_kind")
