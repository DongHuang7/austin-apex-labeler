"""campaign body_text and photo_urls for editing before send

Revision ID: 098573110cc0
Revises: 68f4cd52b631
Create Date: 2026-08-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '098573110cc0'
down_revision = '68f4cd52b631'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('body_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('photo_urls', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('photo_urls')
        batch_op.drop_column('body_text')
