"""The UAR 'Database Query' source: operator SQL against the application's own database.

Before v6.0.15 the guard was a substring blocklist and the source was open to anyone
with read access to the compliance module. These tests pin the layers that replaced it:
shape rules, forbidden identifiers, a connection the engine holds read-only, output
scrubbing, and — at the route — administrators only.
"""
import pytest

from src.extensions import db
from src.models import User
from src.services.readonly_sql import ForbiddenQuery, run_readonly_query, validate_readonly_sql


# --- shape ---------------------------------------------------------------------

@pytest.mark.parametrize('sql', [
    'SELECT name, email FROM "user"',
    'select name from "user";',                       # one trailing separator is fine
    'WITH u AS (SELECT name FROM "user") SELECT * FROM u',
    '  (SELECT name FROM "user")',
])
def test_plain_selects_are_accepted(sql):
    assert validate_readonly_sql(sql)


@pytest.mark.parametrize('sql, reason', [
    ('', 'empty'),
    ('DELETE FROM "user"', 'Only SELECT'),
    ('UPDATE "user" SET role = \'admin\'', 'Only SELECT'),
    ('SELECT 1; DROP TABLE "user"', 'single statement'),
    ('SELECT name FROM "user" -- WHERE role = \'admin\'', 'Comments'),
    ('SELECT name /* hidden */ FROM "user"', 'Comments'),
])
def test_shape_rules(sql, reason):
    with pytest.raises(ForbiddenQuery, match=reason):
        validate_readonly_sql(sql)


# --- identifiers -----------------------------------------------------------------

@pytest.mark.parametrize('sql', [
    'SELECT password_hash FROM "user"',
    'SELECT name FROM "user" WHERE password_hash LIKE \'a%\'',   # blind extraction, one bit at a time
    'SELECT name FROM "user" UNION SELECT api_token FROM "user"',
    'SELECT api_key FROM finance_settings',
    'SELECT table_name FROM information_schema.tables',
    'SELECT sql FROM sqlite_master',
    'SELECT version_num FROM alembic_version',
    'SELECT pg_read_file(\'/etc/passwd\')',
])
def test_secret_bearing_identifiers_are_refused(sql):
    with pytest.raises(ForbiddenQuery, match='forbidden identifier'):
        validate_readonly_sql(sql)


def test_secret_word_inside_a_compound_identifier_is_refused():
    # The identifier check and the output scrub share one word list, so a column that
    # would be dropped from the result cannot be filtered on either.
    with pytest.raises(ForbiddenQuery, match='stripe_api_token'):
        validate_readonly_sql("SELECT name FROM billing WHERE stripe_api_token LIKE 'sk_%'")


def test_secret_words_inside_string_literals_are_data():
    assert validate_readonly_sql("SELECT name FROM note WHERE body = 'password reset token sent'")
    assert validate_readonly_sql("SELECT name FROM note WHERE body = 'it''s a secret'")


def test_select_without_a_space_is_still_a_select():
    assert validate_readonly_sql('SELECT*FROM "user"')


# --- execution -------------------------------------------------------------------

@pytest.fixture
def people(app, init_database):
    with app.app_context():
        for i in range(3):
            u = User(name=f'Person {i}', email=f'p{i}@example.com', role='user')
            u.set_password('pw')
            u.api_token = f'tok-{i}'
            db.session.add(u)
        db.session.commit()


def test_runs_and_returns_dicts(app, people):
    with app.app_context():
        rows = run_readonly_query('SELECT name, email FROM "user" ORDER BY name')
    assert [r['name'] for r in rows] == ['Person 0', 'Person 1', 'Person 2']
    assert set(rows[0]) == {'name', 'email'}


def test_row_cap(app, people):
    with app.app_context():
        assert len(run_readonly_query('SELECT name FROM "user"', max_rows=2)) == 2


def test_secret_columns_are_scrubbed_even_when_aliased(app, people):
    # The identifier rule cannot see through an alias produced by the database itself
    # (SELECT * on a table with a secret column), so the output is filtered by name too.
    with app.app_context():
        rows = run_readonly_query('SELECT * FROM "user"')
    for row in rows:
        assert 'password_hash' not in row
        assert 'api_token' not in row
        assert 'email' in row


def test_write_disguised_as_cte_is_refused_by_the_engine(app, people):
    # Starts with WITH, contains no forbidden word, and would delete every user:
    # the read-only connection is the layer that stops it.
    sql = 'WITH doomed AS (SELECT id FROM "user") DELETE FROM "user" WHERE id IN (SELECT id FROM doomed)'
    with app.app_context():
        with pytest.raises(ValueError, match='Query execution failed'):
            run_readonly_query(sql)
        assert User.query.count() == 3


def test_connection_is_usable_for_writes_afterwards(app, people):
    # The SQLite read-only pragma is per connection and the pool reuses connections.
    with app.app_context():
        run_readonly_query('SELECT 1')
        db.session.add(User(name='Later', email='later@example.com', role='user'))
        db.session.commit()
        assert User.query.filter_by(email='later@example.com').count() == 1


def test_runaway_query_is_interrupted(app, monkeypatch):
    from src.services import readonly_sql
    monkeypatch.setattr(readonly_sql, 'STATEMENT_TIMEOUT_SECONDS', 0.2)
    endless = 'WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c'
    with app.app_context():
        with pytest.raises(ValueError, match='Query execution failed'):
            run_readonly_query(endless)
        # And the connection is healthy afterwards.
        assert run_readonly_query('SELECT 1 AS one') == [{'one': 1}]


# --- who -------------------------------------------------------------------------

def _preview_payload(sql):
    return {
        'source_a_type': 'Database Query', 'source_a_query': sql,
        'source_b_type': 'JSON', 'source_b_json': '[]',
        'mode': 'sql', 'query': 'SELECT * FROM dataset_a',
    }


def test_preview_with_database_query_requires_admin(user_client, app):
    # A compliance user with *write* access: the most privileged non-administrator
    # the module knows, and still not enough.
    from src.models.permissions import AccessLevel, Module, Permission
    from src.services.permissions_service import permissions_cache
    with app.app_context():
        user = User.query.filter_by(email='user@test.com').first()
        module = Module.query.filter_by(slug='compliance').first()
        if not module:
            module = Module(name='compliance', slug='compliance')
            db.session.add(module)
            db.session.flush()
        db.session.add(Permission(module_id=module.id, user_id=user.id, access_level=AccessLevel.WRITE))
        db.session.commit()
        permissions_cache.invalidate()
    response = user_client.post('/compliance/access-review/preview',
                                json=_preview_payload('SELECT name FROM "user"'))
    assert response.status_code == 403
    assert 'administrators' in response.get_json()['error']


def test_preview_with_database_query_as_admin(auth_client):
    response = auth_client.post('/compliance/access-review/preview',
                                json=_preview_payload('SELECT name, email FROM "user"'))
    assert response.status_code == 200, response.data
    assert response.get_json()['success'] is True


def test_automation_form_refuses_forbidden_query_at_save_time(auth_client, app):
    response = auth_client.post('/compliance/uar/automation/new', data={
        'name': 'Leak', 'source_a_type': 'Database Query',
        'source_a_query': 'SELECT password_hash FROM "user"',
        'source_b_type': 'JSON',
    }, follow_redirects=True)
    assert b'was refused' in response.data
    with app.app_context():
        from src.models.uar import UARComparison
        assert UARComparison.query.filter_by(name='Leak').count() == 0
