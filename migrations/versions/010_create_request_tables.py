"""create_request_tables

Adds the service Request feature schema: the `request` table and its
`request_tags` association table.

Revision ID: 010
Revises: 009
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_ref', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('request_type', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('triaged_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('requester_id', sa.Integer(), nullable=False),
        sa.Column('assignee_id', sa.Integer(), nullable=True),
        sa.Column('triaged_by_id', sa.Integer(), nullable=True),
        sa.Column('service_id', sa.Integer(), nullable=True),
        sa.Column('asset_id', sa.Integer(), nullable=True),
        sa.Column('software_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['requester_id'], ['user.id']),
        sa.ForeignKeyConstraint(['assignee_id'], ['user.id']),
        sa.ForeignKeyConstraint(['triaged_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['service_id'], ['business_service.id']),
        sa.ForeignKeyConstraint(['asset_id'], ['asset.id']),
        sa.ForeignKeyConstraint(['software_id'], ['software.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.create_index('ix_request_external_ref', ['external_ref'], unique=True)
        batch_op.create_index('ix_request_status', ['status'], unique=False)
        batch_op.create_index('ix_request_requester_id', ['requester_id'], unique=False)
        batch_op.create_index('ix_request_assignee_id', ['assignee_id'], unique=False)
        batch_op.create_index('ix_request_triaged_by_id', ['triaged_by_id'], unique=False)
        batch_op.create_index('ix_request_service_id', ['service_id'], unique=False)
        batch_op.create_index('ix_request_asset_id', ['asset_id'], unique=False)
        batch_op.create_index('ix_request_software_id', ['software_id'], unique=False)

    op.create_table(
        'request_tags',
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['request_id'], ['request.id']),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id']),
        sa.PrimaryKeyConstraint('request_id', 'tag_id'),
    )


def downgrade():
    op.drop_table('request_tags')
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.drop_index('ix_request_software_id')
        batch_op.drop_index('ix_request_asset_id')
        batch_op.drop_index('ix_request_service_id')
        batch_op.drop_index('ix_request_triaged_by_id')
        batch_op.drop_index('ix_request_assignee_id')
        batch_op.drop_index('ix_request_requester_id')
        batch_op.drop_index('ix_request_status')
        batch_op.drop_index('ix_request_external_ref')
    op.drop_table('request')
