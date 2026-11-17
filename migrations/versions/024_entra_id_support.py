"""entra_id_support

Microsoft Entra ID support:

* user.entra_oid: the Entra object id, bound on a user's first "Sign in with
  Microsoft" or by the user sync. Once set, Entra matches on it instead of the
  userPrincipalName, so a renamed or recycled UPN cannot take over the account.
* entra_sync_settings: singleton configuration of the user sync (disabled by default).
* entra_sync_run: history of sync runs and dry runs.

Revision ID: 024
Revises: 023
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entra_oid', sa.String(length=36), nullable=True))
        batch_op.create_index('ix_user_entra_oid', ['entra_oid'], unique=True)

    op.create_table(
        'entra_sync_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('group_ids', sa.Text(), nullable=True),
        sa.Column('default_role', sa.String(length=50), nullable=False, server_default='user'),
        sa.Column('schedule_mode', sa.String(length=20), nullable=False, server_default='off'),
        sa.Column('daily_time', sa.String(length=5), nullable=True),
        sa.Column('interval_hours', sa.Integer(), nullable=True),
        sa.Column('archive_threshold_percent', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'entra_sync_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('triggered_by', sa.String(length=120), nullable=True),
        sa.Column('dry_run', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unarchived_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('changes_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_entra_sync_run_started_at', 'entra_sync_run', ['started_at'])


def downgrade():
    op.drop_index('ix_entra_sync_run_started_at', table_name='entra_sync_run')
    op.drop_table('entra_sync_run')
    op.drop_table('entra_sync_settings')
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_entra_oid')
        batch_op.drop_column('entra_oid')
