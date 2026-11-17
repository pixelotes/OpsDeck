"""Encryption of API connector secrets at rest, key rotation, and the shared Graph client."""
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from src import db
from src.connectors import msgraph
from src.connectors.microsoft import MicrosoftConnector
from src.models.connectors import (
    ENC_MARKER, ConnectorSubtask, ConnectorTask, decrypt_auth_config, encrypt_auth_config,
)
from src.utils import crypto

AZURE = {
    'AZURE_OAUTH_CLIENT_ID': 'env-client',
    'AZURE_OAUTH_CLIENT_SECRET': 'env-secret',
    'AZURE_OAUTH_TENANT_ID': 'env-tenant',
}


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.ok = 200 <= status < 300
    r.json.return_value = payload or {}
    return r


def _task(service='microsoft', auth_config=None):
    task = ConnectorTask(name=f'{service} sync', service=service, auth_config=auth_config,
                         enabled=True, polling_interval=3600)
    ConnectorSubtask(task=task, name='Users', endpoint='/v1.0/users')
    db.session.add(task)
    db.session.commit()
    return task


# --- crypto -------------------------------------------------------------------------

def test_roundtrip_with_derived_key(app):
    with app.app_context():
        assert crypto.key_source() == 'derived'
        token = crypto.encrypt('s3cret')
        assert token != 's3cret'
        assert crypto.decrypt(token) == 's3cret'


def test_wrong_key_raises_a_clear_error(app, monkeypatch):
    with app.app_context():
        token = crypto.encrypt('s3cret')
        monkeypatch.setitem(app.config, 'SECRET_KEY', 'another-secret-key-entirely-different')
        with pytest.raises(crypto.DecryptionError, match='re-enter the credentials'):
            crypto.decrypt(token)


def test_switching_to_a_dedicated_key_keeps_old_values_readable_until_rotated(app, monkeypatch):
    with app.app_context():
        old_token = crypto.encrypt('legacy')
        new_key = Fernet.generate_key().decode()
        monkeypatch.setitem(app.config, 'DATA_ENCRYPTION_KEY', new_key)
        assert crypto.key_source() == 'dedicated'
        assert crypto.decrypt(old_token) == 'legacy'  # derived key is a decrypt-only fallback
        rotated = crypto.rotate(old_token)
        assert Fernet(new_key.encode()).decrypt(rotated.encode()) == b'legacy'


def test_invalid_dedicated_key_is_reported(app, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'DATA_ENCRYPTION_KEY', 'not-a-fernet-key')
        with pytest.raises(ValueError, match='DATA_ENCRYPTION_KEY'):
            crypto.encrypt('x')


# --- auth_config encryption ---------------------------------------------------------

def test_only_secret_fields_are_encrypted_and_roundtrip(app):
    with app.app_context():
        cfg = {'tenant_id': 't', 'client_secret': 'cs',
               'service_account_json': {'type': 'service_account', 'private_key': 'pk'}}
        enc = encrypt_auth_config(cfg)
        assert enc['tenant_id'] == 't'
        assert set(enc['client_secret']) == {ENC_MARKER}
        assert enc['service_account_json']['$json'] is True
        assert 'pk' not in str(enc) and 'cs' not in str(enc.values())
        assert decrypt_auth_config(enc) == cfg
        assert encrypt_auth_config(enc) == enc  # idempotent: no double encryption


def test_legacy_plaintext_values_still_decrypt(app):
    with app.app_context():
        assert decrypt_auth_config({'api_key': 'plain'}) == {'api_key': 'plain'}
        assert decrypt_auth_config(None) == {}


def test_saved_credentials_are_encrypted_in_the_database(auth_client, app):
    with app.app_context():
        task_id = _task().id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'tenant_id': 't', 'client_id': 'c', 'client_secret': 'super-secret'})
    with app.app_context():
        raw = db.session.execute(
            db.text('SELECT auth_config FROM connector_tasks WHERE id = :id'), {'id': task_id}).scalar()
        assert 'super-secret' not in str(raw)
        assert db.session.get(ConnectorTask, task_id).credentials['client_secret'] == 'super-secret'


