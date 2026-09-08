"""The application refuses to start in production with a placeholder SECRET_KEY."""
import pytest
from sqlalchemy.pool import StaticPool

from src import create_app
from src.config import (PLACEHOLDER_SECRET_KEY, production_config_errors,
                        production_config_warnings, secret_key_problem)

GOOD_KEY = 'k' * 48


@pytest.mark.parametrize('value, fragment', [
    (None, 'not set'),
    ('', 'not set'),
    (PLACEHOLDER_SECRET_KEY, 'placeholder'),
    ('change-me-in-production', 'placeholder'),          # docker-compose's fallback
    ('Your-Very-Strong-And-Random-Secret-Key-Goes-Here', 'placeholder'),  # .env.example, any case
    ('short', 'too short'),
])
def test_secret_key_rejections(value, fragment):
    assert fragment in secret_key_problem(value)


def test_secret_key_accepted():
    assert secret_key_problem(GOOD_KEY) == ''
    assert production_config_errors({'SECRET_KEY': GOOD_KEY}) == []


def test_default_admin_password_is_a_warning_not_an_error():
    cfg = {'SECRET_KEY': GOOD_KEY}
    assert production_config_errors(cfg) == []
    assert any('DEFAULT_ADMIN_INITIAL_PASSWORD' in w for w in production_config_warnings(cfg))
    assert production_config_warnings({**cfg, 'DEFAULT_ADMIN_INITIAL_PASSWORD': 'something-else'}) == []


def _cfg(**overrides):
    cfg = {
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}},
        'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False, 'MFA_ENABLED': False,
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def production_env(monkeypatch):
    # Nothing that marks the process as development.
    for var in ('OAUTHLIB_INSECURE_TRANSPORT', 'FLASK_ENV', 'FLASK_DEBUG'):
        monkeypatch.delenv(var, raising=False)


def test_production_refuses_placeholder_secret_key(production_env, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', PLACEHOLDER_SECRET_KEY)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app(test_config=_cfg(TESTING=False))


def test_production_starts_with_a_real_secret_key(production_env, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', GOOD_KEY)
    app = create_app(test_config=_cfg(TESTING=False))
    assert app.config['SECRET_KEY'] == GOOD_KEY


def test_development_still_runs_with_the_placeholder(production_env, monkeypatch):
    monkeypatch.setenv('SECRET_KEY', PLACEHOLDER_SECRET_KEY)
    monkeypatch.setenv('OAUTHLIB_INSECURE_TRANSPORT', '1')
    assert create_app(test_config=_cfg(TESTING=False)) is not None


def test_testing_mode_is_exempt(production_env, monkeypatch):
    # The test-suite fixtures pass short keys; they are not deployments.
    monkeypatch.setenv('SECRET_KEY', PLACEHOLDER_SECRET_KEY)
    assert create_app(test_config=_cfg(TESTING=True, SECRET_KEY='k')) is not None
