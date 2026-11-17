"""Tests for the Microsoft Entra ID user sync, with Microsoft Graph mocked."""
import json
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from src import db
from src.models import User
from src.models.entra import EntraSyncRun, EntraSyncSettings
from src.services import entra_sync_service as svc

GROUP = 'group-1'


def member(oid, upn, name=None, department=None, job=None, enabled=True):
    return {'@odata.type': '#microsoft.graph.user', 'id': oid, 'userPrincipalName': upn,
            'displayName': name or upn.split('@')[0].title(), 'department': department,
            'jobTitle': job, 'accountEnabled': enabled}


class FakeGraph:
    """Stands in for GraphClient: groups -> members, oid -> manager oid."""

    def __init__(self, groups=None, managers=None, fail_group=None):
        self.groups = groups or {}
        self.managers = managers or {}
        self.fail_group = fail_group

    def group_users(self, group_id):
        if group_id == self.fail_group:
            raise svc.EntraSyncError('Microsoft Graph error 403')
        return [dict(m) for m in self.groups.get(group_id, [])]

    def manager_id(self, oid):
        return self.managers.get(oid)


@pytest.fixture
def entra(app, init_database):
    """Enabled sync settings with one group and credentials configured."""
    settings = EntraSyncSettings.get()
    settings.enabled = True
    settings.group_ids = GROUP
    settings.default_role = 'viewer'
    db.session.commit()
    app.config.update(AZURE_OAUTH_CLIENT_ID='cid', AZURE_OAUTH_CLIENT_SECRET='secret',
                      AZURE_OAUTH_TENANT_ID='11111111-2222-3333-4444-555555555555')
    yield settings
    app.config.update(AZURE_OAUTH_CLIENT_ID='', AZURE_OAUTH_CLIENT_SECRET='', AZURE_OAUTH_TENANT_ID='')


def add_user(email, name='Someone', oid=None, archived=False, **kw):
    user = User(name=name, email=email, role='user', entra_oid=oid, is_archived=archived, **kw)
    db.session.add(user)
    db.session.commit()
    return user


def sync(graph, **kw):
    return svc.run_sync(kw.pop('trigger', 'manual'), graph=graph, **kw)


# --- Reconciliation ----------------------------------------------------------------

def test_creates_missing_users_with_default_role(entra):
    graph = FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana', 'IT', 'SRE')]})
    run = sync(graph)
    assert run.status == 'success'
    assert run.created_count == 1
    user = User.query.filter_by(entra_oid='o1').one()
    assert (user.email, user.name, user.department, user.job_title, user.role) == \
        ('ana@corp.com', 'Ana', 'IT', 'SRE', 'viewer')
    assert user.password_hash is None


def test_links_existing_user_by_upn_then_by_oid(entra):
    user = add_user('Ana@Corp.com', name='Ana')
    sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana')]}))
    assert db.session.get(User, user.id).entra_oid == 'o1'
    assert User.query.count() == 1

    # UPN renamed in Entra: still the same user, matched by oid.
    run = sync(FakeGraph({GROUP: [member('o1', 'ana.new@corp.com', 'Ana Renamed')]}))
    assert run.updated_count == 1
    assert db.session.get(User, user.id).name == 'Ana Renamed'
    assert User.query.count() == 1


def test_upn_already_bound_to_other_oid_is_skipped(entra):
    add_user('ana@corp.com', oid='o-original')
    run = sync(FakeGraph({GROUP: [member('o-original', 'other@corp.com'),
                                  member('o-imposter', 'ana@corp.com')]}))
    assert run.status == 'success'
    assert run.changes['errors'][0]['upn'] == 'ana@corp.com'
    assert User.query.filter_by(entra_oid='o-imposter').first() is None


def test_updates_fields_and_manager(entra):
    boss = add_user('boss@corp.com', name='Boss', oid='o-boss')
    ana = add_user('ana@corp.com', name='Ana', oid='o1', department='Old')
    graph = FakeGraph({GROUP: [member('o-boss', 'boss@corp.com', 'Boss'),
                               member('o1', 'ana@corp.com', 'Ana', 'IT', 'SRE')]},
                      managers={'o1': 'o-boss', 'o-boss': 'o-not-in-opsdeck'})
    run = sync(graph)
    assert run.status == 'success'
    ana = db.session.get(User, ana.id)
    assert (ana.department, ana.job_title, ana.manager_id) == ('IT', 'SRE', boss.id)
    assert db.session.get(User, boss.id).manager_id is None  # manager not in OpsDeck


