"""general posts/campaigns, uploaded photos, templates

Revision ID: 3cba6a0b19d2
Revises: 01b9414e38f3
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3cba6a0b19d2'
down_revision = '01b9414e38f3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.alter_column('listing_id',
               existing_type=sa.Integer(),
               nullable=True)

    with op.batch_alter_table('social_posts', schema=None) as batch_op:
        batch_op.alter_column('listing_id',
               existing_type=sa.Integer(),
               nullable=True)

    op.create_table('uploaded_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(), nullable=False),
    sa.Column('content_type', sa.String(), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )

    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('platform', sa.String(), nullable=True),
    sa.Column('subject', sa.String(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('templates')
    op.drop_table('uploaded_photos')

    with op.batch_alter_table('social_posts', schema=None) as batch_op:
        batch_op.alter_column('listing_id',
               existing_type=sa.Integer(),
               nullable=False)

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.alter_column('listing_id',
               existing_type=sa.Integer(),
               nullable=False)
