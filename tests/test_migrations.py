"""
Database migration integration tests.

These tests verify that Alembic migrations apply cleanly against a real
PostgreSQL database. They require DATABASE_URL to point to a Postgres
instance (the CI workflow provides one automatically).

WARNING: every test in here runs ``DROP SCHEMA public CASCADE`` against
DATABASE_URL, before and after itself. They must therefore only ever run against
a throwaway database, and they refuse to run against anything else.

The guard is the database *name*: it has to contain "test" (CI uses
``opsdeck_test``). This is what stops a plain ``pytest tests/`` inside the
development container — where DATABASE_URL points at the development database —
from silently wiping it. Set ALLOW_DESTRUCTIVE_DB_TESTS=1 to run them against a
disposable database whose name does not say so.

Skipped when DATABASE_URL is not set, points to SQLite, or is not disposable — except
in CI, where a skip would mean migration testing had been switched off without anyone
noticing. Two guards cover that: test_the_environment_is_configured_in_ci below checks
the environment is usable, and REQUIRE_MIGRATION_TESTS (see tests/conftest.py) checks
the tests below actually ran.
"""
import os
import pytest
from urllib.parse import urlsplit
from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.environ.get('DATABASE_URL', '')


def _is_disposable(url):
    """True when the target database is safe to drop: its name says it is a test DB."""
    if os.environ.get('ALLOW_DESTRUCTIVE_DB_TESTS') == '1':
        return True
    return 'test' in urlsplit(url).path.lstrip('/').lower()


DESTRUCTIVE_ALLOWED = _is_disposable(DATABASE_URL)

requires_postgres = pytest.mark.skipif(
    'postgresql' not in DATABASE_URL or not DESTRUCTIVE_ALLOWED,
    reason='Requires a disposable PostgreSQL database: set DATABASE_URL to one whose '
           'name contains "test", or set ALLOW_DESTRUCTIVE_DB_TESTS=1. These tests '
           'drop the public schema, so they never run against a database that is not '
           'marked as throwaway.'
)


def test_the_environment_is_configured_in_ci():
    """Fail, rather than skip, when CI cannot run the tests below.

    A skipped suite and a passing one look identical in a green build. The four tests
    below skip unless DATABASE_URL points at a disposable Postgres, which is correct
    locally — they drop the schema. In CI that same skip would quietly disable migration
    testing altogether: rename the CI database, drop ALLOW_DESTRUCTIVE_DB_TESTS, and the
    job still reports success having verified nothing.

    This is the canary. It is deliberately not marked with requires_postgres, so it runs
    whatever the configuration, and it only asserts when CI is set.
    """
    if not os.environ.get('CI'):
        pytest.skip('Enforced in CI only; skipping locally is the intended behaviour.')

    assert 'postgresql' in DATABASE_URL, (
        'DATABASE_URL must point at PostgreSQL for the migration job, and it is '
        f'{DATABASE_URL!r}. The four migration tests would have skipped silently.'
    )
    assert DESTRUCTIVE_ALLOWED, (
        'The migration job needs a disposable database: name containing "test", or '
        'ALLOW_DESTRUCTIVE_DB_TESTS=1. Neither is set, so the four migration tests '
        'would have skipped silently.'
    )


def _make_app():
    """Create a Flask app configured for migration testing."""
    from src import create_app, limiter
    app = create_app(test_config={
        'SQLALCHEMY_DATABASE_URI': DATABASE_URL,
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test',
        'RATELIMIT_ENABLED': False,
    })
    limiter.enabled = False
    return app


def _clean_db(engine):
    """Drop all tables so migrations start from scratch.

    Re-checks the guard rather than trusting the skipif: this function destroys a
    schema, so it should be impossible to reach by accident if someone calls it
    directly or removes the marker from a test.
    """
    if not DESTRUCTIVE_ALLOWED:
        raise RuntimeError(
            'Refusing to drop the schema of a database that is not marked as '
            f'disposable: {urlsplit(DATABASE_URL).path.lstrip("/") or "<unset>"}'
        )
    with engine.connect() as conn:
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.commit()


@requires_postgres
class TestMigrations:

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create app, engine, and clean DB before each test."""
        self.app = _make_app()
        self.engine = create_engine(DATABASE_URL)
        _clean_db(self.engine)
        yield
        _clean_db(self.engine)
        self.engine.dispose()

    def _upgrade(self, revision='head'):
        with self.app.app_context():
            from flask_migrate import upgrade
            upgrade(revision=revision)

    def _downgrade(self, revision='base'):
        with self.app.app_context():
            from flask_migrate import downgrade
            downgrade(revision=revision)

    def test_upgrade_head(self):
        """Migrations apply cleanly from empty DB to head."""
        self._upgrade()

        inspector = inspect(self.engine)
        tables = inspector.get_table_names()

        # Sanity check: core tables exist
        assert 'user' in tables
        assert 'asset' in tables
        assert 'alembic_version' in tables

        # Verify alembic_version matches the current head of the script directory,
        # not a hardcoded revision (which would rot on every new migration).
        with self.app.app_context():
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            cfg = Config('migrations/alembic.ini')
            cfg.set_main_option('script_location', 'migrations')
            expected_head = ScriptDirectory.from_config(cfg).get_current_head()

        with self.engine.connect() as conn:
            result = conn.execute(text('SELECT version_num FROM alembic_version')).fetchone()
            assert result is not None
            assert result[0] == expected_head

    def test_downgrade_base(self):
        """Migrations can be fully rolled back."""
        self._upgrade()
        self._downgrade()

        inspector = inspect(self.engine)
        tables = inspector.get_table_names()

        # Only alembic_version should remain (Alembic doesn't drop it)
        user_tables = [t for t in tables if t != 'alembic_version']
        assert len(user_tables) == 0, f"Tables left after downgrade: {user_tables}"

    def test_upgrade_is_idempotent(self):
        """Running upgrade twice doesn't fail."""
        self._upgrade()
        self._upgrade()

        inspector = inspect(self.engine)
        assert 'user' in inspector.get_table_names()

    def test_models_match_migrations(self):
        """
        After applying migrations, the DB schema should match the models.
        If autogenerate detects differences, models and migrations are out of sync.
        """
        self._upgrade()

        with self.app.app_context():
            from src.extensions import db
            from alembic.autogenerate import compare_metadata
            from alembic.migration import MigrationContext

            with self.engine.connect() as conn:
                migration_ctx = MigrationContext.configure(conn)
                diff = compare_metadata(migration_ctx, db.metadata)

            # Ignore 'remove_table' diffs — these are tables from optional
            # plugins (e.g. opsdeck-enterprise) that exist in migrations
            # but whose models aren't installed in this environment.
            meaningful = [d for d in diff if d[0] != 'remove_table']

            if meaningful:
                changes = "\n".join(f"  - {d}" for d in meaningful)
                pytest.fail(
                    f"Models and migrations are out of sync.\n"
                    f"Detected {len(meaningful)} difference(s):\n{changes}"
                )