def test_manager_can_be_a_user_created_in_the_same_run(entra):
    graph = FakeGraph({GROUP: [member('o1', 'ana@corp.com'), member('o2', 'boss@corp.com')]},
                      managers={'o1': 'o2'})
    sync(graph)
    ana = User.query.filter_by(entra_oid='o1').one()
    assert ana.manager.entra_oid == 'o2'


def test_archives_users_out_of_scope_and_unarchives_on_return(entra):
    ana = add_user('ana@corp.com', name='Ana', oid='o1')
    local = add_user('breakglass@corp.com')  # never linked to Entra
    run = sync(FakeGraph({GROUP: []}))
    assert run.archived_count == 1
    assert db.session.get(User, ana.id).is_archived is True
    assert db.session.get(User, local.id).is_archived is False  # never touched

    run = sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana')]}))
    assert run.unarchived_count == 1
    assert db.session.get(User, ana.id).is_archived is False


def test_disabled_accounts_are_out_of_scope(entra):
    ana = add_user('ana@corp.com', name='Ana', oid='o1')
    sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana', enabled=False)]}))
    assert db.session.get(User, ana.id).is_archived is True


def test_nested_and_multiple_groups_are_merged(entra):
    entra.group_ids = 'group-1\ngroup-2'
    db.session.commit()
    run = sync(FakeGraph({'group-1': [member('o1', 'a@corp.com')],
                          'group-2': [member('o1', 'a@corp.com'), member('o2', 'b@corp.com')]}))
    assert run.created_count == 2


def test_group_read_failure_changes_nothing(entra):
    ana = add_user('ana@corp.com', oid='o1')
    entra.group_ids = 'group-1\ngroup-2'
    db.session.commit()
    run = sync(FakeGraph({'group-1': []}, fail_group='group-2'))
    assert run.status == 'error'
    assert db.session.get(User, ana.id).is_archived is False


def test_unchanged_users_produce_no_changes(entra):
    add_user('ana@corp.com', name='Ana', oid='o1')
    run = sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana')]}))
    assert run.changes['changes'] == []


# --- Dry run, brake, disabled ------------------------------------------------------

def test_dry_run_makes_no_changes(entra):
    ana = add_user('ana@corp.com', name='Ana', oid='o1')
    run = sync(FakeGraph({GROUP: [member('o2', 'new@corp.com')]}), dry_run=True)
    assert run.status == 'success'
    assert run.dry_run
    assert (run.created_count, run.archived_count) == (1, 1)
    assert User.query.count() == 1
    assert db.session.get(User, ana.id).is_archived is False


def test_preview_returns_plan_without_writing(entra):
    plan = svc.preview(graph=FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}))
    assert plan['counts']['create'] == 1
    assert plan['fingerprint']
    assert User.query.count() == 0
    assert EntraSyncRun.query.count() == 0


def test_apply_refuses_when_plan_changed_since_preview(entra):
    plan = svc.preview(graph=FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}))
    run = sync(FakeGraph({GROUP: [member('o2', 'bob@corp.com')]}),
               expected_fingerprint=plan['fingerprint'])
    assert run.status == 'aborted'
    assert User.query.count() == 0


def test_brake_aborts_scheduled_run_and_notifies(entra):
    for i in range(10):
        add_user(f'u{i}@corp.com', oid=f'o{i}')
    keep = [member(f'o{i}', f'u{i}@corp.com') for i in range(8)]  # 2 of 10 leave: 20% > 10%
    with patch.object(svc, 'notify_admins') as notify:
        run = sync(FakeGraph({GROUP: keep}), trigger='scheduled')
    assert run.status == 'aborted'
    assert 'threshold' in run.error
    notify.assert_called_once()
    assert User.query.filter_by(is_archived=True).count() == 0


def test_brake_allows_runs_under_threshold(entra):
    for i in range(10):
        add_user(f'u{i}@corp.com', name='Someone', oid=f'o{i}')
    keep = [member(f'o{i}', f'u{i}@corp.com', 'Someone') for i in range(9)]  # 10%: not above
    run = sync(FakeGraph({GROUP: keep}), trigger='scheduled')
    assert run.status == 'success'
    assert run.archived_count == 1


