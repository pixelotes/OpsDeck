"""Settings the application refuses to run production with.

Two values ship with a placeholder so that a fresh checkout runs without ceremony:
``SECRET_KEY`` and ``DEFAULT_ADMIN_INITIAL_PASSWORD``. Development wants that;
production must never get it. The key signs every session cookie and every CSRF
token, so a known key is an authentication bypass for whoever reads this repository.
Until v6.0.15 nothing checked, and the Helm chart did not even set the variable.

The check lives here rather than inline in ``create_app`` so it can be tested without
building an application, and so the list of what counts as production-unsafe is in one
place when the next placeholder is added.
"""
from typing import List, Mapping

#: The fallbacks create_app uses when the environment says nothing.
PLACEHOLDER_SECRET_KEY = 'your-secret-key-change-this'
PLACEHOLDER_ADMIN_PASSWORD = 'admin123'

#: Anything shorter is not a secret somebody generated; it is a word somebody typed.
MIN_SECRET_KEY_LENGTH = 32

#: Values people put in .env files and forget. Matched case-insensitively.
_KNOWN_PLACEHOLDERS = {
    PLACEHOLDER_SECRET_KEY,
    'change-me', 'change-me-in-production', 'changeme', 'secret', 'dev', 'test',
    'your-very-strong-and-random-secret-key-goes-here',   # from .env.example
}


def secret_key_problem(value) -> str:
    """Why `value` is unacceptable as SECRET_KEY outside development, or '' if it is fine."""
    if not value:
        return 'SECRET_KEY is not set'
    if str(value).strip().lower() in _KNOWN_PLACEHOLDERS:
        return 'SECRET_KEY is still the placeholder value'
    if len(str(value)) < MIN_SECRET_KEY_LENGTH:
        return f'SECRET_KEY is too short ({len(str(value))} characters; at least {MIN_SECRET_KEY_LENGTH} required)'
    return ''


def production_config_errors(config: Mapping) -> List[str]:
    """Settings that must stop the application from starting outside development."""
    errors = []
    problem = secret_key_problem(config.get('SECRET_KEY'))
    if problem:
        errors.append(
            problem + '. Set the SECRET_KEY environment variable to a long random string, '
            'for example the output of: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return errors


def production_config_warnings(config: Mapping) -> List[str]:
    """Settings that are unwise outside development but do not, on their own, break the deployment.

    The default administrator password is here rather than in the errors: the application
    already forces a password change on the first login with the default credentials, so
    an installation that has done that is safe even though the variable was never set.
    """
    warnings = []
    if config.get('DEFAULT_ADMIN_INITIAL_PASSWORD', PLACEHOLDER_ADMIN_PASSWORD) == PLACEHOLDER_ADMIN_PASSWORD:
        warnings.append(
            'DEFAULT_ADMIN_INITIAL_PASSWORD is the placeholder; the first administrator will be '
            'created with a well-known password and forced to change it at first login'
        )
    return warnings
