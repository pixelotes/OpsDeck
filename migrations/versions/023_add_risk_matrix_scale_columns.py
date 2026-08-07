"""add risk matrix scale columns

Records, on each risk and each assessment item, the size of the matrix its impact and
likelihood were chosen from. Existing rows were all scored on the 5x5 matrix that was
hardcoded until now, which is what the server default backfills them with — so this
migration changes no score and no severity.

Storing it per row is what lets an organisation change its matrix later without
rewriting the meaning of everything already assessed: a 4 out of 5 stays a 4 out of 5,
and comparison across sizes happens on the percentage rather than the raw product.

Written by hand rather than left as autogenerate produced it. Autogenerate proposed
dropping the eight opsdeck-enterprise tables, because those models are not installed in
the environment the migration was generated in; running that would delete a customer's
enterprise data. Only the four column additions belong here.

Revision ID: 023
Revises: 022
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '023'
down_revision = '022'
branch_labels = None
depends_on = None

DEFAULT_LEVELS = '5'
TABLES = ('risk', 'risk_assessment_item')


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                'impact_levels', sa.Integer(),
                server_default=DEFAULT_LEVELS, nullable=False))
            batch_op.add_column(sa.Column(
                'likelihood_levels', sa.Integer(),
                server_default=DEFAULT_LEVELS, nullable=False))


def downgrade():
    for table in reversed(TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('likelihood_levels')
            batch_op.drop_column('impact_levels')
