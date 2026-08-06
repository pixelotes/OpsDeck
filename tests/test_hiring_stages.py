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
    """System stages carry pipeline semantics the app depends on."""
    protected = ['Applied', 'Offer', 'Hired', 'Rejected']
    with app.app_context():
        db.session.add_all(HiringStage(name=name, order=index, is_system=True)
                           for index, name in enumerate(protected))
        db.session.commit()
        ids = {s.name: s.id for s in HiringStage.query.all()}

    for name in protected:
        response = auth_client.post(f'/hr/hiring/stages/{ids[name]}/delete',
                                    follow_redirects=True)
        assert response.status_code == 200

    with app.app_context():
        assert HiringStage.query.count() == len(protected)


def test_protection_survives_a_rename(auth_client, app, init_database):
    """The point of is_system: a translated or relabelled stage stays protected.

    Under the old name list, renaming 'Hired' to anything else made it deletable while
    it was still the stage that triggers onboarding.
    """
    with app.app_context():
        stage = HiringStage(name='Hired', order=1, is_hired_stage=True, is_system=True,
                            is_terminal=True)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/update',
                     data={'name': 'Contratado'}, follow_redirects=True)
    auth_client.post(f'/hr/hiring/stages/{stage_id}/delete', follow_redirects=True)

    with app.app_context():
        survivor = db.session.get(HiringStage, stage_id)
        assert survivor is not None
        assert survivor.name == 'Contratado'
        assert survivor.is_hired_stage is True


def test_a_non_system_stage_stays_deletable_after_a_rename(auth_client, app, init_database):
    with app.app_context():
        stage = HiringStage(name='Screening', order=1)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/update',
                     data={'name': 'Cribado'}, follow_redirects=True)
    auth_client.post(f'/hr/hiring/stages/{stage_id}/delete', follow_redirects=True)

    with app.app_context():
        assert db.session.get(HiringStage, stage_id) is None


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


# --- duplicate names ---------------------------------------------------------
#
# hiring_stage.name has no unique constraint, and until the create route was fixed it
# crashed before it could insert anything, so nothing exercised this. Duplicates are
# a trap rather than a cosmetic problem: delete_stage protects the system stages by
# name, so a second 'Hired' cannot be removed through the UI once it exists.

def test_a_duplicate_stage_name_is_refused(auth_client, app, init_database):
    auth_client.post('/hr/hiring/stages/new', data={'name': 'Screening'},
                     follow_redirects=True)
    auth_client.post('/hr/hiring/stages/new', data={'name': 'Screening'},
                     follow_redirects=True)

    with app.app_context():
        assert HiringStage.query.filter_by(name='Screening').count() == 1


def test_duplicate_detection_ignores_case_and_padding(auth_client, app, init_database):
    auth_client.post('/hr/hiring/stages/new', data={'name': 'Screening'},
                     follow_redirects=True)
    for variant in ('screening', 'SCREENING', '  Screening  '):
        auth_client.post('/hr/hiring/stages/new', data={'name': variant},
                         follow_redirects=True)

    with app.app_context():
        assert HiringStage.query.count() == 1


def test_renaming_onto_an_existing_name_is_refused(auth_client, app, init_database):
    """The rename route could reach the same broken state from the other direction."""
    with app.app_context():
        db.session.add_all([HiringStage(name='Applied', order=1),
                            HiringStage(name='Screening', order=2)])
        db.session.commit()
        screening_id = HiringStage.query.filter_by(name='Screening').one().id

    auth_client.post(f'/hr/hiring/stages/{screening_id}/update',
                     data={'name': 'Applied'}, follow_redirects=True)

    with app.app_context():
        assert HiringStage.query.filter_by(name='Applied').count() == 1
        assert db.session.get(HiringStage, screening_id).name == 'Screening'


def test_renaming_a_stage_to_a_free_name_works(auth_client, app, init_database):
    with app.app_context():
        stage = HiringStage(name='Screening', order=1)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/update',
                     data={'name': '  Phone screen  '}, follow_redirects=True)

    with app.app_context():
        assert db.session.get(HiringStage, stage_id).name == 'Phone screen'


def test_renaming_a_stage_to_its_own_name_is_allowed(auth_client, app, init_database):
    """Excluding itself from the check: saving the form unchanged must not fail."""
    with app.app_context():
        stage = HiringStage(name='Screening', order=1)
        db.session.add(stage)
        db.session.commit()
        stage_id = stage.id

    auth_client.post(f'/hr/hiring/stages/{stage_id}/update',
                     data={'name': 'Screening'}, follow_redirects=True)

    with app.app_context():
        assert db.session.get(HiringStage, stage_id).name == 'Screening'


