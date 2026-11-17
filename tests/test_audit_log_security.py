"""
Audit log and API token hardening.

* Secrets never reach audit_log.changes (API tokens were stored there in clear).
* API tokens are stored hashed and shown only once.
* The audit detail modal does not parse audited values as HTML.
* "Export to CSV" exports.
"""
import csv
import hashlib
import io
import json
import re
from pathlib import Path

from src.extensions import db
from src.models import User
from src.models.audit_log import AuditLog
from src.utils.audit_listener import REDACTED, is_sensitive_field, redact_changes


def _admin(app):
    with app.app_context():
        return User.query.filter_by(email='admin@test.com').first()


def _all_changes(app):
    with app.app_context():
        return [row.changes for row in AuditLog.query.all() if row.changes]


# --- Audit log redaction ---------------------------------------------------------

def test_generating_a_token_does_not_write_it_to_the_audit_log(auth_client, app):
    resp = auth_client.post('/my-api-key/generate')
    token = re.search(rb'value="([0-9a-f]{64})"', resp.data).group(1).decode()

    changes = _all_changes(app)
    token_rows = [c for c in changes if 'api_token' in c]
    assert token_rows, 'the token change should still be audited, redacted'
    for raw in changes:
        assert token not in raw
        assert hashlib.sha256(token.encode()).hexdigest() not in raw
    assert json.loads(token_rows[-1])['api_token_hash']['new'] == REDACTED


def test_password_hash_is_redacted_on_create(client, app):
    with app.app_context():
        user = User(name='Pw', email='pw@test.com')
        user.set_password('s3cret-pass')
        db.session.add(user)
        db.session.commit()
        password_hash = user.password_hash

    created = [json.loads(c) for c in _all_changes(app)]
    snapshot = next(c for c in created if c.get('email', {}).get('new') == 'pw@test.com')
    assert snapshot['password_hash']['new'] == REDACTED
    assert all(password_hash not in json.dumps(c) for c in created)


def test_sensitive_field_names():
    for name in ('api_token', 'api_token_hash', 'password_hash', 'auth_config', 'api_key',
                 'client_secret', 'license_key', 'secret_key', 'refresh_token'):
        assert is_sensitive_field(name), name
    for name in ('name', 'email', 'role', 'private_key_location', 'entra_oid', 'key_value'):
        assert not is_sensitive_field(name), name


def test_redact_changes_keeps_nulls_and_other_fields():
    changes = {
        'api_token': {'old': 'abc', 'new': 'def'},
        'auth_config': {'old': None, 'new': {'client_secret': 'x'}},
        'name': {'old': 'a', 'new': 'b'},
    }
    assert redact_changes(changes) == {
        'api_token': {'old': REDACTED, 'new': REDACTED},
        'auth_config': {'old': None, 'new': REDACTED},
        'name': {'old': 'a', 'new': 'b'},
    }


# --- Hashed API tokens -----------------------------------------------------------

def test_token_is_stored_hashed_and_shown_once(auth_client, app):
    resp = auth_client.post('/my-api-key/generate')
    assert resp.status_code == 200
    assert resp.headers['Cache-Control'] == 'no-store'
    token = re.search(rb'value="([0-9a-f]{64})"', resp.data).group(1).decode()

    admin = _admin(app)
    assert admin.api_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in admin.api_token_hash

    page = auth_client.get('/my-api-key')
    assert token.encode() not in page.data
    assert b'Token active' in page.data

    assert auth_client.get('/api/v1/users', headers={'Authorization': f'Bearer {token}'}
                           ).status_code == 200
    assert auth_client.get('/api/v1/users',
                           headers={'Authorization': f'Bearer {admin.api_token_hash}'}
                           ).status_code == 401


def test_admin_generated_token_is_shown_once(auth_client, app):
    with app.app_context():
        svc = User(name='Service', email='svc@test.com')
        db.session.add(svc)
        db.session.commit()
        svc_id = svc.id

    resp = auth_client.post(f'/users/{svc_id}/generate-token')
    assert resp.status_code == 200
    token = re.search(rb'value="([0-9a-f]{64})"', resp.data).group(1).decode()

    detail = auth_client.get(f'/users/{svc_id}')
    assert token.encode() not in detail.data
    assert b'Token active' in detail.data
    assert auth_client.get('/api/v1/assets', headers={'Authorization': f'Bearer {token}'}
                           ).status_code == 200


def test_regenerating_invalidates_the_old_token(client, app):
    with app.app_context():
        user = User(name='T', email='t@test.com')
        old = user.generate_token()
        db.session.add(user)
        db.session.commit()
        new = user.generate_token()
        db.session.commit()
    assert client.get('/api/v1/users', headers={'Authorization': f'Bearer {old}'}
                      ).status_code == 401
    assert client.get('/api/v1/users', headers={'Authorization': f'Bearer {new}'}
                      ).status_code == 200


def test_migration_hash_matches_the_model():
    """Migration 030 hashes existing tokens itself; it must agree with User."""
    source = Path(__file__).resolve().parents[1] / 'migrations/versions/030_hash_api_tokens.py'
    assert "hashlib.sha256(token.encode('utf-8')).hexdigest()" in source.read_text()
    assert User.hash_api_token('abc') == hashlib.sha256(b'abc').hexdigest()


# --- XSS in the detail modal -----------------------------------------------------

def test_detail_modal_does_not_render_values_as_html():
    template = (Path(__file__).resolve().parents[1]
                / 'src/templates/admin/audit_log.html').read_text()
    script = template[template.index('function showChanges'):template.index('function exportTableToCSV')]
    # The only innerHTML left is the static loading spinner, set before the fetch.
    assert script.count('innerHTML') == 1
    assert script.index('innerHTML') < script.index('fetch(')
    for value in ('data.entity_repr', 'change.old', 'change.new', 'data.user_email'):
        assert f'${{{value}' not in script


def test_detail_endpoint_returns_raw_values_as_json(auth_client, app):
    payload = '<img src=x onerror=alert(1)>'
    with app.app_context():
        db.session.add(User(name=payload, email='xss@test.com'))
        db.session.commit()
        entry = AuditLog.query.filter_by(entity_repr=payload).first()
        entry_id = entry.id
    resp = auth_client.get(f'/admin/audit-log/{entry_id}/detail')
    assert resp.is_json
    assert resp.get_json()['entity_repr'] == payload


# --- CSV export ------------------------------------------------------------------

def _rows(resp):
    return list(csv.reader(io.StringIO(resp.get_data(as_text=True))))


def test_export_csv_returns_filtered_csv(auth_client, app):
    with app.app_context():
        db.session.add(User(name='=HYPERLINK("http://evil")', email='f@test.com'))
        db.session.commit()

    resp = auth_client.get('/admin/audit-log?export=csv&entity_type=User')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/csv'
    assert 'attachment' in resp.headers['Content-Disposition']

    rows = _rows(resp)
    assert rows[0][:5] == ['Timestamp', 'User', 'IP Address', 'Action', 'Entity Type']
    assert len(rows) > 1
    assert {r[4] for r in rows[1:]} == {'User'}
    # Formula injection is neutralised.
    assert "'=HYPERLINK(\"http://evil\")" in [r[6] for r in rows[1:]]

    none = _rows(auth_client.get('/admin/audit-log?export=csv&entity_type=Nothing'))
    assert len(none) == 1


def test_export_csv_needs_audit_log_access(user_client):
    resp = user_client.get('/admin/audit-log?export=csv')
    assert resp.mimetype != 'text/csv'
