"""
Access control on attachments.

download_file used to require nothing but a session, so any account could walk the
id space and pull down every attachment in the system — incident evidence, audit
files, HR documents — no matter which modules it had been granted. Deletion always
checked; downloading did not.
"""
import io
import os

import pytest

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


# --- request size limit ------------------------------------------------------

def test_the_upload_limit_defaults_to_five_megabytes(app):
    assert app.config['MAX_UPLOAD_MB'] == 5
    assert app.config['MAX_CONTENT_LENGTH'] == 5 * 1024 * 1024


def test_the_upload_limit_comes_from_the_environment(monkeypatch):
    from src import create_app

    monkeypatch.setenv('MAX_UPLOAD_MB', '12')
    created = create_app(test_config={'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                      'TESTING': True, 'SECRET_KEY': 'x'})
    assert created.config['MAX_CONTENT_LENGTH'] == 12 * 1024 * 1024


def test_a_nonsense_limit_falls_back_to_the_default(monkeypatch):
    """A typo in the env must not leave the app with no limit at all."""
    from src import create_app

    for value in ('', 'lots', '0', '-3'):
        monkeypatch.setenv('MAX_UPLOAD_MB', value)
        created = create_app(test_config={'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                          'TESTING': True, 'SECRET_KEY': 'x'})
        assert created.config['MAX_CONTENT_LENGTH'] >= 1024 * 1024, value


def test_an_oversized_upload_is_refused_and_writes_nothing(client, app, init_database):
    """A browser form gets a redirect with a flash, as every other upload error does."""
    _user_with(app, 'bigupload@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'bigupload@test.com')

    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        before = set(os.listdir(upload_folder))
        oversized = b'x' * (app.config['MAX_CONTENT_LENGTH'] + 1024)

    response = client.post('/attachments/upload', data={
        'file': (io.BytesIO(oversized), 'huge.pdf'),
        'asset_id': '1',
    }, content_type='multipart/form-data')

    assert response.status_code == 302
    with app.app_context():
        assert set(os.listdir(app.config['UPLOAD_FOLDER'])) == before
        assert Attachment.query.filter_by(filename='huge.pdf').first() is None


def test_the_oversize_redirect_carries_a_message(client, app, init_database):
    _user_with(app, 'bigupload3@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'bigupload3@test.com')

    with app.app_context():
        oversized = b'x' * (app.config['MAX_CONTENT_LENGTH'] + 1024)

    response = client.post('/attachments/upload', data={
        'file': (io.BytesIO(oversized), 'huge.pdf'),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    assert b'too large' in response.data
    assert b'5 MB' in response.data


def test_the_oversize_response_says_what_the_limit_is(client, app, init_database):
    """A bare Werkzeug 413 page tells the user nothing actionable."""
    _user_with(app, 'bigupload2@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'bigupload2@test.com')

    with app.app_context():
        oversized = b'x' * (app.config['MAX_CONTENT_LENGTH'] + 1024)

    response = client.post('/attachments/upload', data={
        'file': (io.BytesIO(oversized), 'huge.pdf'),
        'asset_id': '1',
    }, content_type='multipart/form-data', headers={'Accept': 'application/json'})

    assert response.status_code == 413
    assert '5 MB' in response.get_json()['error']


# --- file type allowlist -----------------------------------------------------
#
# There are two dozen upload sites across thirteen blueprints and none of them
# validated the file type, so the check lives in a before_request hook rather than in
# any one route.

ACCEPTED = ['photo.jpg', 'photo.JPEG', 'scan.png', 'anim.gif', 'texture.tga',
            'bitmap.bmp', 'invoice.pdf', 'notes.odt', 'report.docx', 'export.csv',
            'evidence.zip', 'sheet.xlsx', 'phishing.eml', 'cert.pem', 'photo.heic']

REFUSED = ['payload.exe', 'script.sh', 'macro.bat', 'shell.ps1', 'applet.jar',
           'installer.msi', 'vector.svg', 'page.html', 'noextension']


@pytest.mark.parametrize('filename', ACCEPTED)
def test_accepted_file_types_are_stored(client, app, init_database, filename):
    _user_with(app, f'acc-{filename}@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, f'acc-{filename}@test.com')

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), filename),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert Attachment.query.filter_by(filename=filename).first() is not None


@pytest.mark.parametrize('filename', REFUSED)
def test_refused_file_types_never_reach_the_disk(client, app, init_database, filename):
    """svg and html are refused even though they download rather than render: that
    depends on one argument staying as_attachment=True."""
    _user_with(app, f'ref-{filename}@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, f'ref-{filename}@test.com')

    with app.app_context():
        upload_folder = app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        before = set(os.listdir(upload_folder))

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), filename),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert set(os.listdir(app.config['UPLOAD_FOLDER'])) == before
        assert Attachment.query.count() == 0


def test_a_double_extension_is_judged_by_the_last_one(client, app, init_database):
    """invoice.pdf.exe is an executable, whatever it is trying to look like."""
    _user_with(app, 'double@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'double@test.com')

    client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'invoice.pdf.exe'),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert Attachment.query.count() == 0


def test_the_refusal_lists_what_is_allowed(client, app, init_database):
    _user_with(app, 'listtypes@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'listtypes@test.com')

    response = client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'payload.exe'),
        'asset_id': '1',
    }, content_type='multipart/form-data', follow_redirects=True)

    assert b'not accepted' in response.data
    assert b'pdf' in response.data


def test_the_allowlist_guards_uploads_outside_the_attachments_route(client, app,
                                                                   init_database):
    """The hook is global, so a route with its own file.save() is covered too."""
    from src.models.hiring import HiringStage
    _user_with(app, 'resume@test.com', {'hr_people': AccessLevel.WRITE})
    _login(client, 'resume@test.com')

    with app.app_context():
        stage = HiringStage(name='Applied', order=1)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id
        before = set(os.listdir(app.config['UPLOAD_FOLDER']))

    client.post('/hr/hiring/candidate/new', data={
        'name': 'Mallory', 'email': 'mallory@test.com', 'stage_id': str(stage_id),
        'resume': (io.BytesIO(b'payload'), 'cv.exe'),
    }, content_type='multipart/form-data', follow_redirects=True)

    with app.app_context():
        assert set(os.listdir(app.config['UPLOAD_FOLDER'])) == before


def test_the_allowlist_comes_from_the_environment(monkeypatch):
    from src import create_app

    monkeypatch.setenv('UPLOAD_ALLOWED_EXTENSIONS', 'pdf, .PNG ,csv')
    created = create_app(test_config={'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                                      'TESTING': True, 'SECRET_KEY': 'x'})
    assert created.config['UPLOAD_ALLOWED_EXTENSIONS'] == {'pdf', 'png', 'csv'}


def test_an_api_upload_refusal_is_json(client, app, init_database):
    _user_with(app, 'apitype@test.com', {'core_inventory': AccessLevel.WRITE})
    _login(client, 'apitype@test.com')

    response = client.post('/attachments/upload', data={
        'file': (io.BytesIO(b'payload'), 'payload.exe'),
        'asset_id': '1',
    }, content_type='multipart/form-data', headers={'Accept': 'application/json'})

    assert response.status_code == 415
    assert 'not accepted' in response.get_json()['error']
