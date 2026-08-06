import pytest
import os
import tempfile
from src import create_app, db, limiter
from src.models import User

# --- Guard: migration testing must not be switchable off in silence ---------------
#
# The tests in tests/test_migrations.py skip unless DATABASE_URL points at a disposable
# Postgres, because they drop the public schema. That skip is correct locally and a lie
# in CI, where it produces a green job that verified nothing.
#
# The canary inside that file checks the *environment*. This checks the *outcome*: that
# the tests actually ran. Deleting the class, marking it skip, or letting the job's
# command drift all leave the environment perfectly valid, and pytest exits 0 on a run
# that skipped everything. Set REQUIRE_MIGRATION_TESTS=1 in the job that is meant to run
# them and those failures become loud.
MIGRATION_TEST_FILE = 'test_migrations.py'
MIGRATION_ENV_CANARY = 'test_the_environment_is_configured_in_ci'
MINIMUM_MIGRATION_TESTS = 4

_migration_tests_passed = 0
_migration_tests_skipped = []


def pytest_runtest_logreport(report):
    """Tally outcomes of the migration tests, ignoring the environment canary.

    The canary skips by design when CI is unset, so counting it would defeat the check.
    Skips are reported during setup, passes during the call phase.
    """
    if MIGRATION_TEST_FILE not in report.nodeid or MIGRATION_ENV_CANARY in report.nodeid:
        return

    global _migration_tests_passed
    if report.skipped:
        _migration_tests_skipped.append(report.nodeid)
    elif report.when == 'call' and report.passed:
        _migration_tests_passed += 1


def pytest_sessionfinish(session, exitstatus):
    """Fail the session when migration tests were required but did not run."""
    if os.environ.get('REQUIRE_MIGRATION_TESTS') != '1':
        return

    problems = []
    if _migration_tests_skipped:
        problems.append(
            f'{len(_migration_tests_skipped)} migration test(s) were skipped: '
            + ', '.join(_migration_tests_skipped)
        )
    if _migration_tests_passed < MINIMUM_MIGRATION_TESTS:
        problems.append(
            f'only {_migration_tests_passed} migration test(s) passed, expected at '
            f'least {MINIMUM_MIGRATION_TESTS}. Were they deleted, renamed out of '
            f'collection, or is the job no longer running {MIGRATION_TEST_FILE}?'
        )
    if not problems:
        return

    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    if reporter is not None:
        reporter.write_sep('=', 'REQUIRE_MIGRATION_TESTS not satisfied', red=True)
        for problem in problems:
            reporter.write_line(problem)


@pytest.fixture(scope='session')
def app():
    """Session-scoped Flask application instance for the tests."""
    # Disable HTTPS for tests
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Temporary directory for uploads
    tmpdir = tempfile.mkdtemp()
    
    # Define test configuration BEFORE creating the app
    # Use StaticPool to persist in-memory DB across connections/threads
    from sqlalchemy.pool import StaticPool
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "poolclass": StaticPool,
            "connect_args": {"check_same_thread": False},
        },
        "WTF_CSRF_ENABLED": False,
        "RATELIMIT_ENABLED": False,
        "SECRET_KEY": "test-secret-key",
        "UPLOAD_FOLDER": tmpdir,
        "MFA_ENABLED": False
    }
    
    # Create app with test configuration
    app = create_app(test_config=test_config)
    
    # This works even if the app was initialized with RATELIMIT_ENABLED=True
    limiter.enabled = False

    with app.app_context():
        # Ensure all models are imported before create_all()
        # This prevents "table not found" errors if models are lazily imported
        import src.models  # noqa
        db.create_all()
        yield app
        db.drop_all()
    
    import shutil
    try:
        shutil.rmtree(tmpdir)
    except:
        pass

@pytest.fixture(scope='function')
def init_database(app):
    """
    Resets the database for each test.

    The permissions cache is cleared alongside it. It is a module-level singleton keyed
    by user id, so without this it survives drop_all() and goes on describing rows that
    no longer exist: a test that granted permissions to user 2 would silently hand them
    to whatever user 2 happens to be in the next test.
    """
    from src.services.permissions_cache import permissions_cache

    with app.app_context():
        db.drop_all()
        db.create_all()
        permissions_cache.invalidate()

        # Make sure UPLOAD_FOLDER exists
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        yield db

        permissions_cache.invalidate()

@pytest.fixture(scope='function')
def client(app, init_database):
    """A test client for the application."""
    return app.test_client()

@pytest.fixture(scope='function')
def auth_client(client, app):
    """
    Un cliente de pruebas autenticado como administrador.
    """
    with app.app_context():
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    yield client

@pytest.fixture(scope='function')
def user_client(client, app):
    """
    Un cliente de pruebas autenticado como usuario normal.
    """
    with app.app_context():
        # An admin may also be needed depending on the app, but this fixture creates the user
        user = User(name='Test User', email='user@test.com', role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

    client.post('/login', data={
        'email': 'user@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    yield client