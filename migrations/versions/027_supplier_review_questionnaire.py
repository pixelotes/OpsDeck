"""supplier_review_questionnaire

Structured supplier reviews:

* review_template / review_question: the questionnaire (check questions answered
  yes/no, review points answered OK / Not OK / N/A with a comment).
* supplier_review_answer: the answers of one review, with a copy of each question.
* security_assessment gains template_id, due_date, completed_at, completed_by_id and
  last_reminder_at: a questionnaire review is 'Scheduled' until its owner completes it.
* supplier gains review_interval_months and next_review_date for periodic reviews.

The default template is created by the app on first use (see
services/supplier_review_service.ensure_default_template), not here.

Revision ID: 027
Revises: 026
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '027'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'review_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'review_question',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('text', sa.String(length=255), nullable=False),
        sa.Column('help_text', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['template_id'], ['review_template.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_review_question_template_id', 'review_question', ['template_id'])

    with op.batch_alter_table('security_assessment') as batch_op:
        batch_op.add_column(sa.Column('template_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('due_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('completed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('last_reminder_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_security_assessment_template_id', ['template_id'])
        batch_op.create_index('ix_security_assessment_completed_by_id', ['completed_by_id'])
        batch_op.create_foreign_key('fk_security_assessment_template_id', 'review_template',
                                    ['template_id'], ['id'])
        batch_op.create_foreign_key('fk_security_assessment_completed_by_id', 'user',
                                    ['completed_by_id'], ['id'])

    op.create_table(
        'supplier_review_answer',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assessment_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('question_text', sa.String(length=255), nullable=False),
        sa.Column('answer', sa.String(length=20), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['assessment_id'], ['security_assessment.id']),
        sa.ForeignKeyConstraint(['question_id'], ['review_question.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_supplier_review_answer_assessment_id', 'supplier_review_answer', ['assessment_id'])
    op.create_index('ix_supplier_review_answer_question_id', 'supplier_review_answer', ['question_id'])

    with op.batch_alter_table('supplier') as batch_op:
        batch_op.add_column(sa.Column('review_interval_months', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('next_review_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('supplier') as batch_op:
        batch_op.drop_column('next_review_date')
        batch_op.drop_column('review_interval_months')

    op.drop_index('ix_supplier_review_answer_question_id', table_name='supplier_review_answer')
    op.drop_index('ix_supplier_review_answer_assessment_id', table_name='supplier_review_answer')
    op.drop_table('supplier_review_answer')

    with op.batch_alter_table('security_assessment') as batch_op:
        batch_op.drop_constraint('fk_security_assessment_completed_by_id', type_='foreignkey')
        batch_op.drop_constraint('fk_security_assessment_template_id', type_='foreignkey')
        batch_op.drop_index('ix_security_assessment_completed_by_id')
        batch_op.drop_index('ix_security_assessment_template_id')
        batch_op.drop_column('last_reminder_at')
        batch_op.drop_column('completed_by_id')
        batch_op.drop_column('completed_at')
        batch_op.drop_column('due_date')
        batch_op.drop_column('template_id')

    op.drop_index('ix_review_question_template_id', table_name='review_question')
    op.drop_table('review_question')
    op.drop_table('review_template')
