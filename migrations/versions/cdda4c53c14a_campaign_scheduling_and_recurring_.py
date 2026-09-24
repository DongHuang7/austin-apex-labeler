"""campaign scheduling and recurring template fields

Revision ID: cdda4c53c14a
Revises: 969eec2cb77b
Create Date: 2026-08-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cdda4c53c14a'
down_revision = '969eec2cb77b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(), nullable=False, server_default='sent'))
        batch_op.add_column(sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('recipient_group', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('account', sa.String(), nullable=True))

    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_html', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('account_owner', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('recipient_group', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('scheduled_month', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('scheduled_day', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_triggered_year', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('templates', schema=None) as batch_op:
        batch_op.drop_column('last_triggered_year')
        batch_op.drop_column('scheduled_day')
        batch_op.drop_column('scheduled_month')
        batch_op.drop_column('recipient_group')
        batch_op.drop_column('account_owner')
        batch_op.drop_column('is_html')

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('account')
        batch_op.drop_column('recipient_group')
        batch_op.drop_column('scheduled_time')
        batch_op.drop_column('status')
