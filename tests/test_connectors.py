"""Settings > API Connectors: credentials, runs, diffs and the scheduler job."""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from src import db
from src.models.connectors import ConnectorReport, ConnectorSubtask, ConnectorTask
from src.services import connector_service
from src.utils.timezone_helper import now


def make_task(service='github', auth_config=None, **kw):
    task = ConnectorTask(name=f'{service} sync', service=service, auth_config=auth_config,
                         enabled=kw.pop('enabled', True), polling_interval=3600, **kw)
    subtask = ConnectorSubtask(task=task, name='Members', endpoint='/orgs/YOUR_ORG/members')
    db.session.add_all([task, subtask])
    db.session.commit()
    return task


class FakeConnector:
    """Stands in for a real connector: returns canned pages, saves through the base class."""
    pages = []

    def __init__(self, task, subtask):
        self.task, self.subtask = task, subtask

    def fetch_all_pages(self):
        items = FakeConnector.pages.pop(0)
        return {'items': items, 'total_count': len(items), 'duration_ms': 1}

    def save_report(self, data):
        from src.connectors.base import BaseConnector
        return BaseConnector.save_report(self, data)


@pytest.fixture
def fake_connector():
    with patch.object(connector_service, 'get_connector_class', return_value=FakeConnector):
        yield FakeConnector


def test_every_seeded_service_has_a_connector():
    from src.models.connectors import CONNECTOR_SERVICES
    for service in CONNECTOR_SERVICES:
        assert connector_service.get_connector_class(service) is not None, service


def test_seeding_is_idempotent_and_leaves_tasks_unconfigured(app, init_database):
    from src.seeder_connectors import seed_all_connectors
    with app.app_context():
        seed_all_connectors()
        seed_all_connectors()
        tasks = ConnectorTask.query.all()
        assert sorted(t.service for t in tasks) == ['atlassian', 'aws', 'github', 'google',
                                                   'jumpcloud', 'microsoft']
        assert all(t.auth_config is None and not t.enabled for t in tasks)


def test_dashboard_lists_tasks_for_admins(auth_client, app):
    with app.app_context():
        make_task()
    resp = auth_client.get('/settings/connectors/')
    assert resp.status_code == 200
    assert b'github sync' in resp.data


def test_dashboard_requires_login(client):
    resp = client.get('/settings/connectors/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_json_endpoints_refuse_anonymous_requests_with_401(client):
    assert client.get('/settings/connectors/api/report/1').status_code == 401
    assert client.get('/settings/connectors/api/diff/1').status_code == 401


def test_github_credentials_point_endpoints_at_the_organization(auth_client, app):
    with app.app_context():
        task_id = make_task().id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'access_token': 'ghp_test', 'organization': 'acme'})
    with app.app_context():
        task = db.session.get(ConnectorTask, task_id)
        assert task.auth_config == {'access_token': 'ghp_test', 'organization': 'acme'}
        assert task.subtasks[0].endpoint == '/orgs/acme/members'


def test_a_blank_secret_keeps_the_stored_one(auth_client, app):
    with app.app_context():
        task_id = make_task('microsoft', auth_config={
            'tenant_id': 't', 'client_id': 'c', 'client_secret': 'kept'}).id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'tenant_id': 't2', 'client_id': 'c2', 'client_secret': ''})
    with app.app_context():
        cfg = db.session.get(ConnectorTask, task_id).auth_config
        assert cfg == {'tenant_id': 't2', 'client_id': 'c2', 'client_secret': 'kept'}


def test_invalid_credentials_change_nothing(auth_client, app):
    with app.app_context():
        task_id = make_task('google').id
    auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials',
                     data={'service_account_json': '{not json', 'delegated_user': 'a@b.com'})
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).auth_config is None


def test_polling_interval_is_bounded(auth_client, app):
    with app.app_context():
        task_id = make_task().id
    auth_client.post(f'/settings/connectors/task/{task_id}/update', data={'polling_interval': '60'})
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).polling_interval == 3600
    auth_client.post(f'/settings/connectors/task/{task_id}/update', data={'polling_interval': '900'})
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).polling_interval == 900


def test_an_unconfigured_task_is_not_run(auth_client, app, fake_connector):
    with app.app_context():
        task_id = make_task().id
    auth_client.post(f'/settings/connectors/task/{task_id}/run')
    with app.app_context():
        assert ConnectorReport.query.count() == 0


def test_runs_store_reports_and_the_diff_api_compares_them(auth_client, app, fake_connector):
    fake_connector.pages = [[{'login': 'ann'}], [{'login': 'ann'}, {'login': 'bob'}]]
    with app.app_context():
        task = make_task(auth_config={'access_token': 'x', 'organization': 'acme'})
        task_id, subtask_id = task.id, task.subtasks[0].id

    auth_client.post(f'/settings/connectors/task/{task_id}/run')
    auth_client.post(f'/settings/connectors/task/{task_id}/run')

    with app.app_context():
        assert ConnectorReport.query.filter_by(subtask_id=subtask_id).count() == 2
        task = db.session.get(ConnectorTask, task_id)
        assert task.status == 'idle' and task.next_run is not None

    diff = auth_client.get(f'/settings/connectors/api/diff/{subtask_id}').get_json()
    assert diff['has_changes'] is True

    report_id = diff['report_new_id']
    assert auth_client.get(f'/settings/connectors/api/report/{report_id}').get_json()['record_count'] == 2
    assert auth_client.get(f'/settings/connectors/subtask/{subtask_id}/reports').status_code == 200
    assert auth_client.get(f'/settings/connectors/report/{report_id}/fullscreen').status_code == 200


def test_a_failing_subtask_marks_the_task_as_errored(app, init_database):
    class Broken(FakeConnector):
        def fetch_all_pages(self):
            raise RuntimeError('API down')

    with app.app_context(), patch.object(connector_service, 'get_connector_class', return_value=Broken):
        task = make_task(auth_config={'access_token': 'x'})
        result = connector_service.execute_task(task)
        assert result['success'] is False
        assert result['errors'][0]['error'] == 'API down'
        assert task.status == 'error'


def test_poll_runs_only_due_enabled_tasks(app, init_database, fake_connector):
    fake_connector.pages = [[{'login': 'ann'}]]
    with app.app_context():
        due = make_task(auth_config={'access_token': 'x'}, next_run=now() - timedelta(minutes=1))
        make_task('jumpcloud', auth_config={'api_key': 'x'}, next_run=now() + timedelta(hours=1))
        make_task('aws', auth_config={'aws_access_key': 'x'}, enabled=False)
        due_subtask = due.subtasks[0].id

    connector_service.poll_due_tasks(app)

    with app.app_context():
        reports = ConnectorReport.query.all()
        assert [r.subtask_id for r in reports] == [due_subtask]
        assert json.loads(reports[0].data)['items'] == [{'login': 'ann'}]
