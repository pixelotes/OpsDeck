"""Directory-only users (User.login_enabled = False).

They stay in OpsDeck so assets can name them as owner or assignee, but every way in is
refused: password, MFA completion, API token, and an already-open session. Google and
Microsoft SSO are covered in test_sso.py; the Entra sync side in test_entra_sync.py.
"""
from unittest.mock import patch

import pytest

from src import db
from src.models import User


def _user(email, login_enabled=True, password='password', role='user', **kw):
    user = User(name=email.split('@')[0].title(), email=email, role=role,
                login_enabled=login_enabled, **kw)
    if password:
        user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def test_new_users_can_sign_in_by_default(app, init_database):
    user = User(name='Ana', email='ana@corp.com')
    db.session.add(user)
    db.session.commit()
    assert user.login_enabled is True


# --- Password login ----------------------------------------------------------------

def test_password_login_refused_and_audited(client, app):
    user = _user('dir@corp.com', login_enabled=False)
    with patch('src.routes.main.log_audit') as audit, \
            patch('src.notifications.send_email') as send:
        resp = client.post('/login', data={'email': 'dir@corp.com', 'password': 'password'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'mfa_user_id' not in sess
    audit.assert_called_once()
    kwargs = audit.call_args.kwargs
    assert (kwargs['outcome'], kwargs['target_object']) == ('failure', f'User:{user.id}')
    assert 'Login disabled' in kwargs['error_message']
    send.assert_not_called()


def test_password_login_refused_before_mfa_email(client, app):
    """With MFA on, a new IP would email a code: a directory-only user must get none."""
    _user('dir@corp.com', login_enabled=False)
    app.config['MFA_ENABLED'] = True
    try:
        with patch('src.notifications.send_email') as send:
            client.post('/login', data={'email': 'dir@corp.com', 'password': 'password'})
    finally:
        app.config['MFA_ENABLED'] = False
    send.assert_not_called()
    with client.session_transaction() as sess:
        assert 'mfa_user_id' not in sess


def test_wrong_password_message_unchanged_for_directory_only(client, app):
    _user('dir@corp.com', login_enabled=False)
    resp = client.post('/login', data={'email': 'dir@corp.com', 'password': 'nope'},
                       follow_redirects=True)
    assert 'Invalid email or password' in resp.get_data(as_text=True)


def test_mfa_completion_refused_if_access_removed_meanwhile(client, app):
    user = _user('dir@corp.com', login_enabled=False)
    with client.session_transaction() as sess:
        sess['mfa_user_id'] = user.id
        sess['mfa_otp'] = '123456'
        sess['mfa_expiry'] = 9999999999
    resp = client.post('/mfa-verify', data={'code': '123456'})
    assert '/login' in resp.headers['Location']
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'mfa_user_id' not in sess


def test_open_session_ends_when_access_removed(client, app):
    user = _user('ana@corp.com')
    client.post('/login', data={'email': 'ana@corp.com', 'password': 'password'})
    assert client.get('/change-password').status_code == 200

    user.login_enabled = False
    db.session.commit()
    resp = client.get('/change-password')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


# --- API token ---------------------------------------------------------------------

def test_api_token_refused(client, app):
    user = _user('dir@corp.com', login_enabled=False, password=None)
    user.api_token = 'dir-token'
    db.session.commit()
    resp = client.get('/api/v1/users', headers={'Authorization': 'Bearer dir-token'})
    assert resp.status_code == 401

    user.login_enabled = True
    db.session.commit()
    resp = client.get('/api/v1/users', headers={'Authorization': 'Bearer dir-token'})
    assert resp.status_code == 200


# --- Admin screens -----------------------------------------------------------------

def test_admin_list_shows_badge_and_toggle(auth_client, app):
    dir_user = _user('dir@corp.com', login_enabled=False, password=None)
    html = auth_client.get('/admin/users').get_data(as_text=True)
    assert 'Directory only' in html
    assert f'/admin/users/{dir_user.id}/toggle-login' in html

    with patch('src.routes.admin.log_audit') as audit:
        resp = auth_client.post(f'/admin/users/{dir_user.id}/toggle-login')
    assert resp.status_code == 302
    assert db.session.get(User, dir_user.id).login_enabled is True
    assert audit.call_args.kwargs['event_type'] == 'user.login_access'
    assert audit.call_args.kwargs['login_enabled'] is True

    auth_client.post(f'/admin/users/{dir_user.id}/toggle-login')
    assert db.session.get(User, dir_user.id).login_enabled is False


def test_admin_cannot_remove_own_access(auth_client, app):
    admin = User.query.filter_by(email='admin@test.com').one()
    auth_client.post(f'/admin/users/{admin.id}/toggle-login')
    assert db.session.get(User, admin.id).login_enabled is True


def test_break_glass_admin_keeps_access(auth_client, app):
    break_glass = _user(app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com'), role='admin')
    auth_client.post(f'/admin/users/{break_glass.id}/toggle-login')
    assert db.session.get(User, break_glass.id).login_enabled is True


def test_toggle_requires_admin_write(user_client, app):
    target = _user('dir@corp.com', login_enabled=False, password=None)
    user_client.post(f'/admin/users/{target.id}/toggle-login')
    assert db.session.get(User, target.id).login_enabled is False


def test_admin_edit_page_shows_state(auth_client, app):
    dir_user = _user('dir@corp.com', login_enabled=False, password=None)
    html = auth_client.get(f'/admin/users/{dir_user.id}/edit').get_data(as_text=True)
    assert 'Directory only' in html
    assert 'Allow sign-in' in html


def test_people_screens_show_badge(auth_client, app):
    dir_user = _user('dir@corp.com', login_enabled=False, password=None)
    assert 'Directory only' in auth_client.get('/users/').get_data(as_text=True)
    assert 'Directory only' in auth_client.get(f'/users/{dir_user.id}').get_data(as_text=True)


@pytest.mark.parametrize('url', ['/assets/new', '/peripherals/new', '/licenses/new'])
def test_owner_and_assignee_pickers_list_directory_only_users(auth_client, app, url):
    dir_user = _user('dir@corp.com', login_enabled=False, password=None)
    html = auth_client.get(url).get_data(as_text=True)
    assert f'value="{dir_user.id}"' in html
