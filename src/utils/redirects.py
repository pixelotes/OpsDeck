"""Safe redirect helpers.

Centralises validation of user-influenced redirect targets (form fields like
`redirect_url` and the `Referer` header) to prevent open redirects — the
"URL redirection from remote source" class flagged by CodeQL/Sonar.
"""
from urllib.parse import urlparse
from flask import request, url_for


def safe_redirect_target(candidate, fallback=None):
    """Return ``candidate`` if it is a safe same-site target, else ``fallback``.

    Accepts:
      - same-site relative paths (e.g. ``/assets/3``), and
      - absolute URLs whose host matches the current request host.
    Rejects external hosts, protocol-relative URLs (``//evil.com``) and any
    value containing backslashes or CR/LF (which browsers may normalise),
    falling back to a trusted local URL instead.

    ``fallback`` defaults to the dashboard when not supplied (also covers the
    case where ``candidate`` is ``None``, e.g. a missing Referer header).
    """
    if fallback is None:
        fallback = url_for('main.dashboard')

    if not candidate:
        return fallback

    # Characters browsers may normalise into path separators / new requests.
    if any(c in candidate for c in ('\\', '\n', '\r')):
        return fallback

    parsed = urlparse(candidate)

    # Relative path: no scheme and no host. Must be a single-slash absolute path
    # ('//host' is protocol-relative and would leave the site).
    if not parsed.scheme and not parsed.netloc:
        if candidate.startswith('/') and not candidate.startswith('//'):
            return candidate
        return fallback

    # Absolute URL: only same-host http(s) is allowed.
    if parsed.scheme in ('http', 'https') and parsed.netloc == request.host:
        return candidate

    return fallback
