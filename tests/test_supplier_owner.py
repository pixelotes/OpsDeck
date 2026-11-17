"""Supplier owner: model property, create/edit form handling, rendering and CSV import."""
import pytest

from src.models import db, Supplier, User
from src.models.auth import Group
from src.services import import_service as imp


@pytest.fixture
def people(app, auth_client):
    """An active user, an archived user and a group (ids only, to cross app contexts)."""
    with app.app_context():
        alice = User(name='Alice Owner', email='alice@test.com', role='user')
        bob = User(name='Bob Gone', email='bob@test.com', role='user', is_archived=True)
        for u in (alice, bob):
            u.set_password('x')
        team = Group(name='IT Ops')
        db.session.add_all([alice, bob, team])
        db.session.commit()
        return {'alice': alice.id, 'bob': bob.id, 'team': team.id}


def _form(**extra):
    data = {'name': 'Acme', 'compliance_status': 'Pending'}
    data.update(extra)
    return data


def test_owner_property_resolves_user_group_and_none(app, people):
    with app.app_context():
        s = Supplier(name='A', owner_type='User', owner_id=people['alice'])
        assert s.owner.name == 'Alice Owner'
        s.owner_type, s.owner_id = 'Group', people['team']
        assert s.owner.name == 'IT Ops'
        s.owner_type, s.owner_id = None, None
        assert s.owner is None


def test_create_supplier_with_group_owner(auth_client, app, people):
    r = auth_client.post('/suppliers/new', data=_form(owner=f"Group-{people['team']}"))
    assert r.status_code == 302
    with app.app_context():
        s = Supplier.query.filter_by(name='Acme').one()
        assert (s.owner_type, s.owner_id) == ('Group', people['team'])


def test_create_supplier_without_owner(auth_client, app, people):
    r = auth_client.post('/suppliers/new', data=_form(owner=''))
    assert r.status_code == 302
    with app.app_context():
        assert Supplier.query.filter_by(name='Acme').one().owner is None


@pytest.mark.parametrize('value', ['User-99999', 'Robot-1', 'User-abc', 'garbage'])
def test_invalid_owner_is_rejected(auth_client, app, people, value):
    r = auth_client.post('/suppliers/new', data=_form(owner=value))
    assert r.status_code == 400
    with app.app_context():
        assert Supplier.query.filter_by(name='Acme').count() == 0


def test_archived_user_cannot_become_owner(auth_client, app, people):
    r = auth_client.post('/suppliers/new', data=_form(owner=f"User-{people['bob']}"))
    assert r.status_code == 400


def test_edit_changes_and_clears_owner(auth_client, app, people):
    with app.app_context():
        s = Supplier(name='Acme', owner_type='User', owner_id=people['alice'])
        db.session.add(s)
        db.session.commit()
        sid = s.id
    auth_client.post(f'/suppliers/{sid}/edit', data=_form(owner=f"Group-{people['team']}"))
    with app.app_context():
        assert db.session.get(Supplier, sid).owner_type == 'Group'
    auth_client.post(f'/suppliers/{sid}/edit', data=_form(owner=''))
    with app.app_context():
        assert db.session.get(Supplier, sid).owner is None


def test_edit_keeps_owner_that_was_archived_later(auth_client, app, people):
    """An archived owner stays selectable on edit, so saving other fields does not fail or drop it."""
    with app.app_context():
        s = Supplier(name='Acme', owner_type='User', owner_id=people['bob'])
        db.session.add(s)
        db.session.commit()
        sid = s.id
    page = auth_client.get(f'/suppliers/{sid}/edit').get_data(as_text=True)
    assert 'Bob Gone (archived)' in page
    r = auth_client.post(f'/suppliers/{sid}/edit', data=_form(name='Acme Renamed', owner=f"User-{people['bob']}"))
    assert r.status_code == 302
    with app.app_context():
        s = db.session.get(Supplier, sid)
        assert s.name == 'Acme Renamed'
        assert (s.owner_type, s.owner_id) == ('User', people['bob'])


def test_owner_shown_in_list_and_detail(auth_client, app, people):
    with app.app_context():
        s = Supplier(name='Acme', owner_type='User', owner_id=people['alice'])
        db.session.add(s)
        db.session.commit()
        sid = s.id
    for url in ('/suppliers/', f'/suppliers/{sid}'):
        body = auth_client.get(url).get_data(as_text=True)
        assert 'list-person' in body and 'Alice Owner' in body, url


def test_import_resolves_owner_by_email_or_group_name(app, people):
    with app.app_context():
        csv_text = ('name,owner\n'
                    'ByEmail,ALICE@test.com\n'
                    'ByGroup,IT Ops\n'
                    'NoOwner,\n'
                    'Unknown,nobody@test.com\n'
                    'Archived,bob@test.com\n')
        res = imp.process('suppliers', csv_text, commit=True)
        assert res['counts'] == {'create': 3, 'skip': 0, 'error': 2}
        assert Supplier.query.filter_by(name='ByEmail').one().owner_id == people['alice']
        assert Supplier.query.filter_by(name='ByGroup').one().owner_type == 'Group'
        assert Supplier.query.filter_by(name='NoOwner').one().owner is None
        assert Supplier.query.filter_by(name='Unknown').count() == 0


def test_edit_form_does_not_render_none_for_empty_fields(auth_client, app, people):
    """Empty optional fields used to render as the text 'None', which a save wrote back."""
    with app.app_context():
        s = Supplier(name='Acme')
        db.session.add(s)
        db.session.commit()
        sid = s.id
    page = auth_client.get(f'/suppliers/{sid}/edit').get_data(as_text=True)
    assert '>None</textarea>' not in page
    assert 'value="None"' not in page
