"""add_disposal_partner_fk

Adds the disposal_partner_id FK column on disposal_record (links to supplier).
The legacy free-text disposal_partner column is kept for now; it is backfilled
in 012 and dropped in 013.

Revision ID: 011
Revises: 010
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('disposal_record', schema=None) as batch_op:
        batch_op.add_column(sa.Column('disposal_partner_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_disposal_record_disposal_partner_id', 'supplier', ['disposal_partner_id'], ['id']
        )
        batch_op.create_index('ix_disposal_record_disposal_partner_id', ['disposal_partner_id'], unique=False)


def downgrade():
    with op.batch_alter_table('disposal_record', schema=None) as batch_op:
        batch_op.drop_index('ix_disposal_record_disposal_partner_id')
        batch_op.drop_constraint('fk_disposal_record_disposal_partner_id', type_='foreignkey')
        batch_op.drop_column('disposal_partner_id')
