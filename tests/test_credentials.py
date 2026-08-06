"""
Credentials: secret masking, expiry status and route access.

Replaces a 215-line debug script that lived under this name. It wrote 'Test API
Key' rows into whatever database it was pointed at, printed "All tests passed"
unconditionally, and finished by printing an email and password to log in with. It
asserted nothing, and because it contained no test_* functions pytest collected the
file and ran none of it — so the credentials module looked tested while sitting at
17% coverage.
"""
from datetime import timedelta

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel
from src.models.credentials import Credential, CredentialSecret
from src.utils.timezone_helper import now


def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _grant(app, email, access_level):
    """A plain user holding `access_level` on the module that governs credentials."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        module = Module.query.filter_by(slug='core_inventory').first()
        if not module:
            module = Module(name='Core Inventory', slug='core_inventory')
            db.session.add(module)
            db.session.flush()
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        if access_level is not None:
            db.session.add(Permission(module_id=module.id, user_id=user.id,
                                      access_level=access_level))
        db.session.commit()
        permissions_cache.invalidate()


def _credential(app, name='Deploy key', expires_in_days=None, raw_secret='mySecretKey1234'):
    with app.app_context():
        owner = User(name='Owner', email=f'owner-{name}@test.com', role='user')
        owner.set_password('password')
        db.session.add(owner)
        db.session.flush()

        credential = Credential(name=name, type='API Key', owner_id=owner.id,
                                owner_type='User')
        db.session.add(credential)
        db.session.flush()

        secret = CredentialSecret(credential_id=credential.id, is_active=True)
        secret.set_secret(raw_secret)
        if expires_in_days is not None:
            secret.expires_at = now() + timedelta(days=expires_in_days)
        db.session.add(secret)
        db.session.commit()
        return credential.id


# --- masking -----------------------------------------------------------------
#
# The whole premise of the model is that a raw secret never reaches the database,
# so these are the tests that matter most here.

def test_set_secret_keeps_only_the_last_four_characters(init_database):
    secret = CredentialSecret(credential_id=1)
    secret.set_secret('mySecretKey1234')

    assert secret.masked_value == '***********1234'
    assert 'mySecretKey' not in secret.masked_value


def test_masking_is_capped_so_length_does_not_leak(init_database):
    """A long secret must not produce a long mask, or the mask reveals the size."""
    secret = CredentialSecret(credential_id=1)
    secret.set_secret('aVeryLongSecretValue1234')

    assert secret.masked_value == '************1234'
    assert len(secret.masked_value) == 16


def test_short_secrets_are_masked_entirely(init_database):
    """Four characters or fewer would otherwise be published in full."""
    for raw in ('abc', 'abcd', 'a'):
        secret = CredentialSecret(credential_id=1)
        secret.set_secret(raw)
        assert secret.masked_value == '****'


def test_empty_secret_is_masked(init_database):
    secret = CredentialSecret(credential_id=1)
    secret.set_secret('')
    assert secret.masked_value == '****'


def test_the_raw_secret_is_never_stored(app, init_database):
    """Round-trips through the database to be sure nothing else carries the value."""
    raw = 'sup3rS3cretValue9876'
    credential_id = _credential(app, raw_secret=raw)

    with app.app_context():
        secret = db.session.get(Credential, credential_id).active_secret
        stored = {column.name: getattr(secret, column.name)
                  for column in CredentialSecret.__table__.columns}
        assert not any(raw in str(value) for value in stored.values())
        assert stored['masked_value'].endswith('9876')


# --- expiry ------------------------------------------------------------------

def test_a_secret_without_an_expiry_never_expires(init_database):
    secret = CredentialSecret(credential_id=1, masked_value='****')

    assert secret.is_expired is False
    assert secret.days_until_expiry is None
    assert secret.expiry_status == 'active'


def test_expiry_status_thresholds(init_database):
    cases = [
        (-1, 'expired'),
        (3, 'expiring_soon'),
        (7, 'expiring_soon'),
        (20, 'expiring_warning'),
        (30, 'expiring_warning'),
        (60, 'active'),
    ]
    for days, expected in cases:
        secret = CredentialSecret(credential_id=1, masked_value='****',
                                  expires_at=now() + timedelta(days=days, hours=1))
        assert secret.expiry_status == expected, f'{days} days -> {expected}'


def test_is_expired_follows_the_expiry_date(init_database):
    past = CredentialSecret(credential_id=1, masked_value='****',
                            expires_at=now() - timedelta(days=1))
    future = CredentialSecret(credential_id=1, masked_value='****',
                              expires_at=now() + timedelta(days=1))

    assert past.is_expired is True
    assert future.is_expired is False


def test_days_until_expiry_is_negative_once_past(init_database):
    secret = CredentialSecret(credential_id=1, masked_value='****',
                              expires_at=now() - timedelta(days=5))
    assert secret.days_until_expiry < 0


# --- active secret -----------------------------------------------------------

def test_active_secret_ignores_superseded_ones(app, init_database):
    credential_id = _credential(app)

    with app.app_context():
        credential = db.session.get(Credential, credential_id)
        old = credential.active_secret
        old.is_active = False

        replacement = CredentialSecret(credential_id=credential.id, is_active=True)
        replacement.set_secret('rotatedSecret5678')
        db.session.add(replacement)
        db.session.commit()

        assert credential.active_secret.masked_value.endswith('5678')


def test_a_credential_without_secrets_has_no_active_secret(app, init_database):
    with app.app_context():
        owner = User(name='Bare owner', email='bare@test.com', role='user')
        owner.set_password('password')
        db.session.add(owner)
        db.session.flush()

        credential = Credential(name='Bare', type='API Key', owner_id=owner.id,
                                owner_type='User')
        db.session.add(credential)
        db.session.commit()
        assert credential.active_secret is None


# --- routes ------------------------------------------------------------------

def test_list_requires_login(client, init_database):
    response = client.get('/credentials/')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_list_requires_the_module(client, app, init_database):
    _grant(app, 'nocred@test.com', None)
    _login(client, 'nocred@test.com')
    assert client.get('/credentials/').status_code == 302


def test_list_shows_credentials_without_leaking_secrets(auth_client, app, init_database):
    _credential(app, name='Deploy key', raw_secret='mySecretKey1234')

    response = auth_client.get('/credentials/')
    assert response.status_code == 200
    assert b'Deploy key' in response.data
    assert b'mySecretKey' not in response.data


def test_read_only_user_can_list_but_not_create(client, app, init_database):
    _grant(app, 'credreader@test.com', AccessLevel.READ_ONLY)
    _login(client, 'credreader@test.com')

    assert client.get('/credentials/').status_code == 200

    client.post('/credentials/new', data={'name': 'Nope', 'type': 'API Key'},
                follow_redirects=True)
    with app.app_context():
        assert Credential.query.filter_by(name='Nope').first() is None
