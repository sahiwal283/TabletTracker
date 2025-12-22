"""add_closed_status_to_receives_and_bags

Adds ability to close bags and receives when they're physically emptied.
This prevents incorrect submissions from being assigned to completed bags/receives.

- receiving.closed: BOOLEAN DEFAULT FALSE
- Bags already have status column, just need to enforce 'Closed' status in matching logic

Revision ID: ceab0232bc0f
Revises: 1401330edfe1
Create Date: 2025-12-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ceab0232bc0f'
down_revision: Union[str, None] = '0c2fa3d143a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add closed column to receiving table
    with op.batch_alter_table('receiving', schema=None) as batch_op:
        batch_op.add_column(sa.Column('closed', sa.Boolean(), nullable=False, server_default='0'))
    
    # Update existing bags to have 'Available' status if NULL
    op.execute("UPDATE bags SET status = 'Available' WHERE status IS NULL OR status = ''")


def downgrade() -> None:
    # Remove closed column from receiving table
    with op.batch_alter_table('receiving', schema=None) as batch_op:
        batch_op.drop_column('closed')
