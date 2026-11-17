"""add_user_entra_oid

Adds user.entra_oid, the Microsoft Entra ID object id bound on a user's first
"Sign in with Microsoft". Once set, Entra sign-ins match on it instead of the
userPrincipalName, so a renamed or recycled UPN cannot take over the account.

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
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entra_oid', sa.String(length=36), nullable=True))
        batch_op.create_index('ix_user_entra_oid', ['entra_oid'], unique=True)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_entra_oid')
        batch_op.drop_column('entra_oid')
