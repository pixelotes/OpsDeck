"""user_login_enabled

* user.login_enabled: False for "directory only" users, kept so they can be linked to
  assets (owner, assignee) but refused on every sign-in path (password, Google and
  Microsoft SSO, API token). Existing users keep their access (server default true).
* entra_sync_settings.new_user_login: whether the Entra ID sync gives the users it
  creates sign-in access (off by default: new users are directory only).
* entra_sync_settings.access_group_ids: optional Entra groups whose members get
  sign-in access; when set, the sync keeps every synced user's access in line with
  membership (each change shown in the preview).

Revision ID: 028
Revises: 026
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '028'
down_revision = '026'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('login_enabled', sa.Boolean(), nullable=False,
                                      server_default=sa.true()))

    with op.batch_alter_table('entra_sync_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('new_user_login', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('access_group_ids', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('entra_sync_settings', schema=None) as batch_op:
        batch_op.drop_column('access_group_ids')
        batch_op.drop_column('new_user_login')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('login_enabled')
