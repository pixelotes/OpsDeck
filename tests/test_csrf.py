"""CSRF is enforced, not merely rendered.

Until v6.0.15 the application set WTF_CSRF_CHECK_DEFAULT = False, which in Flask-WTF
means "check only where a view calls csrf.protect()", and no view did. Every template
rendered a token that nothing ever validated. The shared `app` fixture disables CSRF
for convenience, so these tests build their own application with it on.
"""
import re

import pytest
from sqlalchemy.pool import StaticPool

from src import create_app
from src.extensions import db
from src.models import User


@pytest.fixture
def csrf_app(monkeypatch):
    # Same switch the shared fixture uses: without it Talisman answers every plain-HTTP
    # test request with a redirect to https, before any view (or CSRF check) runs.
    monkeypatch.setenv('OAUTHLIB_INSECURE_TRANSPORT', '1')
    app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}},
        'WTF_CSRF_ENABLED': True,
        'RATELIMIT_ENABLED': False,
        'SECRET_KEY': 'csrf-test-key',
        'MFA_ENABLED': False,
    })
    with app.app_context():
        import src.models  # noqa: F401  ensure every table exists before create_all
        db.create_all()
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        api_user = User(name='API', email='api@test.com', role='admin')
        api_user.api_token = 'api-token-123'
        db.session.add_all([admin, api_user])
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def _token(client, path='/login'):
    """The token as a page exposes it: a hidden field in forms, a <meta> tag for fetch()."""
    html = client.get(path).data.decode()
    match = (re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
             or re.search(r'name="csrf-token" content="([^"]+)"', html))
    assert match, f'{path} should render a CSRF token'
    return match.group(1)


def _flashes(client):
    with client.session_transaction() as sess:
        return [msg for _category, msg in sess.get('_flashes', [])]


def _login(client):
    return client.post('/login', data={
        'email': 'admin@test.com', 'password': 'password', 'csrf_token': _token(client),
    }, follow_redirects=True)


def test_config_checks_every_view_by_default(csrf_app):
    assert csrf_app.config['WTF_CSRF_ENABLED'] is True
    assert csrf_app.config['WTF_CSRF_CHECK_DEFAULT'] is True


def test_form_post_without_token_is_rejected(csrf_client):
    response = csrf_client.post('/login', data={'email': 'admin@test.com', 'password': 'password'})
    assert response.status_code == 302
    assert any('session expired' in m for m in _flashes(csrf_client))
    # And the login did not happen.
    assert csrf_client.get('/').status_code == 302


def test_form_post_with_token_is_accepted(csrf_client):
    _login(csrf_client)
    assert csrf_client.get('/').status_code == 200


def test_json_post_without_token_answers_json_400(csrf_client):
    _login(csrf_client)
    response = csrf_client.post('/search/api/saved-searches', json={'name': 'x', 'query': 'y'})
    assert response.status_code == 400
    assert response.is_json
    assert 'CSRF' in response.get_json()['error']


def test_json_post_with_header_token_passes_csrf(csrf_client):
    _login(csrf_client)
    token = _token(csrf_client, '/')
    response = csrf_client.post('/search/api/saved-searches', json={'name': 'x', 'query': 'y'},
                                headers={'X-CSRFToken': token})
    # Whatever the view answers, it was not the CSRF guard that stopped it.
    assert response.status_code != 400 or 'CSRF' not in (response.get_json() or {}).get('error', '')


def test_bearer_api_is_exempt(csrf_client):
    response = csrf_client.post('/api/v1/users', json={'name': 'New', 'email': 'new@test.com'},
                                headers={'Authorization': 'Bearer api-token-123'})
    assert response.status_code == 201, response.data


def test_bearer_api_still_requires_the_bearer(csrf_client):
    response = csrf_client.post('/api/v1/users', json={'name': 'New', 'email': 'new@test.com'})
    assert response.status_code == 401
