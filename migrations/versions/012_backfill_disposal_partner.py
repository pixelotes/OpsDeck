"""backfill_disposal_partner

Best-effort backfill of disposal_record.disposal_partner_id by matching the
legacy free-text disposal_partner against an existing supplier name
(case-insensitive, trimmed). Rows whose text does not match any supplier are
left unlinked — their text value is dropped in 013.

Revision ID: 012
Revises: 011
Create Date: 2026-06-08

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE disposal_record
        SET disposal_partner_id = (
            SELECT s.id FROM supplier s
            WHERE lower(trim(s.name)) = lower(trim(disposal_record.disposal_partner))
            LIMIT 1
        )
        WHERE disposal_partner IS NOT NULL
          AND trim(disposal_partner) <> ''
    """)


def downgrade():
    # Reverse mapping: restore the text from the linked supplier name where set.
    op.execute("""
        UPDATE disposal_record
        SET disposal_partner = (
            SELECT s.name FROM supplier s WHERE s.id = disposal_record.disposal_partner_id
        )
        WHERE disposal_partner_id IS NOT NULL
    """)
    op.execute("UPDATE disposal_record SET disposal_partner_id = NULL")
