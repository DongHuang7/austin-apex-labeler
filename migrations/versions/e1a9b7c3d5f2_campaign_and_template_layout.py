"""campaign and template layout (which listing-email HTML structure to render)

Revision ID: e1a9b7c3d5f2
Revises: 7a2f9c1e4b83
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e1a9b7c3d5f2'
down_revision = '7a2f9c1e4b83'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('layout', sa.String(), nullable=False, server_default='original'))
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('layout', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_column('layout')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('layout')