def test_the_seeder_does_not_duplicate_stages_when_run_twice(app, init_database):
    """The seeder's own guard is all-or-nothing; this pins that it at least holds."""
    from src.seeder_prod import seed_production_frameworks

    with app.app_context():
        seed_production_frameworks()
        first = HiringStage.query.count()
        seed_production_frameworks()

        assert first > 0
        assert HiringStage.query.count() == first
        names = [s.name for s in HiringStage.query.all()]
        assert len(names) == len(set(names))


# --- terminal stages ---------------------------------------------------------

def test_the_board_prunes_stale_candidates_in_terminal_stages(auth_client, app,
                                                              init_database):
    """Terminal stages hide candidates untouched for over 15 days."""
    from datetime import timedelta
    from src.models.hiring import Candidate
    from src.utils.timezone_helper import now

    with app.app_context():
        terminal = HiringStage(name='Hired', order=2, is_system=True, is_terminal=True,
                               is_hired_stage=True)
        active = HiringStage(name='Screening', order=1)
        db.session.add_all([terminal, active])
        db.session.flush()

        stale = Candidate(name='Long gone', email='gone@test.com', stage_id=terminal.id)
        recent = Candidate(name='Just hired', email='new@test.com', stage_id=terminal.id)
        old_active = Candidate(name='Still screening', email='screen@test.com',
                               stage_id=active.id)
        db.session.add_all([stale, recent, old_active])
        db.session.commit()

        # updated_at is set by the model, so it has to be pushed back explicitly.
        stale.updated_at = now() - timedelta(days=40)
        old_active.updated_at = now() - timedelta(days=40)
        db.session.commit()

    body = auth_client.get('/hr/hiring/').data
    assert b'Just hired' in body
    assert b'Long gone' not in body
    # A non-terminal stage keeps everything, however old.
    assert b'Still screening' in body


def test_terminal_pruning_follows_the_flag_not_the_name(auth_client, app, init_database):
    """A stage named 'Hired' without the flag must not prune, and vice versa."""
    from datetime import timedelta
    from src.models.hiring import Candidate
    from src.utils.timezone_helper import now

    with app.app_context():
        named_only = HiringStage(name='Hired', order=1)          # name, but no flag
        flagged_only = HiringStage(name='Descartado', order=2, is_terminal=True)
        db.session.add_all([named_only, flagged_only])
        db.session.flush()

        in_named = Candidate(name='Kept by flag absence', email='a@test.com',
                             stage_id=named_only.id)
        in_flagged = Candidate(name='Pruned by flag', email='b@test.com',
                               stage_id=flagged_only.id)
        db.session.add_all([in_named, in_flagged])
        db.session.commit()

        in_named.updated_at = now() - timedelta(days=40)
        in_flagged.updated_at = now() - timedelta(days=40)
        db.session.commit()

    body = auth_client.get('/hr/hiring/').data
    assert b'Kept by flag absence' in body
    assert b'Pruned by flag' not in body


# --- seeder guard ------------------------------------------------------------

def test_the_seeder_restores_a_deleted_system_stage(app, init_database):
    """It runs on every container start, so a missing system stage must come back."""
    from src.seeder_prod import seed_production_frameworks

    with app.app_context():
        seed_production_frameworks()
        hired = HiringStage.query.filter_by(name='Hired').one()
        db.session.delete(hired)
        db.session.commit()
        assert HiringStage.query.filter_by(name='Hired').first() is None

        seed_production_frameworks()

        restored = HiringStage.query.filter_by(name='Hired').one()
        assert restored.is_system is True
        assert restored.is_terminal is True
        assert restored.is_hired_stage is True


def test_the_seeder_leaves_deleted_optional_stages_alone(app, init_database):
    """An administrator removing 'Screening' meant it; it must not reappear."""
    from src.seeder_prod import seed_production_frameworks

    with app.app_context():
        seed_production_frameworks()
        screening = HiringStage.query.filter_by(name='Screening').one()
        db.session.delete(screening)
        db.session.commit()

        seed_production_frameworks()

        assert HiringStage.query.filter_by(name='Screening').first() is None


def test_the_seeder_marks_the_standard_flags(app, init_database):
    from src.seeder_prod import seed_production_frameworks

    with app.app_context():
        seed_production_frameworks()
        by_name = {s.name: s for s in HiringStage.query.all()}

        assert [n for n, s in by_name.items() if s.is_system] == ['Applied', 'Offer',
                                                                  'Hired', 'Rejected']
        assert sorted(n for n, s in by_name.items() if s.is_terminal) == ['Hired',
                                                                          'Rejected']
        assert [n for n, s in by_name.items() if s.is_hired_stage] == ['Hired']
