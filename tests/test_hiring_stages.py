"""
Hiring stage management routes.

Written alongside the ruff rollout: F821 (undefined name) reported that new_stage
used `name` and `is_hired_stage` without ever reading them off the form, so every
POST raised NameError and returned a 500. The route had no test at all, which is
why a completely broken endpoint could sit there unnoticed.
"""
from src.extensions import db
from src.models import User, Module, Permission, AccessLevel
from src.models.hiring import HiringStage


def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def _grant(app, email, access_level):
    """A plain user holding `access_level` on the HR module."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        module = Module.query.filter_by(slug='hr_people').first()
        if not module:
            module = Module(name='HR & People', slug='hr_people')
            db.session.add(module)
            db.session.flush()
        user = User(name=email, email=email, role='user')
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        if access_level is not None:
            db.session.add(Permission(module_id=module.id, user_id=user.id,
                                      access_level=access_level))
        db.session.commit()
        permissions_cache.invalidate()


def test_create_stage(auth_client, app, init_database):
    response = auth_client.post('/hr/hiring/stages/new',
                                data={'name': 'Technical interview'},
                                follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        stage = HiringStage.query.filter_by(name='Technical interview').one()
        assert stage.is_hired_stage is False


def test_create_stage_reads_the_hired_flag(auth_client, app, init_database):
    auth_client.post('/hr/hiring/stages/new',
                     data={'name': 'Offer accepted', 'is_hired_stage': 'on'},
                     follow_redirects=True)

    with app.app_context():
        assert HiringStage.query.filter_by(name='Offer accepted').one().is_hired_stage is True


def test_create_stage_requires_a_name(auth_client, app, init_database):
    auth_client.post('/hr/hiring/stages/new', data={'name': '   '}, follow_redirects=True)
    with app.app_context():
        assert HiringStage.query.count() == 0


def test_create_stage_appends_to_the_end(auth_client, app, init_database):
    """Order is auto-assigned as last + 1, so stages arrive in creation order."""
    for name in ('Screening', 'Interview', 'Offer'):
        auth_client.post('/hr/hiring/stages/new', data={'name': name},
                         follow_redirects=True)

    with app.app_context():
        stages = HiringStage.query.order_by(HiringStage.order).all()
        assert [s.name for s in stages] == ['Screening', 'Interview', 'Offer']


def test_create_stage_needs_write_access(client, app, init_database):
    _grant(app, 'hrreader@test.com', AccessLevel.READ_ONLY)
    _login(client, 'hrreader@test.com')

    client.post('/hr/hiring/stages/new', data={'name': 'Nope'}, follow_redirects=True)
    with app.app_context():
        assert HiringStage.query.count() == 0


def test_create_stage_requires_the_module(client, app, init_database):
    _grant(app, 'hroutsider@test.com', None)
    _login(client, 'hroutsider@test.com')

    response = client.post('/hr/hiring/stages/new', data={'name': 'Nope'})
    assert response.status_code == 302
    with app.app_context():
        assert HiringStage.query.count() == 0


# --- deletion guards ---------------------------------------------------------
#
# These replace tests/verify_hiring_locking.py, a script that ran against the real
# database, printed its findings and asserted nothing — its own comments conceded it
# was "assuming the route protection works if we read the code". The protection is
# real, so it is worth testing rather than assuming.

def test_delete_stage(auth_client, app, init_database):
    auth_client.post('/hr/hiring/stages/new', data={'name': 'Take-home task'},
                     follow_redirects=True)
    with app.app_context():
        stage_id = HiringStage.query.filter_by(name='Take-home task').one().id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/delete', follow_redirects=True)
    with app.app_context():
        assert db.session.get(HiringStage, stage_id) is None


def test_system_stages_cannot_be_deleted(auth_client, app, init_database):
    """Applied/Offer/Hired/Rejected carry pipeline semantics the app depends on."""
    protected = ['Applied', 'Offer', 'Hired', 'Rejected']
    with app.app_context():
        db.session.add_all(HiringStage(name=name, order=index)
                           for index, name in enumerate(protected))
        db.session.commit()
        ids = {s.name: s.id for s in HiringStage.query.all()}

    for name in protected:
        response = auth_client.post(f'/hr/hiring/stages/{ids[name]}/delete',
                                    follow_redirects=True)
        assert response.status_code == 200

    with app.app_context():
        assert HiringStage.query.count() == len(protected)


def test_a_stage_with_candidates_cannot_be_deleted(auth_client, app, init_database):
    """Deleting it would orphan the candidates sitting in that column."""
    from src.models.hiring import Candidate

    with app.app_context():
        stage = HiringStage(name='Screening', order=0)
        db.session.add(stage)
        db.session.flush()
        db.session.add(Candidate(name='Ada Lovelace', email='ada@test.com',
                                 stage_id=stage.id))
        db.session.commit()
        stage_id = stage.id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/delete', follow_redirects=True)
    with app.app_context():
        assert db.session.get(HiringStage, stage_id) is not None


def test_delete_stage_needs_write_access(client, app, init_database):
    with app.app_context():
        stage = HiringStage(name='Screening', order=0)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id

    _grant(app, 'hrreader2@test.com', AccessLevel.READ_ONLY)
    _login(client, 'hrreader2@test.com')

    client.post(f'/hr/hiring/stages/{stage_id}/delete', follow_redirects=True)
    with app.app_context():
        assert db.session.get(HiringStage, stage_id) is not None
