"""merge_heads_for_damage_closeout

Merge Alembic heads after adding PO damage closeout migration.

Revision ID: l0m1n2o3p4q5
Revises: j5k6l7m8n9p0, k9l0m1n2o3p4
Create Date: 2026-04-20
"""
from typing import Sequence, Union


revision: str = 'l0m1n2o3p4q5'
down_revision: Union[str, Sequence[str], None] = ('j5k6l7m8n9p0', 'k9l0m1n2o3p4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge migration: no schema changes.
    pass


def downgrade() -> None:
    # Merge migration: no schema changes.
    pass
