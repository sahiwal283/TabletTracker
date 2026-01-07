"""add_zoho_line_item_id_to_po_lines

Adds zoho_line_item_id column to po_lines table for Zoho purchase receives.
This column stores the Zoho PO line item ID which is required when creating
purchase receives via the Zoho API.

- po_lines.zoho_line_item_id: TEXT (stores the Zoho line item ID)
- bags.zoho_receive_pushed: BOOLEAN DEFAULT 0 (tracks if bag was pushed to Zoho)
- bags.zoho_receive_id: TEXT (stores the Zoho receive ID after push)

Revision ID: a1b2c3d4e5f6
Revises: ceab0232bc0f
Create Date: 2026-01-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ceab0232bc0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Add zoho_line_item_id column to po_lines table (idempotent)
    po_lines_columns = [col['name'] for col in inspector.get_columns('po_lines')]
    if 'zoho_line_item_id' not in po_lines_columns:
        with op.batch_alter_table('po_lines', schema=None) as batch_op:
            batch_op.add_column(sa.Column('zoho_line_item_id', sa.Text(), nullable=True))
    
    # Add zoho_receive_pushed column to bags table (idempotent)
    bags_columns = [col['name'] for col in inspector.get_columns('bags')]
    if 'zoho_receive_pushed' not in bags_columns:
        with op.batch_alter_table('bags', schema=None) as batch_op:
            batch_op.add_column(sa.Column('zoho_receive_pushed', sa.Boolean(), nullable=False, server_default='0'))
    
    # Add zoho_receive_id column to bags table (idempotent)
    if 'zoho_receive_id' not in bags_columns:
        with op.batch_alter_table('bags', schema=None) as batch_op:
            batch_op.add_column(sa.Column('zoho_receive_id', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # Remove zoho_receive_id column from bags table (idempotent)
    bags_columns = [col['name'] for col in inspector.get_columns('bags')]
    if 'zoho_receive_id' in bags_columns:
        with op.batch_alter_table('bags', schema=None) as batch_op:
            batch_op.drop_column('zoho_receive_id')
    
    # Remove zoho_receive_pushed column from bags table (idempotent)
    if 'zoho_receive_pushed' in bags_columns:
        with op.batch_alter_table('bags', schema=None) as batch_op:
            batch_op.drop_column('zoho_receive_pushed')
    
    # Remove zoho_line_item_id column from po_lines table (idempotent)
    po_lines_columns = [col['name'] for col in inspector.get_columns('po_lines')]
    if 'zoho_line_item_id' in po_lines_columns:
        with op.batch_alter_table('po_lines', schema=None) as batch_op:
            batch_op.drop_column('zoho_line_item_id')

