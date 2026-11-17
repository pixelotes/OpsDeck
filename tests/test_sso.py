"""Tests for the SSO callbacks (Google and Microsoft Entra ID).

The identity providers are never contacted: the Flask-Dance session proxies are
replaced with mocks that return canned userinfo / Microsoft Graph responses.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool

from src import azure_oauth_configured, create_app, db, limiter
from src.models import User

TENANT = '11111111-2222-3333-4444-555555555555'
OID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def _provider(payload=None, status=200, authorized=True, raises=None):
    """A stand-in for flask_dance's ``google`` / ``azure`` session proxy."""
    proxy = MagicMock()
    proxy.authorized = authorized
    if raises:
        proxy.get.side_effect = raises
    else:
        resp = MagicMock()
        resp.ok = 200 <= status < 300
        resp.status_code = status
        resp.json.return_value = payload or {}
        proxy.get.return_value = resp
    return proxy


@pytest.fixture
def sso_app():
    """An app with both Google and Microsoft SSO configured."""
    cfg = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'SECRET_KEY': 'k',
        'MFA_ENABLED': False,
        'GOOGLE_OAUTH_CLIENT_ID': 'google-id',
        'GOOGLE_OAUTH_CLIENT_SECRET': 'google-secret',
        'AZURE_OAUTH_CLIENT_ID': 'azure-id',
        'AZURE_OAUTH_CLIENT_SECRET': 'azure-secret',
        'AZURE_OAUTH_TENANT_ID': TENANT,
    }
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app = create_app(test_config=cfg)
    limiter.enabled = False
    with app.app_context():
        import src.models  # noqa: F401
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sso_client(sso_app):
    return sso_app.test_client()


def _add_user(email, archived=False, entra_oid=None, login_enabled=True):
    user = User(name='SSO User', email=email, role='user', is_archived=archived, entra_oid=entra_oid,
                login_enabled=login_enabled)
    db.session.add(user)
    db.session.commit()
    return user.id


def _azure_login(client, payload=None, **kwargs):
    proxy = _provider(payload, **kwargs)
    with patch('flask_dance.contrib.azure.azure', proxy):
        resp = client.get('/azure/callback')
    return resp, proxy


# --- Configuration -----------------------------------------------------------------

@pytest.mark.parametrize('tenant, expected', [
    (TENANT, True),
    ('contoso.onmicrosoft.com', True),
    ('', False),
    ('common', False),
    ('organizations', False),
    ('Consumers', False),
])
def test_azure_requires_a_single_tenant(tenant, expected):
    cfg = {'AZURE_OAUTH_CLIENT_ID': 'id', 'AZURE_OAUTH_TENANT_ID': tenant}
    assert azure_oauth_configured(cfg) is expected


def test_azure_requires_client_id():
    assert azure_oauth_configured({'AZURE_OAUTH_TENANT_ID': TENANT}) is False


def test_azure_blueprint_uses_configured_tenant(sso_app):
    assert 'azure' in sso_app.blueprints
    with sso_app.test_request_context():
        bp = sso_app.blueprints['azure']
        assert f'/{TENANT}/oauth2/v2.0/authorize' in bp.authorization_url
        assert 'User.Read' in bp.scope


def test_login_page_shows_both_buttons(sso_client):
    html = sso_client.get('/login').get_data(as_text=True)
    assert '/login/google' in html
    assert '/login/azure' in html
    assert 'Iniciar sesión con Microsoft' in html


def test_login_page_hides_buttons_when_unconfigured(client):
    html = client.get('/login').get_data(as_text=True)
    assert 'Iniciar sesión con Microsoft' not in html
    assert 'Iniciar sesión con Google' not in html


def test_azure_login_redirects_to_tenant(sso_client):
    resp = sso_client.get('/login/azure')
    assert resp.status_code == 302
    assert resp.headers['Location'].startswith(
        f'https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize'
    )


# --- Microsoft callback ------------------------------------------------------------

def test_azure_success_matches_upn_and_binds_oid(sso_app, sso_client):
    user_id = _add_user('jane@corp.com')
    resp, proxy = _azure_login(sso_client, {
        'id': OID, 'userPrincipalName': 'Jane@Corp.com', 'mail': 'someone-else@corp.com',
    })

    assert resp.status_code == 302
    assert '/login' not in resp.headers['Location']
    proxy.get.assert_called_once_with('/v1.0/me')
    with sso_client.session_transaction() as sess:
        assert sess['user_id'] == user_id
    assert db.session.get(User, user_id).entra_oid == OID


