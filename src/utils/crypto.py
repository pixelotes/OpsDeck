"""Symmetric encryption for secrets stored in the database (Fernet: AES-128-CBC + HMAC).

Key material, in order of preference:

1. ``DATA_ENCRYPTION_KEY``: one or more Fernet keys separated by commas. The first key
   encrypts; all of them decrypt, so a key can be rotated by prepending the new one and
   running ``flask rotate-data-encryption-key`` before dropping the old one. The
   SECRET_KEY-derived key (below) is always tried last for decryption, so switching
   from it to a dedicated key is the same operation: set the key, run the command.
   Generate one with ``python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"``.
2. Otherwise a key derived from ``SECRET_KEY`` with HKDF. This keeps existing
   deployments working, but ties stored secrets to the session key: rotating
   SECRET_KEY then makes them undecryptable (they must be re-entered). Production
   deployments should set DATA_ENCRYPTION_KEY.

Values are read from the Flask config when an app context exists (tests, requests,
Alembic via Flask-Migrate) and from the environment otherwise.
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_HKDF_INFO = b'opsdeck-data-encryption-v1'
DEFAULT_SECRET_KEY = 'your-secret-key-change-this'


class DecryptionError(Exception):
    """A stored value cannot be decrypted with the configured keys."""


def _setting(name, default=None):
    try:
        from flask import current_app
        return current_app.config.get(name, os.environ.get(name, default))
    except RuntimeError:  # no app context
        return os.environ.get(name, default)


def _derived_key(secret_key):
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        secret_key.encode('utf-8'))
    return base64.urlsafe_b64encode(raw)


def key_source():
    """'dedicated' when DATA_ENCRYPTION_KEY is set, else 'derived' (from SECRET_KEY)."""
    return 'dedicated' if (_setting('DATA_ENCRYPTION_KEY') or '').strip() else 'derived'


def _fernet():
    configured = [k.strip() for k in (_setting('DATA_ENCRYPTION_KEY') or '').split(',') if k.strip()]
    derived = Fernet(_derived_key(_setting('SECRET_KEY', DEFAULT_SECRET_KEY)))
    if configured:
        try:
            keys = [Fernet(k.encode('ascii')) for k in configured]
        except (ValueError, TypeError) as exc:
            raise ValueError('DATA_ENCRYPTION_KEY must hold valid Fernet keys (comma-separated).') from exc
        # The SECRET_KEY-derived key stays last as a decrypt-only fallback, so values
        # written before DATA_ENCRYPTION_KEY was introduced remain readable until
        # `flask rotate-data-encryption-key` re-encrypts them under the new key.
        return MultiFernet(keys + [derived])
    return MultiFernet([derived])


def encrypt(value):
    """Encrypt a str; returns the token as str."""
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt(token):
    """Decrypt a token produced by encrypt()."""
    try:
        return _fernet().decrypt(token.encode('ascii')).decode('utf-8')
    except InvalidToken as exc:
        raise DecryptionError(
            'A stored secret cannot be decrypted with the current key. If SECRET_KEY or '
            'DATA_ENCRYPTION_KEY changed, re-enter the credentials.') from exc


def rotate(token):
    """Re-encrypt a token under the current primary key (MultiFernet.rotate)."""
    try:
        return _fernet().rotate(token.encode('ascii')).decode('ascii')
    except InvalidToken as exc:
        raise DecryptionError('Cannot rotate a token that no configured key decrypts.') from exc
