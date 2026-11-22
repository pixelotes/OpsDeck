"""jira_assets_sync

One-way sync from Jira Service Management Assets:

* jira_assets_profile: what to import (object type, AQL filter), what it becomes in
  OpsDeck and how Jira statuses map to OpsDeck states;
* jira_assets_run: history of runs and dry runs;
* asset.jira_object_id / supplier.jira_object_id: the Jira object each record is
  linked to.

Revision ID: 029
Revises: 028
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '029'
down_revision = '028'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'jira_assets_profile',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('target', sa.String(length=20), nullable=False),
        sa.Column('object_type', sa.String(length=120), nullable=False),
        sa.Column('aql_filter', sa.Text(), nullable=True),
        sa.Column('status_attribute', sa.String(length=120), nullable=False),
        sa.Column('status_map_json', sa.Text(), nullable=False),
        sa.Column('field_map_json', sa.Text(), nullable=False),
        sa.Column('create_missing', sa.Boolean(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('interval_hours', sa.Integer(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('archive_threshold_percent', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'jira_assets_run',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('triggered_by', sa.String(length=120), nullable=True),
        sa.Column('dry_run', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('fetched_count', sa.Integer(), nullable=False),
        sa.Column('created_count', sa.Integer(), nullable=False),
        sa.Column('linked_count', sa.Integer(), nullable=False),
        sa.Column('updated_count', sa.Integer(), nullable=False),
        sa.Column('archived_count', sa.Integer(), nullable=False),
        sa.Column('unarchived_count', sa.Integer(), nullable=False),
        sa.Column('changes_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['profile_id'], ['jira_assets_profile.id'],
                                name='fk_jira_assets_run_profile_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_jira_assets_run_profile_id', 'jira_assets_run', ['profile_id'])
    op.create_index('ix_jira_assets_run_started_at', 'jira_assets_run', ['started_at'])

    with op.batch_alter_table('asset') as batch_op:
        batch_op.add_column(sa.Column('jira_object_id', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_asset_jira_object_id', ['jira_object_id'], unique=True)
    with op.batch_alter_table('supplier') as batch_op:
        batch_op.add_column(sa.Column('jira_object_id', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_supplier_jira_object_id', ['jira_object_id'], unique=True)


def downgrade():
    with op.batch_alter_table('supplier') as batch_op:
        batch_op.drop_index('ix_supplier_jira_object_id')
        batch_op.drop_column('jira_object_id')
    with op.batch_alter_table('asset') as batch_op:
        batch_op.drop_index('ix_asset_jira_object_id')
        batch_op.drop_column('jira_object_id')
    op.drop_index('ix_jira_assets_run_started_at', table_name='jira_assets_run')
    op.drop_index('ix_jira_assets_run_profile_id', table_name='jira_assets_run')
    op.drop_table('jira_assets_run')
    op.drop_table('jira_assets_profile')
