"""Helpers for polymorphic owners (a User or a Group stored as owner_type + owner_id).

Forms submit the owner as a single select value: "User-<id>", "Group-<id>" or "" for none.
"""
from ..extensions import db

OWNER_TYPES = ('User', 'Group')


class InvalidOwner(ValueError):
    """The submitted owner value is malformed or points at nothing."""


def owner_value(owner_type, owner_id):
    """The select value for a stored owner ("User-3"), or "" when there is none."""
    return f'{owner_type}-{owner_id}' if owner_type and owner_id else ''


def parse_owner(value, current=(None, None)):
    """Turn a form value into (owner_type, owner_id), checking the target exists.

    Returns (None, None) for an empty value. Archived users are rejected as a *new*
    owner, but `current` (the record's existing owner) is always accepted unchanged, so
    editing a record whose owner was archived later does not fail.
    """
    from ..models.auth import User, Group

    if not value:
        return None, None
    if value == owner_value(*current):
        return current
    owner_type, _, raw_id = value.partition('-')
    if owner_type not in OWNER_TYPES or not raw_id.isdigit():
        raise InvalidOwner(f'Invalid owner: {value!r}')
    owner_id = int(raw_id)
    model = User if owner_type == 'User' else Group
    target = db.session.get(model, owner_id)
    if target is None or getattr(target, 'is_archived', False):
        raise InvalidOwner(f'Owner not found: {value!r}')
    return owner_type, owner_id


def owner_choices():
    """Active users and all groups, for the owner <select>."""
    from ..models.auth import User, Group

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return users, groups
