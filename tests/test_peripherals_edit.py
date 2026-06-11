"""The peripheral edit form must expose and persist user and location.

These are the most important fields (who has it / where it is) and were missing
from the edit form and its route handling.
"""
from src.models import db, User, Peripheral, Location


def _setup():
    owner = User(name='Owner', email='owner@test.com', role='user')
    owner.set_password('x')
    db.session.add(owner)
    loc = Location(name='HQ Madrid')
    db.session.add(loc)
    db.session.flush()
    p = Peripheral(name='Logi Mouse', status='In Use')
    db.session.add(p)
    db.session.commit()
    return p.id, owner.id, loc.id


def test_edit_form_shows_location_field(auth_client, app):
    with app.app_context():
        pid, _, _ = _setup()
    html = auth_client.get(f'/peripherals/{pid}/edit').data.decode()
    assert 'name="location_id"' in html
    assert 'name="user_id"' in html


def test_edit_persists_user_and_location(auth_client, app):
    with app.app_context():
        pid, owner_id, loc_id = _setup()

    auth_client.post(f'/peripherals/{pid}/edit', data={
        'name': 'Logi Mouse', 'status': 'In Use',
        'user_id': owner_id, 'location_id': loc_id,
    }, follow_redirects=True)

    with app.app_context():
        p = db.session.get(Peripheral, pid)
        assert p.user_id == owner_id
        assert p.location_id == loc_id
