"""record the matrix a risk catalog's suggestions were written for

A catalog is shared material — seeded, or brought in from elsewhere — so the
organisation reading it may use a different matrix than its author did. Without the
scale, a suggested "4" is a number with no unit.

Existing catalogs were written against the 5x5 that was hardcoded, which is what the
default backfills, so no suggestion changes.

Hand-written like 023-025: autogenerate proposes dropping the opsdeck-enterprise
tables whenever it runs without that plugin installed.

Revision ID: 026
Revises: 025
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None

DEFAULT_LEVELS = '5'


def upgrade():
    with op.batch_alter_table('catalog_risk', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'impact_levels', sa.Integer(),
            server_default=DEFAULT_LEVELS, nullable=False))
        batch_op.add_column(sa.Column(
            'likelihood_levels', sa.Integer(),
            server_default=DEFAULT_LEVELS, nullable=False))


def downgrade():
    with op.batch_alter_table('catalog_risk', schema=None) as batch_op:
        batch_op.drop_column('likelihood_levels')
        batch_op.drop_column('impact_levels')