def test_manual_run_does_not_enforce_brake(entra):
    add_user('ana@corp.com', oid='o1')
    run = sync(FakeGraph({GROUP: []}))
    assert run.status == 'success'
    assert run.archived_count == 1


def test_disabled_sync_does_nothing(entra):
    entra.enabled = False
    db.session.commit()
    graph = MagicMock()
    run = sync(graph)
    assert run.status == 'error'
    assert 'disabled' in run.error
    graph.group_users.assert_not_called()
    with pytest.raises(svc.EntraSyncError):
        svc.preview(graph=graph)


def test_scheduled_job_skips_when_disabled_or_unscheduled(app, entra):
    with patch.object(svc, 'run_sync') as run_sync:
        svc._scheduled_job(app)  # enabled but schedule off
        entra.schedule_mode = 'daily'
        entra.enabled = False
        db.session.commit()
        svc._scheduled_job(app)
        run_sync.assert_not_called()
        entra.enabled = True
        db.session.commit()
        svc._scheduled_job(app)
        run_sync.assert_called_once_with('scheduled')


def test_second_scheduled_run_within_window_is_skipped(entra):
    graph = FakeGraph({GROUP: []})
    assert sync(graph, trigger='scheduled') is not None
    assert sync(graph, trigger='scheduled') is None
    assert EntraSyncRun.query.count() == 1


def test_run_is_recorded_with_changes(entra):
    run = sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}), triggered_by='admin@corp.com')
    stored = db.session.get(EntraSyncRun, run.id)
    assert stored.trigger == 'manual'
    assert stored.triggered_by == 'admin@corp.com'
    assert stored.finished_at is not None
    assert stored.changes['changes'][0]['action'] == 'create'


def test_notify_admins_emails_admins(app, entra):
    admin = User(name='Root', email='root@corp.com', role='admin')
    db.session.add(admin)
    db.session.commit()
    run = EntraSyncRun(trigger='scheduled', status='aborted', error='too many')
    with patch('src.notifications.send_email') as send:
        svc.notify_admins(run)
    assert send.call_args[0][3] == ['root@corp.com']


# --- Scheduler registration --------------------------------------------------------

def test_scheduler_registration_follows_settings(app, entra):
    scheduler = BackgroundScheduler()
    assert svc.configure_schedule(app, scheduler) is None  # schedule off
    assert scheduler.get_job(svc.SCHEDULER_JOB_ID) is None

    entra.schedule_mode, entra.daily_time = 'daily', '04:30'
    db.session.commit()
    job = svc.configure_schedule(app, scheduler)
    assert 'hour=\'4\'' in str(job.trigger)
    assert 'minute=\'30\'' in str(job.trigger)

    entra.schedule_mode, entra.interval_hours = 'interval', 6
    db.session.commit()
    job = svc.configure_schedule(app, scheduler)
    assert job.trigger.interval.total_seconds() == 6 * 3600
    assert len(scheduler.get_jobs()) == 1

    entra.enabled = False
    db.session.commit()
    assert svc.configure_schedule(app, scheduler) is None
    assert scheduler.get_job(svc.SCHEDULER_JOB_ID) is None


def test_refresh_schedule_reregisters_only_on_change(app, entra):
    scheduler = BackgroundScheduler()
    svc.configure_schedule(app, scheduler)
    entra.schedule_mode = 'interval'
    db.session.commit()
    with patch.object(svc, 'configure_schedule', wraps=svc.configure_schedule) as configure:
        svc.refresh_schedule(app, scheduler)
        svc.refresh_schedule(app, scheduler)
    assert configure.call_count == 1
    assert scheduler.get_job(svc.SCHEDULER_JOB_ID) is not None


def test_parse_daily_time():
    assert svc.parse_daily_time('07:05') == (7, 5)
    for bad in ('7', '25:00', 'aa:bb', ''):
        with pytest.raises(ValueError):
            svc.parse_daily_time(bad)


# --- Graph client ------------------------------------------------------------------

