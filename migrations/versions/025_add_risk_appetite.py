"""add the organisation's risk appetite

Where green becomes amber and amber becomes red, as percentages of the maximum score.
Defaults to 20/60/80, which is exactly where the hardcoded thresholds sat on a 5x5
matrix (5, 15 and 20 out of 25), so nothing changes colour until somebody chooses
otherwise.

Unlike the matrix size in 023, this is not stamped per risk: it applies to the whole
register the moment it changes, which is the point of setting it.

Hand-written for the same reason as 023 and 024: autogenerate proposes dropping the
opsdeck-enterprise tables when that plugin is not installed.

Revision ID: 025
Revises: 024
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None

BANDS = (
    ('risk_appetite_medium_from', '20'),
    ('risk_appetite_high_from', '60'),
    ('risk_appetite_critical_from', '80'),
)


def upgrade():
    with op.batch_alter_table('organization_settings', schema=None) as batch_op:
        for column, default in BANDS:
            batch_op.add_column(sa.Column(
                column, sa.Integer(), server_default=default, nullable=False))


def downgrade():
    with op.batch_alter_table('organization_settings', schema=None) as batch_op:
        for column, _ in reversed(BANDS):
            batch_op.drop_column(column)
