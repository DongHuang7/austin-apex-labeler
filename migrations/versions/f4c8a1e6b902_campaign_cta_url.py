"""campaign cta_url (configurable "visit our website" button link for manual email)

Revision ID: f4c8a1e6b902
Revises: e1a9b7c3d5f2
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f4c8a1e6b902'
down_revision = 'e1a9b7c3d5f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cta_url', sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('cta_url')
