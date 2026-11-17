"""api_connectors

API connectors move from the opsdeck-enterprise plugin into the core app.

* enterprise_tasks / enterprise_subtasks / enterprise_reports (created by 001 for the
  plugin) are renamed to connector_tasks / connector_subtasks / connector_reports, so
  an install that used the plugin keeps its credentials and report history. Their
  foreign keys get the indexes 022 gave every other one.
* uar_comparison: the 'Enterprise Report' source type becomes 'Connector Report'.

Revision ID: 025
Revises: 024
Create Date: 2026-11-17

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '025'
down_revision = '024'
branch_labels = None
depends_on = None

RENAMES = (  # plugin table -> core table
    ('enterprise_tasks', 'connector_tasks'),
    ('enterprise_subtasks', 'connector_subtasks'),
    ('enterprise_reports', 'connector_reports'),
)


def upgrade():
    for old, new in RENAMES:
        op.rename_table(old, new)

    op.create_index('ix_connector_subtasks_task_id', 'connector_subtasks', ['task_id'])
    op.create_index('ix_connector_reports_subtask_id', 'connector_reports', ['subtask_id'])

    op.execute("UPDATE uar_comparison SET source_a_type = 'Connector Report' "
               "WHERE source_a_type = 'Enterprise Report'")
    op.execute("UPDATE uar_comparison SET source_b_type = 'Connector Report' "
               "WHERE source_b_type = 'Enterprise Report'")


def downgrade():
    op.execute("UPDATE uar_comparison SET source_a_type = 'Enterprise Report' "
               "WHERE source_a_type = 'Connector Report'")
    op.execute("UPDATE uar_comparison SET source_b_type = 'Enterprise Report' "
               "WHERE source_b_type = 'Connector Report'")

    op.drop_index('ix_connector_reports_subtask_id', table_name='connector_reports')
    op.drop_index('ix_connector_subtasks_task_id', table_name='connector_subtasks')
    for old, new in reversed(RENAMES):
        op.rename_table(new, old)
