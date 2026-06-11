"""add_event_rule_slack_webhook

Adds slack_webhook_url to event_rule so a rule can deliver to Slack via an
incoming webhook (POST {"text": "..."}) without a bot token. When set, it takes
precedence over the bot-API path (slack_target_channel / DM-by-email).

Revision ID: 018
Revises: 017
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('event_rule', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slack_webhook_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('event_rule', schema=None) as batch_op:
        batch_op.drop_column('slack_webhook_url')
