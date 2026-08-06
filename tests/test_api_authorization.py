"""
In-app JSON endpoints must refuse in JSON.

requires_permission answers a denial with flash() + redirect(), which is right for a
browser navigation and wrong for a fetch() caller: it receives a 302 to an HTML page
and parses it as though it were the payload, so the failure is silent. The
authentication half of this was fixed in the global login guard; these are the
authorization denials, which kept redirecting.

Every endpoint below returns only JSON — none renders a template — so the whole
surface is covered by one table rather than one test per route.
"""
import pytest

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel


# (path, method, module slug that governs it)
JSON_ENDPOINTS = [
    ('/security/audits/api/search-linkable?q=x&type=Asset', 'get', 'compliance'),
    ('/compliance/drift/api/timeline/1', 'get', 'compliance'),
    ('/documentation/api/search?q=x', 'get', 'knowledge_policy'),
    ('/frameworks/api/search-controls?q=x', 'get', 'compliance'),
    ('/onboarding/api/packs', 'get', 'hr_people'),
    ('/onboarding/api/users', 'get', 'hr_people'),
    ('/risk/api/items/Asset', 'get', 'risk_governance'),
    ('/risk/api/references/Policy', 'get', 'risk_governance'),
    ('/risk-assessments/api/linkable-objects/Asset', 'get', 'risk_governance'),
    ('/services/api/search-components/Asset?q=x', 'get', 'core_inventory'),
    ('/subscriptions/api/calendar-events?start=2027-01-01&end=2027-03-31', 'get',
     'core_inventory'),
    ('/compliance/drift/api/detect', 'post', 'compliance'),
    ('/compliance/drift/api/snapshot', 'post', 'compliance'),
    ('/security/audits/api/control/1/status', 'post', 'compliance'),
    ('/evaluations/api/1/update_status', 'post', 'procurement'),
]

IDS = [f'{method.upper()} {path.split("?")[0]}' for path, method, _ in JSON_ENDPOINTS]


def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _user_holding(app, email, slug):
    """A plain user granted read access to exactly one module."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()

        if slug is not None:
            module = Module.query.filter_by(slug=slug).first()
            if not module:
                module = Module(name=slug, slug=slug)
                db.session.add(module)
                db.session.flush()
            db.session.add(Permission(module_id=module.id, user_id=user.id,
                                      access_level=AccessLevel.READ_ONLY))
        db.session.commit()
        permissions_cache.invalidate()


@pytest.mark.parametrize('path,method,slug', JSON_ENDPOINTS, ids=IDS)
def test_authorization_denial_is_json(client, app, init_database, path, method, slug):
    """A user without the governing module gets 403 JSON, not a redirect to HTML."""
    # Granted an unrelated module, so the request is authenticated but not authorised.
    other = 'settings' if slug != 'settings' else 'administration'
    _user_holding(app, f'denied-{abs(hash(path))}@test.com', other)
    _login(client, f'denied-{abs(hash(path))}@test.com')

    response = getattr(client, method)(path)

    assert response.status_code == 403, f'{path} answered {response.status_code}'
    assert response.is_json, f'{path} answered with {response.content_type}'
    assert response.get_json().get('error')


@pytest.mark.parametrize('path,method,slug', JSON_ENDPOINTS, ids=IDS)
def test_unauthenticated_access_is_json(client, init_database, path, method, slug):
    """The global guard already covers this; pinned so it cannot regress either."""
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.is_json


def test_a_denial_never_answers_with_html(client, app, init_database):
    """The specific failure mode: a 302 whose body a fetch() caller would parse as data."""
    _user_holding(app, 'htmlcheck@test.com', 'settings')
    _login(client, 'htmlcheck@test.com')

    for path, method, _ in JSON_ENDPOINTS:
        response = getattr(client, method)(path)
        assert response.status_code != 302, f'{path} redirected'
        assert b'<!DOCTYPE' not in response.data[:200].upper().replace(b'!doctype', b'!DOCTYPE')


def test_holding_the_module_is_still_allowed(client, app, init_database):
    """The read endpoints must keep working for someone who does hold the module."""
    readable = [(p, m, s) for p, m, s in JSON_ENDPOINTS if m == 'get']
    for path, method, slug in readable:
        _user_holding(app, f'allowed-{abs(hash(path))}@test.com', slug)
        _login(client, f'allowed-{abs(hash(path))}@test.com')

        response = getattr(client, method)(path)
        assert response.status_code != 403, f'{path} refused a user holding {slug}'
        assert response.status_code != 302, f'{path} redirected a user holding {slug}'
