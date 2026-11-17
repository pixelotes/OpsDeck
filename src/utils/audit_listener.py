"""
SQLAlchemy event listener for automatic audit logging.

This module registers session-level event listeners that capture all
INSERT, UPDATE, and DELETE operations and record them in the AuditLog table.
"""
import json
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import event, inspect
from flask import has_request_context, request
from flask_login import current_user

# Models to exclude from audit logging (to prevent infinite loops and noise)
EXCLUDED_MODELS = {
    'AuditLog',              # Prevent infinite loop
    'ScheduledCommunication', # High frequency, low value
    'ExchangeRate',           # Daily auto-update
    'NotificationSetting',    # User preferences
}

# Fields whose values must never reach the audit log. They are still recorded, so the
# log shows that a password or token changed, but with the value replaced by REDACTED.
# Matching is by substring as well as by exact name: an exact-name list silently missed
# `api_token` (a substring of nothing in it), and the next secret column will have a new
# name too.
SENSITIVE_FIELDS = {
    'password_hash', 'password', 'secret', 'token', 'api_key', 'api_token',
    'api_token_hash', 'encrypted_value', 'secret_key', 'private_key', 'auth_config',
    'license_key',
}
SENSITIVE_SUBSTRINGS = ('password', 'secret', 'token', 'api_key', 'auth_config')
REDACTED = '[REDACTED]'

REDUNDANT_FIELDS = {
    'created_at', 'updated_at', '_sa_instance_state'
}

EXCLUDED_FIELDS = REDUNDANT_FIELDS


def is_sensitive_field(key):
    """True for a column whose value must be redacted in the audit log."""
    key = key.lower()
    return key in SENSITIVE_FIELDS or any(part in key for part in SENSITIVE_SUBSTRINGS)


def _redact(key, value):
    if value is None or not is_sensitive_field(key):
        return value
    return REDACTED


def redact_changes(changes):
    """Return an audit `changes` dict with every sensitive field's values redacted.

    Used for existing rows (see migration 027) as well as new ones. The key of a
    relationship snapshot is `<relationship>.name`; it is checked as a whole.
    """
    if not isinstance(changes, dict):
        return changes
    redacted = {}
    for key, change in changes.items():
        if isinstance(change, dict) and is_sensitive_field(key):
            change = {k: _redact(key, v) for k, v in change.items()}
        redacted[key] = change
    return redacted


def _get_entity_repr(obj):
    """
    Get a human-readable representation of an entity.

    Tries common name attributes first, falls back to string representation.
    """
    for attr in ('name', 'title', 'email', 'filename', 'code', 'slug', 'description'):
        val = getattr(obj, attr, None)
        if val and isinstance(val, str):
            return str(val)[:255]

    # Fallback to class name + id
    entity_id = getattr(obj, 'id', '?')
    return f"{type(obj).__name__}#{entity_id}"


def _serialize_value(value):
    """
    Serialize a value to a JSON-compatible format.

    Handles dates, decimals, enums, and other special types.
    """
    if value is None:
        return None
    elif isinstance(value, (date, datetime)):
        return value.isoformat()
    elif isinstance(value, Decimal):
        return str(value)
    elif isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    elif hasattr(value, 'value'):  # Enum
        return value.value
    elif hasattr(value, 'name'):  # Enum alternative
        return value.name
    elif isinstance(value, (str, int, float, bool)):
        return value
    else:
        # For complex objects, just return their string representation
        return str(value)


def _get_changes(obj):
    """
    Extract field changes from a modified object.

    Returns a dict of {field_name: {"old": old_value, "new": new_value}}
    """
    changes = {}
    insp = inspect(obj)

    for attr in insp.attrs:
        # Skip relationships and excluded fields
        if attr.key in EXCLUDED_FIELDS:
            continue

        history = attr.load_history()

        # Check if the attribute was modified
        if history.has_changes():
            old_value = history.deleted[0] if history.deleted else None
            new_value = history.added[0] if history.added else None

            # Only track if values actually changed
            if old_value != new_value:
                changes[attr.key] = {
                    'old': _redact(attr.key, _serialize_value(old_value)),
                    'new': _redact(attr.key, _serialize_value(new_value)),
                }

    return changes if changes else None


