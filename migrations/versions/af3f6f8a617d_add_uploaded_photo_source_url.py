"""add uploaded_photos.source_url for caching MLS photos

Revision ID: af3f6f8a617d
Revises: 3cba6a0b19d2
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'af3f6f8a617d'
down_revision = '3cba6a0b19d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('uploaded_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_url', sa.String(), nullable=True))
        batch_op.create_index(batch_op.f('ix_uploaded_photos_source_url'), ['source_url'], unique=False)


def downgrade():
    with op.batch_alter_table('uploaded_photos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_uploaded_photos_source_url'))
        batch_op.drop_column('source_url')
