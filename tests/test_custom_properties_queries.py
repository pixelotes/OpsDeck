"""custom_properties must not re-query per field, or per object in a collection.

Every template that renders custom fields loops over the definitions and calls
``obj.custom_properties.get(field.name)`` inside the loop. The property ran two queries
each time, so displaying eight custom fields cost sixteen. The UAR user export was worse:
it reads them for every user in the database, two queries apiece.

These tests count the statements that actually touch the custom-field tables, so they
measure the thing that was wrong rather than a total that shifts with unrelated changes.
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from src.extensions import db
from src.models import User
from src.models.core import CustomFieldDefinition, CustomFieldValue


@contextmanager
def custom_field_queries(app):
    """Collect statements issued against the custom-field tables."""
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if 'custom_field' in statement.lower():
            statements.append(statement)

    engine = db.engine
    event.listen(engine, 'before_cursor_execute', record)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', record)


@pytest.fixture
def fields(app):
    """Four custom field definitions on User, and values for two of them."""
    with app.app_context():
        for name in ('github_user', 'desk', 'badge', 'shirt'):
            db.session.add(CustomFieldDefinition(
                entity_type='User', label=name, name=name, field_type='text'))
        db.session.commit()


def _user_with_values(app, email, values):
    with app.app_context():
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()

        for name, value in values.items():
            definition = CustomFieldDefinition.query.filter_by(
                entity_type='User', name=name).first()
            db.session.add(CustomFieldValue(
                field_definition_id=definition.id, linkable_type='User',
                linkable_id=user.id, value=value))
        db.session.commit()
        return user.id


# --- correctness first: the optimisation must not change the answer ----------------

def test_values_and_gaps_are_reported(app, init_database, fields):
    """Every definition appears; the ones without a value are None."""
    user_id = _user_with_values(app, 'props@test.com', {'github_user': 'octocat'})

    with app.app_context():
        user = db.session.get(User, user_id)
        props = user.custom_properties

    assert props['github_user'] == 'octocat'
    assert props['desk'] is None
    assert set(props) == {'github_user', 'desk', 'badge', 'shirt'}


def test_a_write_is_visible_afterwards(app, init_database, fields):
    """The cache must not outlive the value it caches."""
    user_id = _user_with_values(app, 'invalidate@test.com', {'desk': 'old'})

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.custom_properties['desk'] == 'old'

        user.save_custom_properties({'custom_field_desk': 'new'})
        db.session.commit()

        assert user.custom_properties['desk'] == 'new'


# --- the counts -------------------------------------------------------------------

def test_repeated_access_costs_two_queries_not_two_per_field(app, init_database, fields):
    """What the templates do: one read per definition, in a loop."""
    user_id = _user_with_values(app, 'loop@test.com', {'github_user': 'octocat'})

    with app.app_context():
        user = db.session.get(User, user_id)

        with custom_field_queries(app) as statements:
            for name in ('github_user', 'desk', 'badge', 'shirt'):
                user.custom_properties.get(name)

    assert len(statements) == 2, (
        f'Four field reads issued {len(statements)} queries against the custom-field '
        f'tables; expected 2 in total:\n' + '\n'.join(statements)
    )


def test_preloading_a_collection_costs_two_queries_not_two_per_object(app, init_database,
                                                                     fields):
    """What the UAR export does: one read per object, across the whole collection."""
    for index in range(6):
        _user_with_values(app, f'bulk{index}@test.com', {'desk': f'D{index}'})

    with app.app_context():
        users = User.query.filter(User.email.like('bulk%')).all()
        assert len(users) == 6

        with custom_field_queries(app) as statements:
            User.preload_custom_properties(users)
            for user in users:
                user.custom_properties.get('desk')

    assert len(statements) == 2, (
        f'Six objects took {len(statements)} queries; expected 2:\n'
        + '\n'.join(statements)
    )

    # And the values still land on the right objects.
    with app.app_context():
        users = User.query.filter(User.email.like('bulk%')).order_by(User.email).all()
        User.preload_custom_properties(users)
        assert [u.custom_properties['desk'] for u in users] == [f'D{i}' for i in range(6)]


def test_preloading_chunks_its_in_clause(app, init_database, fields, monkeypatch):
    """SQLite caps bound parameters, and this can be handed every user in the database."""
    import src.models.core as core

    for index in range(5):
        _user_with_values(app, f'chunk{index}@test.com', {'badge': f'B{index}'})

    monkeypatch.setattr(core, '_PRELOAD_CHUNK', 2)

    with app.app_context():
        users = User.query.filter(User.email.like('chunk%')).order_by(User.email).all()

        with custom_field_queries(app) as statements:
            User.preload_custom_properties(users)

    # One definitions query plus ceil(5/2) value queries.
    assert len(statements) == 4, '\n'.join(statements)
    assert [u.custom_properties['badge'] for u in users] == [f'B{i}' for i in range(5)]


def test_saving_looks_up_existing_values_once(app, init_database, fields):
    """The writer ran a SELECT per field in the form to find that field's current value.

    Asserted against custom_field_value specifically, because creating a value still
    lazy-loads its definition when the flush populates the backref. That cost scales with
    values created rather than with fields submitted, and it is not what this fixes.
    """
    user_id = _user_with_values(app, 'write@test.com', {'github_user': 'a', 'desk': 'b'})

    with app.app_context():
        user = db.session.get(User, user_id)

        with custom_field_queries(app) as statements:
            user.save_custom_properties({
                'custom_field_github_user': 'x',
                'custom_field_desk': 'y',
                'custom_field_badge': 'z',
                'custom_field_shirt': 'w',
            })
            db.session.commit()

        lookups = [s for s in statements
                   if s.lstrip().upper().startswith('SELECT')
                   and 'FROM custom_field_value' in s]

    assert len(lookups) == 1, (
        f'Saving four fields issued {len(lookups)} lookups against custom_field_value; '
        f'expected 1 for all of them:\n' + '\n'.join(lookups)
    )
