"""rename Payment.helper_address to recipient_address

Revision ID: 01fc8f78dd6b
Revises: da2a0c33917b
Create Date: 2026-05-01 09:07:37.356848

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '01fc8f78dd6b'
down_revision = 'da2a0c33917b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('helper_address', new_column_name='recipient_address',
                              existing_type=sa.String(42), existing_nullable=False)


def downgrade():
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column('recipient_address', new_column_name='helper_address',
                              existing_type=sa.String(42), existing_nullable=False)
