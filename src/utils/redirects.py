"""Safe redirect helpers.

Centralises validation of user-influenced redirect targets (form fields like
`redirect_url` and the `Referer` header) to prevent open redirects — the
"URL redirection from remote source" class flagged by CodeQL/Sonar.
"""
from urllib.parse import urlparse, urlunparse
from flask import url_for


def safe_redirect_target(candidate, fallback=None):
    """Return a safe **same-origin relative** redirect target derived from ``candidate``.

    Any scheme/host in ``candidate`` is discarded — only the path (plus query and
    fragment) is kept. This is open-redirect-proof (you can never be sent off-site)
    and, crucially, avoids emitting an *absolute* ``Location``: behind a reverse
    proxy ``request.host``/``request.url`` may carry an internal scheme/host, and a
    302 to that internal URL is unreachable from the public site — the browser
    hangs while the request actually succeeded. A relative target lets the browser
    resolve it against the real public origin.

    Rejects values with backslashes or CR/LF, non-path schemes (``javascript:``),
    and protocol-relative hosts, falling back to a trusted local URL.

    ``fallback`` defaults to the dashboard (also covers ``candidate`` being ``None``,
    e.g. a missing Referer header).
    """
    if fallback is None:
        fallback = url_for('main.dashboard')

    if not candidate:
        return fallback

    # Characters browsers may normalise into path separators / new requests.
    if any(c in candidate for c in ('\\', '\n', '\r')):
        return fallback

    parsed = urlparse(candidate)

    # Keep only the path component; drop scheme and host entirely so the result
    # is always a same-origin relative URL.
    path = parsed.path or '/'
    if not path.startswith('/') or path.startswith('//'):
        return fallback

    relative = urlunparse(('', '', path, parsed.params, parsed.query, parsed.fragment))
    return relative or fallback
