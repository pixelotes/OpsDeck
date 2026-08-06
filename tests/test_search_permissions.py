"""Search must not return what the user could not reach by navigating.

Both search surfaces are transversal: one request touches models owned by several
different modules, so a @requires_permission on the route cannot express the rule — it
would have to name one module and would either over- or under-refuse. The filtering
therefore lives where the results are produced, keyed on ENTITY_MODULES.

The two surfaces are separate implementations and both are covered here:

* /search/api/search and /search/api/facets go through SearchService;
* /api/search in main.py is a hand-rolled quick search over six models.
"""
import pytest

from src.extensions import db
from src.models import User, Module, Permission, AccessLevel, Asset, Supplier
from src.services.permissions_service import (ENTITY_MODULES, can_read_entity,
                                              readable_modules)


def _user(app, email, role='user', modules=()):
    """A user granted read access to exactly the modules named."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role=role)
        user.set_password('password')
        db.session.add(user)
        db.session.flush()

        for slug in modules:
            module = Module.query.filter_by(slug=slug).first()
            if not module:
                module = Module(name=slug, slug=slug)
                db.session.add(module)
                db.session.flush()
            db.session.add(Permission(module_id=module.id, user_id=user.id,
                                      access_level=AccessLevel.READ_ONLY))
        db.session.commit()
        permissions_cache.invalidate()


def _login(client, email):
    return client.post('/login', data={'email': email, 'password': 'password'},
                       follow_redirects=True)


@pytest.fixture
def searchable(app):
    """One asset and one supplier, owned by core_inventory and procurement."""
    with app.app_context():
        db.session.add(Asset(name='Findable Laptop', serial_number='FIND-1',
                             status='Active', cost=1))
        db.session.add(Supplier(name='Findable Vendor', email='v@findable.com'))
        db.session.commit()


# --- the mapping ------------------------------------------------------------------

def test_every_searchable_entity_has_a_module():
    """An unmapped searchable model is invisible, but it should not get that far."""
    from src.services.search_service import SearchService

    unmapped = [name for name, config in SearchService.SEARCHABLE_ENTITIES.items()
                if config['model'].__name__ not in ENTITY_MODULES]
    assert unmapped == [], (
        f'Searchable entities with no module in ENTITY_MODULES: {unmapped}. They fail '
        'closed, so search silently returns nothing for them.'
    )


def test_an_unmapped_entity_fails_closed():
    """The default has to be "unreadable", or a new model is world-readable on merge."""
    assert can_read_entity('SomethingNobodyClassified', {'core_inventory'}) is False
    # Not even for an admin, whose allowed_modules is None.
    assert can_read_entity('SomethingNobodyClassified', None) is False


def test_an_admin_reads_everything(app, init_database):
    _user(app, 'admin-search@test.com', role='admin')
    with app.app_context():
        user = User.query.filter_by(email='admin-search@test.com').first()
        assert readable_modules(user.id) is None


def test_a_missing_user_reads_nothing(app, init_database):
    """Belt and braces: an unresolvable session must not mean "unrestricted"."""
    with app.app_context():
        assert readable_modules(None) == set()
        assert readable_modules(999999) == set()


# --- SearchService surface --------------------------------------------------------

def test_service_search_only_returns_permitted_entity_types(client, app, init_database,
                                                            searchable):
    """A user holding core_inventory sees assets and not suppliers."""
    _user(app, 'inv@test.com', modules=['core_inventory'])
    _login(client, 'inv@test.com')

    response = client.get('/search/api/search?q=Findable')

    assert response.status_code == 200
    results = response.get_json()['results']
    assert 'assets' in results
    assert 'suppliers' not in results, 'procurement was not granted'
    assert any(r['fields'].get('name') == 'Findable Laptop' for r in results['assets'])


def test_asking_for_a_forbidden_entity_type_returns_nothing(client, app, init_database,
                                                            searchable):
    """Naming the type explicitly must not bypass the filter."""
    _user(app, 'inv2@test.com', modules=['core_inventory'])
    _login(client, 'inv2@test.com')

    response = client.get('/search/api/search?q=Findable&entity_types=suppliers')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['results'] == {}
    assert payload['total_count'] == 0


def test_facets_are_limited_to_permitted_entity_types(client, app, init_database):
    """Facet counts are data too, so they follow the same rule."""
    _user(app, 'facets@test.com', modules=['core_inventory'])
    _login(client, 'facets@test.com')

    forbidden = client.get('/search/api/facets?entity_types=security_incidents')

    assert forbidden.status_code == 200
    assert not forbidden.get_json().get('status'), (
        'status facets were generated for an entity type the user cannot search'
    )


def test_omitting_the_user_searches_nothing(app, init_database, searchable):
    """The service defaults to refusing, so a caller that forgets leaks nothing."""
    from src.services.search_service import get_search_service

    with app.app_context():
        results = get_search_service().search(query='Findable')

    assert results['results'] == {}
    assert results['total_count'] == 0


# --- quick search in main.py -----------------------------------------------------

def test_quick_search_filters_by_module(client, app, init_database, searchable):
    """The other implementation of the same idea, over six models and four modules."""
    _user(app, 'quick@test.com', modules=['core_inventory'])
    _login(client, 'quick@test.com')

    response = client.get('/api/search?q=Findable')

    assert response.status_code == 200
    types = {row['type'] for row in response.get_json()}
    assert 'Asset' in types
    assert 'Supplier' not in types, 'procurement was not granted'


def test_quick_search_returns_nothing_without_any_module(client, app, init_database,
                                                         searchable):
    _user(app, 'nomod-quick@test.com', modules=[])
    _login(client, 'nomod-quick@test.com')

    response = client.get('/api/search?q=Findable')

    assert response.status_code == 200
    assert response.get_json() == []
