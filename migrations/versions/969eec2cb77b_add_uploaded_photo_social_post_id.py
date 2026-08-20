"""add uploaded_photos.social_post_id for restoring removed photos

Revision ID: 969eec2cb77b
Revises: af3f6f8a617d
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '969eec2cb77b'
down_revision = 'af3f6f8a617d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('uploaded_photos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('social_post_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_uploaded_photos_social_post_id', 'social_posts', ['social_post_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('uploaded_photos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_uploaded_photos_social_post_id', type_='foreignkey')
        batch_op.drop_column('social_post_id')