def test_azure_does_not_match_on_mail(sso_client):
    """The nOAuth case: ``mail`` is admin-editable and must not grant access."""
    _add_user('victim@corp.com')
    _azure_login(sso_client, {
        'id': OID, 'userPrincipalName': 'attacker@corp.com', 'mail': 'victim@corp.com',
    })
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_azure_prefers_bound_oid_over_upn(sso_client):
    """After the first login the oid is trusted even if the UPN was renamed."""
    user_id = _add_user('old-name@corp.com', entra_oid=OID)
    _azure_login(sso_client, {'id': OID, 'userPrincipalName': 'new-name@corp.com'})
    with sso_client.session_transaction() as sess:
        assert sess['user_id'] == user_id


def test_azure_rejects_upn_bound_to_another_oid(sso_client):
    """A recycled UPN with a different object id must not inherit the account."""
    _add_user('jane@corp.com', entra_oid=OID)
    _azure_login(sso_client, {
        'id': '99999999-9999-9999-9999-999999999999', 'userPrincipalName': 'jane@corp.com',
    })
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_azure_unknown_user(sso_client):
    resp, _ = _azure_login(sso_client, {'id': OID, 'userPrincipalName': 'ghost@corp.com'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess
    assert User.query.count() == 0  # no auto-provisioning


def test_azure_archived_user(sso_client):
    _add_user('gone@corp.com', archived=True)
    resp, _ = _azure_login(sso_client, {'id': OID, 'userPrincipalName': 'gone@corp.com'})
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_azure_directory_only_user_refused_and_audited(sso_client):
    user_id = _add_user('dir@corp.com', entra_oid=OID, login_enabled=False)
    with patch('src.routes.main.log_audit') as audit:
        resp, _ = _azure_login(sso_client, {'id': OID, 'userPrincipalName': 'dir@corp.com'})
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess
    kwargs = audit.call_args.kwargs
    assert (kwargs['outcome'], kwargs['target_object'], kwargs['provider']) == \
        ('failure', f'User:{user_id}', 'azure')
    assert 'Login disabled' in kwargs['error_message']


def test_azure_graph_error(sso_client):
    _add_user('jane@corp.com')
    resp, _ = _azure_login(sso_client, status=500)
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_azure_graph_exception(sso_client):
    resp, _ = _azure_login(sso_client, raises=RuntimeError('network down'))
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_azure_not_authorized(sso_client):
    resp, proxy = _azure_login(sso_client, authorized=False)
    assert '/login' in resp.headers['Location']
    proxy.get.assert_not_called()


def test_azure_callback_is_public(sso_client):
    """The callback must be reachable before a session exists (login guard)."""
    resp, proxy = _azure_login(sso_client, authorized=False)
    assert resp.status_code == 302
    assert proxy.authorized is False


# --- Google callback (behaviour must be unchanged) ---------------------------------

def _google_login(client, payload=None, **kwargs):
    proxy = _provider(payload, **kwargs)
    with patch('flask_dance.contrib.google.google', proxy):
        resp = client.get('/google/callback')
    return resp, proxy


def test_google_success(sso_client):
    user_id = _add_user('jane@corp.com')
    resp, proxy = _google_login(sso_client, {'email': 'jane@corp.com'})
    assert resp.status_code == 302
    assert '/login' not in resp.headers['Location']
    proxy.get.assert_called_once_with('/oauth2/v2/userinfo')
    with sso_client.session_transaction() as sess:
        assert sess['user_id'] == user_id
        assert sess['user_role'] == 'user'


def test_google_unknown_user(sso_client):
    resp, _ = _google_login(sso_client, {'email': 'ghost@corp.com'})
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_google_api_error(sso_client):
    resp, _ = _google_login(sso_client, status=401)
    assert '/login' in resp.headers['Location']


def test_google_not_authorized(sso_client):
    resp, proxy = _google_login(sso_client, authorized=False)
    assert '/login' in resp.headers['Location']
    proxy.get.assert_not_called()


def test_google_archived_user_unchanged(sso_client):
    """Google never checked is_archived; the refactor keeps that as-is."""
    user_id = _add_user('gone@corp.com', archived=True)
    _google_login(sso_client, {'email': 'gone@corp.com'})
    with sso_client.session_transaction() as sess:
        assert sess['user_id'] == user_id


def test_google_directory_only_user_refused_and_audited(sso_client):
    user_id = _add_user('dir@corp.com', login_enabled=False)
    with patch('src.routes.main.log_audit') as audit:
        resp, _ = _google_login(sso_client, {'email': 'dir@corp.com'})
    assert '/login' in resp.headers['Location']
    with sso_client.session_transaction() as sess:
        assert 'user_id' not in sess
    kwargs = audit.call_args.kwargs
    assert (kwargs['outcome'], kwargs['target_object'], kwargs['provider']) == \
        ('failure', f'User:{user_id}', 'google')
