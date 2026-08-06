"""
Access control on attachments.

download_file used to require nothing but a session, so any account could walk the
id space and pull down every attachment in the system — incident evidence, audit
files, HR documents — no matter which modules it had been granted. Deletion always
checked; downloading did not.
"""
import io
import os

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel, Attachment
from src.routes.attachments import ATTACHMENT_PERMISSIONS, UPLOAD_TARGETS


def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _user_with(app, email, grants):
    """Create a plain user holding `grants`, a {module_slug: AccessLevel} mapping."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()

        for slug, level in grants.items():
            module = Module.query.filter_by(slug=slug).first()
            if not module:
                module = Module(name=slug, slug=slug)
                db.session.add(module)
                db.session.flush()
            db.session.add(Permission(module_id=module.id, user_id=user.id,
                                      access_level=level))
        db.session.commit()
        permissions_cache.invalidate()


def _attachment(app, linkable_type, name='evidence.pdf'):
    """An attachment row with a real file behind it."""
    with app.app_context():
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        stored = f'stored-{linkable_type}.pdf'
        with open(os.path.join(app.config['UPLOAD_FOLDER'], stored), 'wb') as handle:
            handle.write(b'%PDF-1.4 test')

        attachment = Attachment(filename=name, secure_filename=stored,
                                linkable_id=1, linkable_type=linkable_type)
        db.session.add(attachment)
        db.session.commit()
        return attachment.id


# --- the mapping itself ------------------------------------------------------

def test_every_upload_target_has_a_permission_mapping():
    """A form field that cannot be resolved to a module would refuse every upload."""
    unmapped = [t for t in UPLOAD_TARGETS.values() if t not in ATTACHMENT_PERMISSIONS]
    assert unmapped == []


def test_permission_mapping_points_at_real_modules(app, init_database):
    """Guards against a typo silently locking a whole object type out."""
    from src.seeder_prod import seed_modules
    with app.app_context():
        seed_modules()
        known = {m.slug for m in Module.query.all()}
        assert set(ATTACHMENT_PERMISSIONS.values()) <= known


# --- download ----------------------------------------------------------------

def test_download_requires_login(client, app, init_database):
    attachment_id = _attachment(app, 'SecurityIncident')
    response = client.get(f'/attachments/download/{attachment_id}')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_download_refused_without_the_governing_module(client, app, init_database):
    """The core of the fix: read access somewhere else is not read access here."""
    attachment_id = _attachment(app, 'SecurityIncident')          # governed by operations
    _user_with(app, 'reader@test.com', {'knowledge_policy': AccessLevel.READ_ONLY})
    _login(client, 'reader@test.com')

    response = client.get(f'/attachments/download/{attachment_id}')
    assert response.status_code == 403


def test_download_allowed_with_read_access_to_the_module(client, app, init_database):
    attachment_id = _attachment(app, 'SecurityIncident')
    _user_with(app, 'ops@test.com', {'operations': AccessLevel.READ_ONLY})
    _login(client, 'ops@test.com')

    response = client.get(f'/attachments/download/{attachment_id}')
    assert response.status_code == 200
    assert response.data.startswith(b'%PDF')


def test_download_allowed_for_admins(auth_client, app, init_database):
    attachment_id = _attachment(app, 'SecurityIncident')
    assert auth_client.get(f'/attachments/download/{attachment_id}').status_code == 200


def test_download_refused_for_an_unmapped_type(client, app, init_database):
    """An object type nobody mapped is refused rather than served to everyone."""
    attachment_id = _attachment(app, 'SomethingNobodyMapped')
    _user_with(app, 'anyone@test.com', {'operations': AccessLevel.WRITE})
    _login(client, 'anyone@test.com')

    assert client.get(f'/attachments/download/{attachment_id}').status_code == 403


def test_download_is_scoped_per_module(client, app, init_database):
    """Holding one module does not open the attachments of another."""
    incident = _attachment(app, 'SecurityIncident')               # operations
    contract = _attachment(app, 'Contract')                      # procurement
    _user_with(app, 'proc@test.com', {'procurement': AccessLevel.READ_ONLY})
    _login(client, 'proc@test.com')

    assert client.get(f'/attachments/download/{contract}').status_code == 200
    assert client.get(f'/attachments/download/{incident}').status_code == 403


# --- delete ------------------------------------------------------------------

def test_delete_refused_with_read_only_access(client, app, init_database):
    attachment_id = _attachment(app, 'SecurityIncident')
    _user_with(app, 'opsreader@test.com', {'operations': AccessLevel.READ_ONLY})
    _login(client, 'opsreader@test.com')

    client.post(f'/attachments/delete/{attachment_id}', follow_redirects=True)
    with app.app_context():
        assert db.session.get(Attachment, attachment_id) is not None


def test_delete_allowed_with_write_access(client, app, init_database):
    attachment_id = _attachment(app, 'SecurityIncident')
    _user_with(app, 'opswriter@test.com', {'operations': AccessLevel.WRITE})
    _login(client, 'opswriter@test.com')

    client.post(f'/attachments/delete/{attachment_id}', follow_redirects=True)
    with app.app_context():
        assert db.session.get(Attachment, attachment_id) is None


# --- upload ------------------------------------------------------------------

def test_upload_refused_without_write_access_leaves_no_file(client, app, init_database):
    """The check now runs before the save, so a refused upload writes nothing."""
    _user_with(app, 'uploadreader@test.com', {'core_inventory': AccessLevel.READ_ONLY})
    _login(client, 'uploadreader@test.com')

    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        before = set(os.listdir(upload_folder))

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'sneaky.pdf'),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert set(os.listdir(app.config['UPLOAD_FOLDER'])) == before
        assert Attachment.query.filter_by(filename='sneaky.pdf').first() is None


def test_upload_with_an_unknown_target_writes_nothing(client, app, init_database):
    _user_with(app, 'uploadwriter@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'uploadwriter@test.com')

    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        before = set(os.listdir(upload_folder))

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'orphan.pdf'),
        'unknown_thing_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert set(os.listdir(app.config['UPLOAD_FOLDER'])) == before
        assert Attachment.query.filter_by(filename='orphan.pdf').first() is None


def test_upload_succeeds_with_write_access(client, app, init_database):
    _user_with(app, 'assetwriter@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'assetwriter@test.com')

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'manual.pdf'),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        attachment = Attachment.query.filter_by(filename='manual.pdf').one()
        assert attachment.linkable_type == 'Asset'
        assert os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'],
                                           attachment.secure_filename))
