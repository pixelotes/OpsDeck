"""Security tests for HTML sanitization of user-supplied markdown/HTML."""
from src.utils.sanitize import sanitize_html


def test_strips_script_tags():
    out = sanitize_html('<p>hi</p><script>alert(1)</script>')
    assert '<script>' not in out
    assert 'alert(1)' not in out or '<script' not in out
    assert '<p>hi</p>' in out


def test_strips_event_handler_attributes():
    out = sanitize_html('<img src="x" onerror="alert(1)">')
    assert 'onerror' not in out


def test_strips_javascript_protocol_links():
    out = sanitize_html('<a href="javascript:alert(1)">x</a>')
    assert 'javascript:' not in out


def test_strips_iframe():
    out = sanitize_html('<iframe src="https://evil.example"></iframe>')
    assert '<iframe' not in out


def test_preserves_safe_markdown_html():
    out = sanitize_html(
        '<h2>Title</h2><p><strong>bold</strong> and <a href="https://ok.example">link</a></p>'
        '<table><tr><td>cell</td></tr></table><pre><code>x = 1</code></pre>'
    )
    assert '<strong>bold</strong>' in out
    assert 'href="https://ok.example"' in out
    assert '<table>' in out
    assert '<code>' in out


def test_markdown_filter_sanitizes(app):
    """The registered `markdown` Jinja filter must sanitize its output."""
    with app.app_context():
        md = app.jinja_env.filters['markdown']
        rendered = str(md('Hello <script>alert(1)</script> **world**'))
        assert '<script>' not in rendered
        assert '<strong>world</strong>' in rendered
