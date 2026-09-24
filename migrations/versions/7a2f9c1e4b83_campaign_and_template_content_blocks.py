"""campaign and template content_blocks

Revision ID: 7a2f9c1e4b83
Revises: 098573110cc0
Create Date: 2026-08-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7a2f9c1e4b83'
down_revision = '098573110cc0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_blocks', sa.JSON(), nullable=True))

    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_blocks', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_column('content_blocks')

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('content_blocks')
