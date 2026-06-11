"""create_event_rule

Creates the event_rule table — the configurable layer of the event engine. A rule
matches committed entity changes (by entity_type + action) and enqueues a
notification through the existing communications queue.

Revision ID: 015
Revises: 014
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'event_rule',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('entity_type', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False, server_default='any'),
        sa.Column('recipient_mode', sa.String(length=20), nullable=False, server_default='admins'),
        sa.Column('recipient_emails', sa.Text(), nullable=True),
        sa.Column('recipient_role', sa.String(length=50), nullable=True),
        sa.Column('template_id', sa.Integer(), nullable=True),
        sa.Column('channels', sa.JSON(), nullable=True),
        sa.Column('slack_target_channel', sa.String(length=50), nullable=True),
        sa.Column('webhook_url', sa.String(length=500), nullable=True),
        sa.Column('discord_webhook_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['email_template.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_event_rule_entity_type', 'event_rule', ['entity_type'])


def downgrade():
    op.drop_index('ix_event_rule_entity_type', table_name='event_rule')
    op.drop_table('event_rule')
