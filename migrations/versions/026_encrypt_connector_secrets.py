"""encrypt_connector_secrets

API connector credentials (connector_tasks.auth_config) were stored as plain JSON:
client secrets, AWS secret keys, API tokens and Google service-account keys readable by
anyone with database or backup access. From now on the secret fields are stored as
Fernet tokens (see src/utils/crypto.py and src/models/connectors.py); this migration
encrypts the values already in the table. Non-secret fields are left as they are.

The key is DATA_ENCRYPTION_KEY, or one derived from SECRET_KEY when that is unset, so
this migration must run with the same environment as the application.

Downgrade decrypts them back to plaintext.

Revision ID: 026
Revises: 025
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '026'
down_revision = '025'
branch_labels = None
depends_on = None


tasks = sa.table(
    'connector_tasks',
    sa.column('id', sa.Integer),
    sa.column('auth_config', sa.JSON),
)


def _rewrite(transform):
    bind = op.get_bind()
    rows = bind.execute(sa.select(tasks.c.id, tasks.c.auth_config)).fetchall()
    for task_id, cfg in rows:
        if not cfg:
            continue
        new_cfg = transform(cfg)
        if new_cfg != cfg:
            bind.execute(tasks.update().where(tasks.c.id == task_id).values(auth_config=new_cfg))


def upgrade():
    from src.models.connectors import encrypt_auth_config
    _rewrite(encrypt_auth_config)


def downgrade():
    from src.models.connectors import decrypt_auth_config
    _rewrite(decrypt_auth_config)