def test_rotate_command_reencrypts_under_the_new_key(app, monkeypatch):
    with app.app_context():
        task = _task(service='github')
        task.set_credentials({'access_token': 'ghp_x', 'organization': 'acme'})
        db.session.commit()
        task_id = task.id
        new_key = Fernet.generate_key().decode()
        monkeypatch.setitem(app.config, 'DATA_ENCRYPTION_KEY', new_key)
    result = app.test_cli_runner().invoke(args=['rotate-data-encryption-key'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        stored = db.session.get(ConnectorTask, task_id).auth_config['access_token'][ENC_MARKER]
        assert Fernet(new_key.encode()).decrypt(stored.encode()) == b'ghp_x'


# --- Microsoft connector: reuse the Entra ID app registration -------------------------

def test_use_entra_app_stores_no_secret(auth_client, app, monkeypatch):
    for k, v in AZURE.items():
        monkeypatch.setitem(app.config, k, v)
    with app.app_context():
        task_id = _task(auth_config={'tenant_id': 't', 'client_id': 'c', 'client_secret': 'old'}).id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'use_entra_app': '1'})
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).auth_config == {'use_entra_app': True}


def test_use_entra_app_is_refused_when_not_configured(auth_client, app):
    with app.app_context():
        task_id = _task().id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'use_entra_app': '1'})
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).auth_config is None


def test_credentials_form_offers_entra_app_only_when_configured(auth_client, app, monkeypatch):
    with app.app_context():
        task_id = _task().id
    assert 'id="useEntraApp"' not in auth_client.get(f'/settings/connectors/task/{task_id}').get_data(as_text=True)
    for k, v in AZURE.items():
        monkeypatch.setitem(app.config, k, v)
    assert 'id="useEntraApp"' in auth_client.get(f'/settings/connectors/task/{task_id}').get_data(as_text=True)


def test_microsoft_connector_authenticates_with_entra_app(app, monkeypatch):
    for k, v in AZURE.items():
        monkeypatch.setitem(app.config, k, v)
    with app.app_context():
        task = _task(auth_config={'use_entra_app': True})
        conn = MicrosoftConnector(task, task.subtasks[0])
        with patch.object(conn.session, 'post', return_value=_resp(payload={'access_token': 'tok'})) as post:
            conn.authenticate()
        assert post.call_args[1]['data']['client_secret'] == 'env-secret'
        assert 'env-tenant' in post.call_args[0][0]
        assert conn.session.headers['Authorization'] == 'Bearer tok'


def test_microsoft_connector_uses_decrypted_task_secret(app):
    with app.app_context():
        task = _task()
        task.set_credentials({'tenant_id': 't', 'client_id': 'c', 'client_secret': 'task-secret'})
        conn = MicrosoftConnector(task, task.subtasks[0])
        with patch.object(conn.session, 'post', return_value=_resp(payload={'access_token': 'tok'})) as post:
            conn.authenticate()
        assert post.call_args[1]['data']['client_secret'] == 'task-secret'


def test_microsoft_connector_token_failure_is_a_value_error(app):
    with app.app_context():
        task = _task(auth_config={'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
        conn = MicrosoftConnector(task, task.subtasks[0])
        with patch.object(conn.session, 'post', return_value=_resp(status=401)):
            with pytest.raises(ValueError, match='HTTP 401'):
                conn.authenticate()


# --- shared Graph client --------------------------------------------------------------

def test_graph_token_is_refreshed_after_expiry():
    http = MagicMock()
    http.post.return_value = _resp(payload={'access_token': 't1', 'expires_in': 3600})
    http.get.return_value = _resp(payload={'value': []})
    graph = msgraph.GraphClient('tenant', 'cid', 'secret', session=http)
    with patch('src.connectors.msgraph.time.monotonic', return_value=1000.0):
        graph.get('/users')
        graph.get('/users')
    assert http.post.call_count == 1
    with patch('src.connectors.msgraph.time.monotonic', return_value=1000.0 + 3600):
        graph.get('/users')
    assert http.post.call_count == 2


def test_graph_errors_never_leak_the_secret():
    http = MagicMock()
    http.post.return_value = _resp(status=400, payload={'error_description': 'bad secret super-secret'})
    graph = msgraph.GraphClient('tenant', 'cid', 'super-secret', session=http)
    with pytest.raises(msgraph.GraphError) as exc:
        graph.get('/users')
    assert 'super-secret' not in str(exc.value)


def test_entra_app_credentials_require_single_tenant_and_secret():
    assert msgraph.entra_app_credentials(AZURE) == ('env-tenant', 'env-client', 'env-secret')
    assert msgraph.entra_app_credentials({**AZURE, 'AZURE_OAUTH_TENANT_ID': 'common'}) is None
    assert msgraph.entra_app_credentials({**AZURE, 'AZURE_OAUTH_CLIENT_SECRET': ''}) is None
