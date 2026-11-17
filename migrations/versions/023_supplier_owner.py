"""supplier_owner

Adds an internal owner to suppliers: the person or group accountable for the
relationship (SRM), who will be assigned the periodic supplier reviews.

Polymorphic like the other owned entities (Link, SecurityActivity…): owner_type is
'User' or 'Group' and owner_id points at that table, so there is no foreign key.
Both columns are nullable and existing suppliers start without an owner.

Revision ID: 023
Revises: 022
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('supplier') as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('owner_type', sa.String(length=50), nullable=True))
        batch_op.create_index('ix_supplier_owner', ['owner_type', 'owner_id'], unique=False)


def downgrade():
    with op.batch_alter_table('supplier') as batch_op:
        batch_op.drop_index('ix_supplier_owner')
        batch_op.drop_column('owner_type')
        batch_op.drop_column('owner_id')
