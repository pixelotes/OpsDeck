"""
API authorization: a token acts with its user's permissions.

Reads stay open to any valid token; writes need WRITE on the module that owns the
data; roles and admin accounts can only be touched by an admin token. Before this,
any token could create an admin or promote its own user through POST /api/v1/users.
"""
import pytest

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel


def _token_user(app, email, token, role='user', module=None, level=AccessLevel.WRITE):
    with app.app_context():
        user = User(name=email, email=email, role=role)
        user.set_api_token(token)
        db.session.add(user)
        db.session.flush()
        if module:
            mod = Module.query.filter_by(slug=module).first()
            if not mod:
                mod = Module(name=module, slug=module)
                db.session.add(mod)
                db.session.flush()
            db.session.add(Permission(module_id=mod.id, user_id=user.id, access_level=level))
        db.session.commit()
    return {'Authorization': f'Bearer {token}'}


def _role(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        return user.role if user else None


# --- Users: privilege escalation -------------------------------------------------

def test_plain_token_cannot_create_an_admin(client, app):
    headers = _token_user(app, 'plain@test.com', 'plain-token')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'evil@test.com', 'name': 'Evil', 'role': 'admin'})
    assert resp.status_code == 403
    assert _role(app, 'evil@test.com') is None


def test_plain_token_cannot_promote_itself(client, app):
    headers = _token_user(app, 'plain@test.com', 'plain-token')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'plain@test.com', 'name': 'Plain', 'role': 'admin'})
    assert resp.status_code == 403
    assert _role(app, 'plain@test.com') == 'user'


def test_plain_token_cannot_create_users_at_all(client, app):
    headers = _token_user(app, 'plain@test.com', 'plain-token')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'new@test.com', 'name': 'New'})
    assert resp.status_code == 403
    assert _role(app, 'new@test.com') is None


def test_administration_writer_creates_users_but_cannot_set_roles(client, app):
    headers = _token_user(app, 'hr@test.com', 'hr-token', module='administration')

    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'new@test.com', 'name': 'New'})
    assert resp.status_code == 201
    assert _role(app, 'new@test.com') == 'user'

    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'new@test.com', 'name': 'New', 'role': 'admin'})
    assert resp.status_code == 403
    assert _role(app, 'new@test.com') == 'user'


def test_administration_writer_cannot_modify_an_admin(client, app):
    headers = _token_user(app, 'hr@test.com', 'hr-token', module='administration')
    _token_user(app, 'boss@test.com', 'boss-token', role='admin')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'boss@test.com', 'name': 'Renamed'})
    assert resp.status_code == 403
    with app.app_context():
        assert User.query.filter_by(email='boss@test.com').first().name == 'boss@test.com'


def test_read_only_administration_cannot_write_users(client, app):
    headers = _token_user(app, 'ro@test.com', 'ro-token', module='administration',
                          level=AccessLevel.READ_ONLY)
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'new@test.com', 'name': 'New'})
    assert resp.status_code == 403


def test_admin_token_sets_roles(client, app):
    headers = _token_user(app, 'root@test.com', 'root-token', role='admin')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'ed@test.com', 'name': 'Ed', 'role': 'editor'})
    assert resp.status_code == 201
    assert _role(app, 'ed@test.com') == 'editor'


def test_upsert_without_role_keeps_the_existing_role(client, app):
    """The schema used to default role to 'user', so any upsert demoted an admin."""
    headers = _token_user(app, 'root@test.com', 'root-token', role='admin')
    _token_user(app, 'other@test.com', 'other-token', role='admin')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'other@test.com', 'name': 'Other', 'department': 'IT'})
    assert resp.status_code == 200
    assert _role(app, 'other@test.com') == 'admin'


def test_unknown_role_is_rejected(client, app):
    headers = _token_user(app, 'root@test.com', 'root-token', role='admin')
    resp = client.post('/api/v1/users', headers=headers,
                       json={'email': 'x@test.com', 'name': 'X', 'role': 'superuser'})
    assert resp.status_code == 422


# --- Other write endpoints -------------------------------------------------------

WRITES = [
    ('/api/v1/changes', 'operations', {'title': 'Patch servers'}),
    ('/api/v1/requests', 'operations', {'title': 'Laptop', 'request_type': 'Hardware'}),
    ('/api/v1/incidents', 'operations', {'title': 'Phishing', 'description': 'Reported mail'}),
    ('/api/v1/onboardings', 'hr_people', {'new_hire_name': 'Ada', 'start_date': '2027-01-04'}),
]


@pytest.mark.parametrize('path,module,payload', WRITES, ids=[w[0] for w in WRITES])
def test_writes_need_module_write_permission(client, app, path, module, payload):
    headers = _token_user(app, 'plain@test.com', 'plain-token')
    assert client.post(path, headers=headers, json=payload).status_code == 403

    ro = _token_user(app, 'ro@test.com', 'ro-token', module=module, level=AccessLevel.READ_ONLY)
    assert client.post(path, headers=ro, json=payload).status_code == 403

    rw = _token_user(app, 'rw@test.com', 'rw-token', module=module)
    resp = client.post(path, headers=rw, json=payload)
    assert resp.status_code == 201, resp.get_json()


# --- Reads stay open -------------------------------------------------------------

@pytest.mark.parametrize('path', ['/api/v1/users', '/api/v1/assets', '/api/v1/changes',
                                  '/api/v1/requests', '/api/v1/suppliers'])
def test_reads_work_for_any_valid_token(client, app, path):
    headers = _token_user(app, 'plain@test.com', 'plain-token')
    assert client.get(path, headers=headers).status_code == 200


# --- Tokens ----------------------------------------------------------------------

def test_archived_users_token_is_refused(client, app):
    headers = _token_user(app, 'gone@test.com', 'gone-token')
    with app.app_context():
        User.query.filter_by(email='gone@test.com').first().is_archived = True
        db.session.commit()
    assert client.get('/api/v1/users', headers=headers).status_code == 401