def _resp(status=200, payload=None):
    r = MagicMock()
    r.ok, r.status_code = 200 <= status < 300, status
    r.json.return_value = payload or {}
    return r


def test_graph_client_follows_pages_and_filters_non_users():
    http = MagicMock()
    http.post.return_value = _resp(payload={'access_token': 't'})
    http.get.side_effect = [
        _resp(payload={'value': [member('o1', 'a@corp.com'), {'@odata.type': '#microsoft.graph.group', 'id': 'g'}],
                       '@odata.nextLink': 'https://graph.microsoft.com/v1.0/next'}),
        _resp(payload={'value': [member('o2', 'b@corp.com')]}),
        _resp(status=404),
    ]
    graph = svc.GraphClient('tenant', 'cid', 'secret', session=http)
    users = graph.group_users('g1')
    assert [u['id'] for u in users] == ['o1', 'o2']
    assert http.get.call_args_list[0][0][0].endswith('/groups/g1/transitiveMembers')
    assert http.get.call_args_list[1][0][0] == 'https://graph.microsoft.com/v1.0/next'
    assert graph.manager_id('o1') is None
    assert http.post.call_count == 1  # token reused
    assert http.post.call_args[1]['data']['grant_type'] == 'client_credentials'
    assert '/tenant/oauth2/v2.0/token' in http.post.call_args[0][0]


def test_graph_client_errors():
    http = MagicMock()
    http.post.return_value = _resp(status=401)
    token_refused = svc.GraphClient('t', 'c', 's', session=http)
    with pytest.raises(svc.EntraSyncError):
        token_refused.get('/me')

    http.post.return_value = _resp(payload={'access_token': 't'})
    http.get.return_value = _resp(status=403)
    group_forbidden = svc.GraphClient('t', 'c', 's', session=http)
    with pytest.raises(svc.EntraSyncError):
        group_forbidden.group_users('g')


def test_graph_client_requires_credentials(app, init_database):
    with pytest.raises(svc.EntraSyncError):
        svc.GraphClient.from_config({'AZURE_OAUTH_CLIENT_ID': 'c', 'AZURE_OAUTH_TENANT_ID': 'common'})


# --- Admin screens -----------------------------------------------------------------

def test_settings_page_and_save(auth_client, app):
    assert auth_client.get('/admin/entra').status_code == 200
    resp = auth_client.post('/admin/entra/settings', data={
        'enabled': 'on', 'group_ids': 'g1, g2', 'default_role': 'editor', 'schedule_mode': 'daily',
        'daily_time': '02:15', 'interval_hours': '12', 'archive_threshold_percent': '5',
    })
    assert resp.status_code == 302
    s = EntraSyncSettings.get()
    assert (s.enabled, s.group_id_list, s.default_role, s.schedule_mode, s.daily_time,
            s.archive_threshold_percent) == (True, ['g1', 'g2'], 'editor', 'daily', '02:15', 5)


@pytest.mark.parametrize('field, value', [
    ('schedule_mode', 'hourly'), ('default_role', 'root'), ('daily_time', '99:00'),
    ('interval_hours', '0'), ('archive_threshold_percent', 'abc'),
])
def test_settings_validation(auth_client, field, value):
    data = {'schedule_mode': 'off', 'default_role': 'user', 'daily_time': '03:00',
            'interval_hours': '24', 'archive_threshold_percent': '10', field: value}
    auth_client.post('/admin/entra/settings', data=data)
    assert EntraSyncSettings.get().schedule_mode == 'off'
    assert EntraSyncSettings.get().default_role == 'user'


def test_preview_and_apply_screens(auth_client, entra):
    add_user('gone@corp.com', oid='o-gone')
    graph = FakeGraph({GROUP: [member('o1', 'ana@corp.com', 'Ana')]})
    with patch.object(svc.GraphClient, 'from_config', return_value=graph):
        resp = auth_client.post('/admin/entra/preview')
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'ana@corp.com' in html
        assert 'Apply 2 change(s)' in html
        assert 'above the' in html  # 1 of 1 synced users would be archived
        assert User.query.filter_by(entra_oid='o1').first() is None

        fingerprint = html.split('name="fingerprint" value="')[1].split('"')[0]
        resp = auth_client.post('/admin/entra/apply', data={'fingerprint': fingerprint})
    assert resp.status_code == 302
    assert User.query.filter_by(entra_oid='o1').one().name == 'Ana'
    run = EntraSyncRun.query.one()
    assert run.trigger == 'manual'
    assert run.triggered_by == 'admin@test.com'
    detail = auth_client.get(f'/admin/entra/runs/{run.id}').get_data(as_text=True)
    assert 'ana@corp.com' in detail
    assert f'/admin/entra/runs/{run.id}' in auth_client.get('/admin/entra').get_data(as_text=True)


