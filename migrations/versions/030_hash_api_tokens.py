"""hash_api_tokens

API tokens were stored in clear in user.api_token, and every token change was copied
into audit_log.changes by the audit listener, old and new value included.

* user.api_token becomes user.api_token_hash: the SHA-256 of the token. Existing tokens
  are hashed in place, so every integration keeps working with the token it already
  has; the token itself can no longer be displayed, only regenerated.
* audit_log.changes: values of sensitive fields (API tokens, password hashes, secrets,
  connector auth_config, license keys, see src/utils/audit_listener.is_sensitive_field)
  are replaced by "[REDACTED]" in the rows already written.

Downgrade restores the api_token column empty: a hash cannot be turned back into a
token, so users have to generate new ones. Redacted audit values are not restored.

Revision ID: 030
Revises: 029
Create Date: 2026-11-18

"""
import hashlib
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '030'
down_revision = '029'
branch_labels = None
depends_on = None


user_table = sa.table(
    'user',
    sa.column('id', sa.Integer),
    sa.column('api_token', sa.String),
    sa.column('api_token_hash', sa.String),
)

audit_log = sa.table(
    'audit_log',
    sa.column('id', sa.Integer),
    sa.column('changes', sa.Text),
)


def _hash_existing_tokens(bind):
    rows = bind.execute(
        sa.select(user_table.c.id, user_table.c.api_token)
        .where(user_table.c.api_token.isnot(None))
    ).fetchall()
    for user_id, token in rows:
        if not token:
            continue
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        bind.execute(
            user_table.update().where(user_table.c.id == user_id).values(api_token_hash=digest)
        )


def _scrub_audit_log(bind):
    from src.utils.audit_listener import is_sensitive_field, redact_changes

    rows = bind.execute(
        sa.select(audit_log.c.id, audit_log.c.changes).where(audit_log.c.changes.isnot(None))
    ).fetchall()
    for row_id, raw in rows:
        try:
            changes = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(changes, dict) or not any(is_sensitive_field(k) for k in changes):
            continue
        scrubbed = redact_changes(changes)
        if scrubbed != changes:
            bind.execute(
                audit_log.update().where(audit_log.c.id == row_id)
                .values(changes=json.dumps(scrubbed, ensure_ascii=False))
            )


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('api_token_hash', sa.String(length=64), nullable=True))

    bind = op.get_bind()
    _hash_existing_tokens(bind)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_api_token')
        batch_op.drop_column('api_token')
        batch_op.create_index('ix_user_api_token_hash', ['api_token_hash'], unique=True)

    _scrub_audit_log(bind)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_api_token_hash')
        batch_op.drop_column('api_token_hash')
        batch_op.add_column(sa.Column('api_token', sa.String(length=64), nullable=True))
        batch_op.create_index('ix_user_api_token', ['api_token'], unique=True)
