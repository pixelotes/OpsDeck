"""drop_disposal_partner_text

Drops the legacy free-text disposal_partner column now that disposal partners
are linked to suppliers via disposal_partner_id (added in 011, backfilled in
012). Text values that did not match a supplier are not preserved.

Revision ID: 013
Revises: 012
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('disposal_record', schema=None) as batch_op:
        batch_op.drop_column('disposal_partner')


def downgrade():
    with op.batch_alter_table('disposal_record', schema=None) as batch_op:
        batch_op.add_column(sa.Column('disposal_partner', sa.String(length=255), nullable=True))
    # 012's downgrade repopulates this column from the linked supplier name.
