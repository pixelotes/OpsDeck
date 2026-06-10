"""Tests for the admin bulk CSV import (users): template, preview, commit."""
import io
from src.models import db, User


def _upload(client, type_key, csv_bytes):
    return client.post(
        f'/admin/import/{type_key}/preview',
        data={'file': (io.BytesIO(csv_bytes), 'data.csv')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )


def test_template_download(auth_client):
    r = auth_client.get('/admin/import/users/template')
    assert r.status_code == 200
    assert 'text/csv' in r.content_type
    body = r.get_data(as_text=True)
    assert body.splitlines()[0] == 'name,email'


def test_preview_classifies_without_persisting(auth_client, app):
    with app.app_context():
        existing = User(name='Existing', email='dup@test.com', role='user')
        existing.set_password('x')
        db.session.add(existing)
        db.session.commit()
        before = User.query.count()

    csv = b'name,email\nNew Person,new@test.com\nDup,dup@test.com\nNoEmail,\n'
    r = _upload(auth_client, 'users', csv)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '1 to create' in body
    assert '1 skipped' in body
    assert '1 error' in body

    with app.app_context():
        assert User.query.count() == before  # preview must NOT create anything


def test_commit_creates_users(auth_client, app):
    csv_text = 'name,email\nAlice Imported,alice.imported@test.com\n'
    r = auth_client.post(
        '/admin/import/users/commit',
        data={'csv_text': csv_text},
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'alice.imported@test.com' in body  # password table shows the new user
    with app.app_context():
        u = User.query.filter_by(email='alice.imported@test.com').first()
        assert u is not None
        assert u.role == 'user'


def test_unknown_type_is_rejected(auth_client):
    r = auth_client.get('/admin/import/bogus/template', follow_redirects=True)
    assert r.status_code == 200
    assert 'Unknown import type' in r.get_data(as_text=True)
