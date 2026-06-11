"""add_audit_log_event_processed

Adds the event_processed flag to audit_log so the event engine can mark each
committed change as handled (and avoid re-notifying). A partial index keeps the
"unprocessed" lookup cheap on a high-volume table.

Existing rows are backfilled to processed=true so the engine does not notify on
historical changes when first enabled.

Revision ID: 016
Revises: 015
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('event_processed', sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Backfill pre-existing rows as already processed (don't notify on history).
    op.execute("UPDATE audit_log SET event_processed = true")
    # Partial index: only unprocessed rows are indexed, so it stays tiny.
    op.create_index(
        'ix_audit_log_unprocessed',
        'audit_log',
        ['id'],
        postgresql_where=sa.text('event_processed = false'),
    )


def downgrade():
    op.drop_index('ix_audit_log_unprocessed', table_name='audit_log')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_column('event_processed')
