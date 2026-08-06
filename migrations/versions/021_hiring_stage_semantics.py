"""hiring_stage_semantics

Makes hiring stage behaviour follow data instead of names, and stops duplicates.

Three flags now describe a stage: is_hired_stage (starts onboarding, already existed),
is_system (part of the standard pipeline, cannot be deleted) and is_terminal (the
candidate's process is over, so the board stops showing stale ones). Until now the last
two were inferred from the stage's *name* in three separate places, which meant renaming
'Hired' silently took its behaviour with it — and translating the pipeline was
impossible without breaking it.

Also adds the unique constraint the name column never had. Duplicates were not merely
untidy: deletion refuses to remove the standard stages by name, so a second 'Hired'
could not be cleaned up through the UI at all. Existing duplicates are merged before
the constraint goes on, since an installation carrying them would otherwise fail to
migrate.

Revision ID: 021
Revises: 020
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


# The pipeline the seeder creates. (name, is_system, is_terminal)
STANDARD_STAGES = [
    ('Applied', True, False),
    ('Screening', False, False),
    ('Interview', False, False),
    ('Offer', True, False),
    ('Hired', True, True),
    ('Rejected', True, True),
]


def upgrade():
    op.add_column('hiring_stage',
                  sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('hiring_stage',
                  sa.Column('is_terminal', sa.Boolean(), nullable=False, server_default=sa.false()))

    # Backfill from the names, which is the only signal available at this point.
    for name, is_system, is_terminal in STANDARD_STAGES:
        op.execute(f"""
            UPDATE hiring_stage
            SET is_system = {'true' if is_system else 'false'},
                is_terminal = {'true' if is_terminal else 'false'}
            WHERE lower(trim(name)) = '{name.lower()}'
        """)

    # --- merge duplicates before the constraint can reject them ---------------
    #
    # Candidates are moved onto the surviving row first. Doing it the other way round
    # would either violate the foreign key or, through the ORM cascade, delete the
    # candidates along with their stage.
    op.execute("""
        UPDATE candidate SET stage_id = (
            SELECT MIN(survivor.id) FROM hiring_stage survivor
            WHERE lower(trim(survivor.name)) = (
                SELECT lower(trim(current.name)) FROM hiring_stage current
                WHERE current.id = candidate.stage_id
            )
        )
        WHERE stage_id IS NOT NULL
    """)

    # Trailing whitespace would sneak past a plain UNIQUE, so normalise it away.
    op.execute("UPDATE hiring_stage SET name = trim(name) WHERE name <> trim(name)")

    op.execute("""
        DELETE FROM hiring_stage
        WHERE id NOT IN (
            SELECT MIN(id) FROM hiring_stage GROUP BY lower(trim(name))
        )
    """)

    op.create_unique_constraint('uq_hiring_stage_name', 'hiring_stage', ['name'])


def downgrade():
    op.drop_constraint('uq_hiring_stage_name', 'hiring_stage', type_='unique')
    op.drop_column('hiring_stage', 'is_terminal')
    op.drop_column('hiring_stage', 'is_system')
