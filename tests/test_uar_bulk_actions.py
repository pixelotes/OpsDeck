"""Bulk operations on UAR findings, one handler per action.

There was no test for this endpoint, which is how `create_incident` shipped building its
redirect from a blueprint that does not exist: the incident was created and committed,
then the response was a 500.
"""
import pytest

from src.extensions import db
from src.models import User
from src.models.security import SecurityIncident
from src.models.uar import UARComparison, UARExecution, UARFinding

URL = '/compliance/uar/findings/bulk-action'


@pytest.fixture
def findings(app, init_database):
    with app.app_context():
        comparison = UARComparison(name='Bulk', source_a_type='JSON', source_b_type='JSON',
                                   key_field_a='email', key_field_b='email')
        db.session.add(comparison)
        db.session.flush()
        execution = UARExecution(comparison_id=comparison.id)
        db.session.add(execution)
        db.session.flush()
        rows = [UARFinding(execution_id=execution.id, finding_type='Right Only (B)', severity='high',
                           key_value=f'ghost{i}@example.com', description='not in HR',
                           raw_data_b={'email': f'ghost{i}@example.com'})
                for i in range(3)]
        db.session.add_all(rows)
        db.session.commit()
        return [r.id for r in rows]


def _post(client, **payload):
    return client.post(URL, json=payload)


def test_unknown_action_and_empty_selection(auth_client, findings):
    assert _post(auth_client, action='explode', finding_ids=findings).status_code == 400
    assert _post(auth_client, action='resolve', finding_ids=[]).status_code == 400
    assert _post(auth_client, action='resolve', finding_ids=[999]).status_code == 404


def test_mark_false_positive(auth_client, app, findings):
    response = _post(auth_client, action='mark_false_positive', finding_ids=findings, notes='seeded')
    assert response.status_code == 200
    assert response.get_json()['count'] == 3
    with app.app_context():
        assert {f.status for f in UARFinding.query.all()} == {'false_positive'}
        assert UARFinding.query.first().resolution_notes == 'seeded'


def test_assign(auth_client, app, findings):
    with app.app_context():
        reviewer = User(name='Reviewer', email='rev@test.com', role='user')
        db.session.add(reviewer)
        db.session.commit()
        reviewer_id = reviewer.id
    assert _post(auth_client, action='assign', finding_ids=findings).status_code == 400
    assert _post(auth_client, action='assign', finding_ids=findings, user_id=9999).status_code == 404
    response = _post(auth_client, action='assign', finding_ids=findings, user_id=reviewer_id)
    assert response.status_code == 200
    assert 'Reviewer' in response.get_json()['message']
    with app.app_context():
        assert {f.assigned_to_id for f in UARFinding.query.all()} == {reviewer_id}


def test_resolve(auth_client, app, findings):
    response = _post(auth_client, action='resolve', finding_ids=findings[:2], resolution_status='resolved')
    assert response.status_code == 200
    with app.app_context():
        statuses = sorted(f.status for f in UARFinding.query.order_by(UARFinding.id).all())
        assert statuses == ['open', 'resolved', 'resolved']


def test_create_incident_links_findings_and_answers_a_working_link(auth_client, app, findings):
    response = _post(auth_client, action='create_incident', finding_ids=findings)
    assert response.status_code == 200, response.data
    body = response.get_json()
    with app.app_context():
        incident = db.session.get(SecurityIncident, body['incident_id'])
        assert incident.status == 'Investigating'
        assert 'ghost0@example.com' in incident.description
        assert {f.security_incident_id for f in UARFinding.query.all()} == {incident.id}
    assert auth_client.get(body['redirect_url']).status_code == 200


def test_export(auth_client, findings):
    response = _post(auth_client, action='export', finding_ids=findings)
    assert response.status_code == 200
    body = response.get_json()
    assert body['filename'].startswith('uar_findings_')
    lines = body['csv_data'].strip().splitlines()
    assert lines[0].startswith('ID,Finding Type,Severity')
    assert len(lines) == 4


def test_read_only_user_is_refused(user_client, app, findings):
    from src.models.permissions import AccessLevel, Module, Permission
    from src.services.permissions_service import permissions_cache
    with app.app_context():
        user = User.query.filter_by(email='user@test.com').first()
        module = Module.query.filter_by(slug='compliance').first() or Module(name='compliance', slug='compliance')
        db.session.add(module)
        db.session.flush()
        db.session.add(Permission(module_id=module.id, user_id=user.id, access_level=AccessLevel.READ_ONLY))
        db.session.commit()
        permissions_cache.invalidate()
    assert _post(user_client, action='resolve', finding_ids=findings).status_code == 403
