"""Add advanced conditions to EventRule

Revision ID: 019
Revises: 018
Create Date: 2026-06-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '019'
down_revision = '018'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('event_rule', sa.Column('advanced_conditions_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('event_rule', sa.Column('condition_attribute', sa.String(length=100), nullable=True))
    op.add_column('event_rule', sa.Column('condition_operator', sa.String(length=20), nullable=True))
    op.add_column('event_rule', sa.Column('condition_value', sa.String(length=255), nullable=True))

def downgrade():
    op.drop_column('event_rule', 'condition_value')
    op.drop_column('event_rule', 'condition_operator')
    op.drop_column('event_rule', 'condition_attribute')
    op.drop_column('event_rule', 'advanced_conditions_enabled')
