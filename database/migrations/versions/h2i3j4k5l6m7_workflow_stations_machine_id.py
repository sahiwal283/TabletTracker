"""workflow_stations.machine_id links sealing stations to machines (machine count form)

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-04-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("workflow_stations"):
        return
    cols = {c["name"] for c in insp.get_columns("workflow_stations")}
    if "machine_id" not in cols:
        with op.batch_alter_table("workflow_stations") as batch:
            batch.add_column(sa.Column("machine_id", sa.Integer(), nullable=True))
            if insp.has_table("machines"):
                batch.create_foreign_key(
                    "fk_workflow_stations_machine_id",
                    "machines",
                    ["machine_id"],
                    ["id"],
                )
    # Backfill when machines table exists (production schema)
    if insp.has_table("machines"):
        op.execute(
            """
            UPDATE workflow_stations
            SET machine_id = (SELECT id FROM machines WHERE machine_name = 'Machine 1' LIMIT 1)
            WHERE station_code = 'M1' AND machine_id IS NULL
            """
        )
        op.execute(
            """
            UPDATE workflow_stations
            SET machine_id = (SELECT id FROM machines WHERE machine_name = 'Machine 2' LIMIT 1)
            WHERE station_code = 'M2' AND machine_id IS NULL
            """
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if not insp.has_table("workflow_stations"):
        return
    cols = {c["name"] for c in insp.get_columns("workflow_stations")}
    if "machine_id" not in cols:
        return
    with op.batch_alter_table("workflow_stations") as batch:
        if insp.has_table("machines"):
            try:
                batch.drop_constraint("fk_workflow_stations_machine_id", type_="foreignkey")
            except Exception:
                pass
    with op.batch_alter_table("workflow_stations") as batch:
        batch.drop_column("machine_id")
