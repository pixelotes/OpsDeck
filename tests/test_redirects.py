"""Tests for safe_redirect_target — always returns a same-origin relative target.

Regression: behind a reverse proxy, echoing request.url as an absolute redirect
target produced a 302 to an internal host the browser could not follow (offboarding
credential transfer "hung" while the POST had actually succeeded).
"""
from src.utils.redirects import safe_redirect_target


def test_relative_path_preserved_with_query(app):
    with app.test_request_context():
        assert safe_redirect_target('/onboarding/offboarding/view/9') == '/onboarding/offboarding/view/9'
        assert safe_redirect_target('/assets?page=2') == '/assets?page=2'


def test_absolute_same_host_reduced_to_relative(app):
    with app.test_request_context():
        out = safe_redirect_target('https://opsdeck.prod.adhara.zone/onboarding/offboarding/view/9')
        assert out == '/onboarding/offboarding/view/9'


def test_external_host_reduced_to_relative_path(app):
    # Open-redirect-proof: the host is dropped, only our own path remains.
    with app.test_request_context():
        assert safe_redirect_target('https://evil.example/steal') == '/steal'


def test_protocol_relative_drops_host(app):
    with app.test_request_context():
        assert safe_redirect_target('//evil.example/x') == '/x'


def test_javascript_scheme_falls_back(app):
    with app.test_request_context():
        out = safe_redirect_target('javascript:alert(1)')
        assert out.startswith('/') and 'javascript' not in out


def test_crlf_and_backslash_fall_back(app):
    with app.test_request_context():
        assert safe_redirect_target('/ok\r\nSet-Cookie: x=1').startswith('/')
        assert safe_redirect_target('/ok\\evil').startswith('/')
        # both fall back to the dashboard, not the tainted value
        assert '\r' not in safe_redirect_target('/ok\r\nx')


def test_none_and_empty_fall_back(app):
    with app.test_request_context():
        assert safe_redirect_target(None).startswith('/')
        assert safe_redirect_target('').startswith('/')