def _record_change(session, obj, action):
    """
    Record a change to the audit log.

    Accumulates entries in session.info to be written after commit.
    """
    entity_type = type(obj).__name__

    # Skip excluded models
    if entity_type in EXCLUDED_MODELS:
        return

    # Get entity details
    entity_id = getattr(obj, 'id', None)
    entity_repr = _get_entity_repr(obj)

    # Get user info if available
    user_id = None
    user_email = None
    ip_address = None

    if has_request_context():
        if current_user and current_user.is_authenticated:
            user_id = current_user.id
            user_email = current_user.email

        ip_address = request.remote_addr

    # Get changes
    changes_json = None
    if action == 'update':
        changes = _get_changes(obj)
        if changes:
            changes_json = json.dumps(changes, ensure_ascii=False)
        else:
            # If no actual changes, skip the audit entry
            return
    elif action in ('create', 'delete'):
        # Snapshot the entire object state so the event engine can evaluate advanced rules
        snapshot = {}
        insp = inspect(obj)
        for attr in insp.attrs:
            if attr.key in EXCLUDED_FIELDS:
                continue
            # For relationships, capture a display value if present
            is_relationship = False
            try:
                is_relationship = attr.key in insp.mapper.relationships
            except Exception:
                pass

            if is_relationship:
                rel_obj = getattr(obj, attr.key, None)
                if rel_obj:
                    name_val = getattr(rel_obj, 'name', None) or getattr(rel_obj, 'title', None)
                    if name_val:
                        snapshot[attr.key + '.name'] = {'old': None, 'new': name_val} if action == 'create' else {'old': name_val, 'new': None}
            else:
                val = getattr(obj, attr.key, None)
                val = _redact(attr.key, _serialize_value(val))
                snapshot[attr.key] = {'old': None, 'new': val} if action == 'create' else {'old': val, 'new': None}
                
        if snapshot:
            changes_json = json.dumps(snapshot, ensure_ascii=False)
    # Create audit entry dict
    audit_entry = {
        'user_id': user_id,
        'user_email': user_email,
        'ip_address': ip_address,
        'action': action,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'entity_repr': entity_repr,
        'changes': changes_json,
    }

    # Accumulate in session.info to be written after commit
    if '_audit_entries' not in session.info:
        session.info['_audit_entries'] = []

    session.info['_audit_entries'].append(audit_entry)


def _after_flush(session, flush_context):
    """
    SQLAlchemy after_flush event handler.

    Captures all INSERTs, UPDATEs, and DELETEs in the current transaction.
    """
    # Process new objects (INSERTs)
    for obj in session.new:
        _record_change(session, obj, 'create')

    # Process modified objects (UPDATEs)
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            _record_change(session, obj, 'update')

    # Process deleted objects (DELETEs)
    for obj in session.deleted:
        _record_change(session, obj, 'delete')


def _after_commit(session):
    """
    SQLAlchemy after_commit event handler.

    Writes accumulated audit entries to the database after the main
    transaction has been committed successfully.
    """
    audit_entries = session.info.get('_audit_entries', [])

    if not audit_entries:
        return

    # Import here to avoid circular dependency
    from ..models.audit_log import AuditLog
    from src.utils.timezone_helper import now

    try:
        for entry in audit_entries:
            entry['timestamp'] = now()

        # Use a separate connection to avoid "committed state" session error
        bind = session.get_bind()
        with bind.connect() as conn:
            conn.execute(AuditLog.__table__.insert(), audit_entries)
            conn.commit()
    except Exception as e:
        import sys
        print(f"Error writing audit log: {e}", file=sys.stderr)
    finally:
        # Clear the accumulated entries
        session.info['_audit_entries'] = []


def register_audit_listener(db):
    """
    Register SQLAlchemy event listeners for automatic audit logging.

    This should be called once during application initialization.

    Args:
        db: The SQLAlchemy database instance
    """
    # Register the after_flush event to capture changes
    event.listen(db.session, 'after_flush', _after_flush)

    # Register the after_commit event to write audit entries
    event.listen(db.session, 'after_commit', _after_commit)

    print("✓ Audit logging initialized")