def test_preview_screen_reports_errors(auth_client, entra):
    with patch.object(svc.GraphClient, 'from_config', side_effect=svc.EntraSyncError('no creds')):
        resp = auth_client.post('/admin/entra/preview')
    assert resp.status_code == 302


def test_sync_screens_require_admin_write(user_client):
    assert user_client.get('/admin/entra').status_code in (302, 403)
    user_client.post('/admin/entra/settings', data={'enabled': 'on', 'schedule_mode': 'daily'})
    assert EntraSyncSettings.get().enabled is False


# --- CLI ---------------------------------------------------------------------------

def test_cli_dry_run(app, entra):
    with patch.object(svc.GraphClient, 'from_config',
                      return_value=FakeGraph({GROUP: [member('o1', 'ana@corp.com')]})):
        result = app.test_cli_runner().invoke(args=['entra-sync', '--dry-run'])
    assert result.exit_code == 0, result.output
    assert 'Dry run finished: 1 to create' in result.output
    assert User.query.count() == 0
    assert json.loads(EntraSyncRun.query.one().changes_json)['changes'][0]['upn'] == 'ana@corp.com'


def test_cli_apply_and_brake(app, entra):
    add_user('ana@corp.com', oid='o1')
    with patch.object(svc.GraphClient, 'from_config', return_value=FakeGraph({GROUP: []})):
        result = app.test_cli_runner().invoke(args=['entra-sync'])
        assert result.exit_code == 1
        assert 'aborted' in result.output
        result = app.test_cli_runner().invoke(args=['entra-sync', '--force'])
    assert result.exit_code == 0, result.output
    assert User.query.filter_by(entra_oid='o1').one().is_archived is True


# --- Sign-in access ----------------------------------------------------------------

def test_new_users_are_directory_only_by_default(entra):
    with patch('src.notifications.send_email') as send:
        run = sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}))
    assert run.status == 'success'
    user = User.query.filter_by(entra_oid='o1').one()
    assert user.login_enabled is False
    assert user.password_hash is None
    assert run.changes['changes'][0]['fields']['login_enabled'] == [None, False]
    send.assert_not_called()


def test_new_users_can_sign_in_when_enabled(entra):
    entra.new_user_login = True
    db.session.commit()
    sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}))
    assert User.query.filter_by(entra_oid='o1').one().login_enabled is True


def test_new_user_setting_never_changes_existing_users(entra):
    can = add_user('can@corp.com', oid='o-can')
    cannot = add_user('cannot@corp.com', oid='o-cannot', login_enabled=False)
    linked = add_user('local@corp.com')  # linked by UPN on this run
    graph = FakeGraph({GROUP: [member('o-can', 'can@corp.com', 'Someone'),
                               member('o-cannot', 'cannot@corp.com', 'Someone'),
                               member('o-local', 'local@corp.com', 'Someone')]})
    plan = svc.build_plan(svc.fetch_scope(graph, [GROUP]), 'user', new_user_login=False)
    assert all('login_enabled' not in c['fields'] for c in plan['changes'])
    assert plan['login_changes'] == 0
    sync(graph)
    assert [db.session.get(User, u.id).login_enabled for u in (can, cannot, linked)] == \
        [True, False, True]


