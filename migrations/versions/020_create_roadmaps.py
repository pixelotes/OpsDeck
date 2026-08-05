"""create_roadmaps

Creates the Roadmaps module: strategic planning of goals and initiatives over
periods (typically quarters). Initiatives are positioned on an integer step grid
(4 steps per period) with denormalised planned dates so they stay queryable in SQL.

Also registers the 'roadmaps' module in the Module table so existing installations
get the permission entry — the seeder only runs on fresh installs.

Revision ID: 020
Revises: 019
Create Date: 2026-08-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'roadmap',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='draft'),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'roadmap_period',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roadmap_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['roadmap_id'], ['roadmap.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_roadmap_period_roadmap_id', 'roadmap_period', ['roadmap_id'])

    op.create_table(
        'roadmap_goal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roadmap_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=False, server_default='#2E5F9E'),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['roadmap_id'], ['roadmap.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_roadmap_goal_roadmap_id', 'roadmap_goal', ['roadmap_id'])

    op.create_table(
        'roadmap_initiative',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('start_step', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('end_step', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('planned_start_date', sa.Date(), nullable=True),
        sa.Column('planned_end_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='planned'),
        sa.Column('priority', sa.String(length=50), nullable=False, server_default='medium'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('points', sa.Integer(), nullable=True),
        sa.Column('is_new', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('external_ref', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('external_url', sa.String(length=500), nullable=True),
        sa.Column('owner_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['goal_id'], ['roadmap_goal.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_roadmap_initiative_goal_id', 'roadmap_initiative', ['goal_id'])
    op.create_index('ix_roadmap_initiative_planned_start_date', 'roadmap_initiative',
                    ['planned_start_date'])
    op.create_index('ix_roadmap_initiative_planned_end_date', 'roadmap_initiative',
                    ['planned_end_date'])

    op.create_table(
        'roadmap_dependency',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('predecessor_id', sa.Integer(), nullable=False),
        sa.Column('successor_id', sa.Integer(), nullable=False),
        sa.Column('lag', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['predecessor_id'], ['roadmap_initiative.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['successor_id'], ['roadmap_initiative.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('predecessor_id', 'successor_id', name='uq_roadmap_dependency'),
    )
    op.create_index('ix_roadmap_dependency_predecessor_id', 'roadmap_dependency',
                    ['predecessor_id'])
    op.create_index('ix_roadmap_dependency_successor_id', 'roadmap_dependency',
                    ['successor_id'])

    op.create_table(
        'roadmap_initiative_link',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('initiative_id', sa.Integer(), nullable=False),
        sa.Column('related_object_id', sa.Integer(), nullable=False),
        sa.Column('related_object_type', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['initiative_id'], ['roadmap_initiative.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('initiative_id', 'related_object_id', 'related_object_type',
                            name='uq_roadmap_initiative_link'),
    )
    op.create_index('ix_roadmap_initiative_link_initiative_id', 'roadmap_initiative_link',
                    ['initiative_id'])
    op.create_index('ix_roadmap_initiative_link_related', 'roadmap_initiative_link',
                    ['related_object_type', 'related_object_id'])

    # Register the module for RBAC. Idempotent: existing installs that somehow already
    # have the row (e.g. re-seeded) are left untouched.
    op.execute("""
        INSERT INTO module (name, slug, description)
        SELECT 'Roadmaps', 'roadmaps',
               'Strategic roadmaps: quarterly planning of goals and initiatives.'
        WHERE NOT EXISTS (SELECT 1 FROM module WHERE slug = 'roadmaps')
    """)


def downgrade():
    op.execute("DELETE FROM module WHERE slug = 'roadmaps'")

    op.drop_index('ix_roadmap_initiative_link_related', table_name='roadmap_initiative_link')
    op.drop_index('ix_roadmap_initiative_link_initiative_id',
                  table_name='roadmap_initiative_link')
    op.drop_table('roadmap_initiative_link')

    op.drop_index('ix_roadmap_dependency_successor_id', table_name='roadmap_dependency')
    op.drop_index('ix_roadmap_dependency_predecessor_id', table_name='roadmap_dependency')
    op.drop_table('roadmap_dependency')

    op.drop_index('ix_roadmap_initiative_planned_end_date', table_name='roadmap_initiative')
    op.drop_index('ix_roadmap_initiative_planned_start_date', table_name='roadmap_initiative')
    op.drop_index('ix_roadmap_initiative_goal_id', table_name='roadmap_initiative')
    op.drop_table('roadmap_initiative')

    op.drop_index('ix_roadmap_goal_roadmap_id', table_name='roadmap_goal')
    op.drop_table('roadmap_goal')

    op.drop_index('ix_roadmap_period_roadmap_id', table_name='roadmap_period')
    op.drop_table('roadmap_period')

    op.drop_table('roadmap')
