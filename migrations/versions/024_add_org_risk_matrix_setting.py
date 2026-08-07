"""add the organisation's risk matrix size

The size new assessments are scored against. Defaults to 5x5, which is what was
hardcoded before and what migration 023 stamped on every existing risk, so nothing
changes until somebody chooses otherwise.

Hand-written for the same reason as 023: autogenerate wants to drop the
opsdeck-enterprise tables whenever it runs in an environment without that plugin.

Revision ID: 024
Revises: 023
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '024'
down_revision = '023'
branch_labels = None
depends_on = None

DEFAULT_LEVELS = '5'


def upgrade():
    with op.batch_alter_table('organization_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'risk_impact_levels', sa.Integer(),
            server_default=DEFAULT_LEVELS, nullable=False))
        batch_op.add_column(sa.Column(
            'risk_likelihood_levels', sa.Integer(),
            server_default=DEFAULT_LEVELS, nullable=False))


def downgrade():
    with op.batch_alter_table('organization_settings', schema=None) as batch_op:
        batch_op.drop_column('risk_likelihood_levels')
        batch_op.drop_column('risk_impact_levels')