def test_access_groups_decide_sign_in_and_show_in_plan(entra):
    entra.new_user_login = True   # ignored once access groups are set
    entra.access_group_ids = 'access-1'
    db.session.commit()
    keeps = add_user('keeps@corp.com', name='Keeps', oid='o-keeps')
    loses = add_user('loses@corp.com', name='Loses', oid='o-loses')
    gains = add_user('gains@corp.com', name='Gains', oid='o-gains', login_enabled=False)
    graph = FakeGraph({
        GROUP: [member('o-keeps', 'keeps@corp.com', 'Keeps'), member('o-loses', 'loses@corp.com', 'Loses'),
                member('o-new', 'new@corp.com'), member('o-gains', 'gains@corp.com', 'Gains')],
        # Access-group members are in scope even if not in the main groups.
        'access-1': [member('o-keeps', 'keeps@corp.com', 'Keeps'), member('o-gains', 'gains@corp.com', 'Gains'),
                     member('o-admin', 'it.admin@corp.com')],
    })

    plan = svc.run_sync('manual', graph=graph, dry_run=True)
    fields = {c['upn']: c['fields'] for c in plan.changes['changes']}
    assert fields['loses@corp.com'] == {'login_enabled': [True, False]}
    assert fields['gains@corp.com'] == {'login_enabled': [False, True]}
    assert 'keeps@corp.com' not in fields
    assert fields['new@corp.com']['login_enabled'] == [None, False]
    assert fields['it.admin@corp.com']['login_enabled'] == [None, True]
    assert db.session.get(User, loses.id).login_enabled is True  # dry run wrote nothing

    run = sync(graph)
    assert run.status == 'success'
    assert [db.session.get(User, u.id).login_enabled for u in (keeps, loses, gains)] == [True, False, True]
    assert User.query.filter_by(entra_oid='o-new').one().login_enabled is False
    assert User.query.filter_by(entra_oid='o-admin').one().login_enabled is True


def test_access_group_read_failure_changes_nothing(entra):
    entra.access_group_ids = 'access-1'
    db.session.commit()
    user = add_user('ana@corp.com', oid='o1')
    run = sync(FakeGraph({GROUP: [member('o1', 'ana@corp.com')]}, fail_group='access-1'))
    assert run.status == 'error'
    assert db.session.get(User, user.id).login_enabled is True


def test_preview_screen_flags_sign_in_changes(auth_client, entra):
    entra.access_group_ids = 'access-1'
    db.session.commit()
    add_user('loses@corp.com', name='Loses', oid='o-loses')
    graph = FakeGraph({GROUP: [member('o-loses', 'loses@corp.com', 'Loses'), member('o-new', 'new@corp.com')]})
    with patch.object(svc.GraphClient, 'from_config', return_value=graph):
        html = auth_client.post('/admin/entra/preview').get_data(as_text=True)
    assert 'sign-in access of 1 existing user(s)' in html
    assert '<del>can sign in</del> → directory only' in html
    assert 'directory only' in html


def test_settings_save_sign_in_options(auth_client, app):
    auth_client.post('/admin/entra/settings', data={
        'schedule_mode': 'off', 'default_role': 'user', 'daily_time': '03:00', 'interval_hours': '24',
        'archive_threshold_percent': '10', 'new_user_login': 'on', 'access_group_ids': 'a1, a2',
    })
    s = EntraSyncSettings.get()
    assert (s.new_user_login, s.access_group_id_list) == (True, ['a1', 'a2'])

    auth_client.post('/admin/entra/settings', data={
        'schedule_mode': 'off', 'default_role': 'user', 'daily_time': '03:00', 'interval_hours': '24',
        'archive_threshold_percent': '10',
    })
    s = EntraSyncSettings.get()
    assert (s.new_user_login, s.access_group_id_list) == (False, [])
    assert 'New users can sign in' in auth_client.get('/admin/entra').get_data(as_text=True)


def test_brake_covers_mass_sign_in_removal(entra):
    """An access group read fine but emptied by mistake must not lock everyone out."""
    entra.access_group_ids = 'access-1'
    db.session.commit()
    users = [add_user(f'u{i}@corp.com', name=f'U{i}', oid=f'o{i}') for i in range(5)]
    graph = FakeGraph({GROUP: [member(f'o{i}', f'u{i}@corp.com', f'U{i}') for i in range(5)],
                       'access-1': []})
    with patch('src.notifications.send_email'):
        run = sync(graph, trigger='scheduled')
    assert run.status == 'aborted'
    assert 'remove sign-in access from 5 of 5' in run.error
    assert all(db.session.get(User, u.id).login_enabled for u in users)

    run = sync(graph)  # a confirmed manual run is the admin's call
    assert run.status == 'success'
    assert not any(db.session.get(User, u.id).login_enabled for u in users)
