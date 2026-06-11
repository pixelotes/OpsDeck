"""link_scheduled_comm_to_event_engine

Links a queued ScheduledCommunication back to the event engine that produced it:
- event_rule_id: which EventRule fired (senders read per-rule channel config from it)
- audit_log_id: which committed change triggered it (source of the template context)

Both nullable; legacy notification comms leave them null and keep their current
NotificationEvent-based behaviour.

Revision ID: 017
Revises: 016
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scheduled_communication', schema=None) as batch_op:
        batch_op.add_column(sa.Column('event_rule_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('audit_log_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_scheduled_comm_event_rule', 'event_rule', ['event_rule_id'], ['id']
        )
        batch_op.create_foreign_key(
            'fk_scheduled_comm_audit_log', 'audit_log', ['audit_log_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('scheduled_communication', schema=None) as batch_op:
        batch_op.drop_constraint('fk_scheduled_comm_audit_log', type_='foreignkey')
        batch_op.drop_constraint('fk_scheduled_comm_event_rule', type_='foreignkey')
        batch_op.drop_column('audit_log_id')
        batch_op.drop_column('event_rule_id')
