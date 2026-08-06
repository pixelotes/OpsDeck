"""
Email bodies must not be able to run script inside the app.

EmailTemplate.body_html and Campaign.body_html are authored in a WYSIWYG editor and
were stored exactly as submitted, then rendered on the campaign detail page with |safe.
Anyone who could edit a campaign could therefore run script in the session of any admin
who opened it — a privilege escalation from communications-writer to admin.

The bodies legitimately contain HTML and Jinja placeholders, so escaping them is not an
option: they are sanitised instead, on save and again on render.
"""
import pytest

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel
from src.models.communications import Campaign, EmailTemplate
from src.utils.sanitize import sanitize_email_html


PAYLOADS = [
    '<script>alert(1)</script>',
    '<img src=x onerror="alert(1)">',
    '<p onclick="alert(1)">click me</p>',
    '<a href="javascript:alert(1)">link</a>',
    '<iframe src="https://evil.test"></iframe>',
    '<object data="evil.swf"></object>',
    '<embed src="evil.swf">',
    '<form action="https://evil.test"><input name="p"></form>',
    '<svg onload="alert(1)"></svg>',
    '<body onload="alert(1)">',
    '<div style="behavior:url(evil.htc)">x</div>',
    '<div style="background:url(javascript:alert(1))">x</div>',
]


def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _user_with(app, email, slug, level=AccessLevel.WRITE):
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        module = Module.query.filter_by(slug=slug).first()
        if not module:
            module = Module(name=slug, slug=slug)
            db.session.add(module)
            db.session.flush()
        db.session.add(Permission(module_id=module.id, user_id=user.id,
                                  access_level=level))
        db.session.commit()
        permissions_cache.invalidate()


# --- the sanitiser itself ----------------------------------------------------

@pytest.mark.parametrize('payload', PAYLOADS)
def test_executable_content_is_removed(payload):
    cleaned = sanitize_email_html(f'<p>hello</p>{payload}')

    lowered = cleaned.lower()
    for marker in ('<script', '<iframe', '<object', '<embed', '<form', '<svg',
                   'onerror', 'onclick', 'onload', 'javascript:', 'behavior'):
        assert marker not in lowered, f'{marker!r} survived in {cleaned!r}'
    assert '<p>hello</p>' in cleaned


def test_email_layout_survives():
    """These bodies are table-and-inline-style HTML; stripping that would break them."""
    body = ('<table style="width:100%; background-color:#f4f4f4" cellpadding="10" '
            'border="0"><tbody><tr><td align="center" valign="top">'
            '<h2 style="color:#2E5F9E">Title</h2>'
            '<img src="https://x/logo.png" width="120" alt="logo">'
            '</td></tr></tbody></table>')
    cleaned = sanitize_email_html(body)

    for fragment in ('<table', 'cellpadding="10"', 'align="center"', 'valign="top"',
                     'background-color', 'color', '<img', 'width="120"', 'alt="logo"'):
        assert fragment in cleaned, f'{fragment!r} was stripped'


def test_jinja_placeholders_are_untouched():
    """Sanitising on save is only viable if it does not corrupt the templating."""
    body = ('<p>Hello {{ new_hire_name }}, starting {{ start_date }}.</p>'
            '{% if manager %}<p>Manager: {{ manager.name }}</p>{% endif %}'
            '{% for item in items %}<li>{{ item }}</li>{% endfor %}'
            '<a href="{{ event_url }}">Open</a>')
    cleaned = sanitize_email_html(body)

    for fragment in ('{{ new_hire_name }}', '{{ start_date }}', '{% if manager %}',
                     '{% endif %}', '{% for item in items %}', '{{ item }}',
                     'href="{{ event_url }}"'):
        assert fragment in cleaned, f'{fragment!r} was corrupted'


def test_http_links_and_mailto_survive():
    cleaned = sanitize_email_html(
        '<a href="https://opsdeck.test/x">a</a><a href="mailto:a@b.test">b</a>')
    assert 'https://opsdeck.test/x' in cleaned
    assert 'mailto:a@b.test' in cleaned


def test_empty_input_is_returned_as_is():
    assert sanitize_email_html('') == ''
    assert sanitize_email_html(None) is None


# --- save path ---------------------------------------------------------------

def test_a_campaign_body_is_sanitised_on_save(client, app, init_database):
    _user_with(app, 'campaigner@test.com', 'communications')
    _login(client, 'campaigner@test.com')

    client.post('/campaigns/new', data={
        'title': 'Newsletter',
        'subject': 'Hi',
        'body_html': '<p>Hello</p><script>alert(1)</script>',
    }, follow_redirects=True)

    with app.app_context():
        campaign = Campaign.query.filter_by(title='Newsletter').first()
        assert campaign is not None
        assert '<script' not in campaign.body_html
        assert '<p>Hello</p>' in campaign.body_html


def test_an_email_template_body_is_sanitised_on_save(client, app, init_database):
    _user_with(app, 'templater@test.com', 'hr_people')
    _login(client, 'templater@test.com')

    client.post('/admin/communications/templates/new', data={
        'name': 'Welcome',
        'subject': 'Welcome {{ new_hire_name }}',
        'body_html': '<p>Hi {{ new_hire_name }}</p><img src=x onerror="alert(1)">',
    }, follow_redirects=True)

    with app.app_context():
        template = EmailTemplate.query.filter_by(name='Welcome').first()
        assert template is not None
        assert 'onerror' not in template.body_html
        assert '{{ new_hire_name }}' in template.body_html


# --- render path -------------------------------------------------------------

def test_a_body_stored_before_the_fix_is_cleaned_on_render(client, app, init_database):
    """Rows written before sanitising existed are still displayed safely."""
    _user_with(app, 'viewer@test.com', 'communications', AccessLevel.READ_ONLY)

    with app.app_context():
        campaign = Campaign(title='Legacy', subject='Hi', status='Draft',
                            body_html='<p>ok</p><img src=x onerror="alert(1)">')
        db.session.add(campaign)
        db.session.commit()
        campaign_id = campaign.id

    _login(client, 'viewer@test.com')
    response = client.get(f'/campaigns/{campaign_id}')

    assert response.status_code == 200
    assert b'onerror' not in response.data
    assert b'<p>ok</p>' in response.data
