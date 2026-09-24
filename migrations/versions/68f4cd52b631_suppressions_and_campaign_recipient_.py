"""suppressions table and campaign.recipient_emails

Revision ID: 68f4cd52b631
Revises: cdda4c53c14a
Create Date: 2026-08-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '68f4cd52b631'
down_revision = 'cdda4c53c14a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('suppressions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('unsubscribed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipient_emails', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('recipient_emails')

    op.drop_table('suppressions')
