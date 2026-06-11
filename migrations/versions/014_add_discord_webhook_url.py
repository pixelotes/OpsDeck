"""add_discord_webhook_url

Adds the discord_webhook_url column to notification_event so events can deliver
to a Discord incoming webhook (POST {"content": "..."}). Complements the
existing generic webhook_url; the new 'discord' channel uses this field.

Revision ID: 014
Revises: 013
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notification_event', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discord_webhook_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('notification_event', schema=None) as batch_op:
        batch_op.drop_column('discord_webhook_url')
