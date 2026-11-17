"""Tests for the one-way Jira Service Management Assets sync, with the Assets API mocked."""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src import db
from src.models import Asset, AssetHistory, Brand, Supplier, User
from src.models.connectors import ConnectorTask
from src.models.jira_assets import JiraAssetsProfile, JiraAssetsRun
from src.services import jira_assets_service as svc
from src.services.jira_assets_client import (JiraAssetsClient, JiraAssetsError, normalise_object,
                                             type_clause, validate_site_url)
from src.utils.timezone_helper import now

LAPTOP_MAP = {'Assigned': 'In Use', 'Unassigned': 'Stored', 'Broken': 'In Repair',
              'To be recycled': 'Awaiting Disposal', 'Recycled': 'archive', 'Stolen': 'archive'}


def laptop(oid, name, status, serial=None, brand='Lenovo', model='T14', assignee=None, order_date=None):
    attrs = {'Name': [name], 'Status': [status]}
    if serial:
        attrs['Serial Number'] = [serial]
    if brand:
        attrs['Brand'] = [brand]
    if model:
        attrs['Model'] = [model]
    if assignee:
        attrs['Assignee'] = [assignee]
    if order_date:
        attrs['Order date'] = [order_date]
    return {'id': str(oid), 'key': f'ITSM-{oid}', 'label': name, 'type_id': '260', 'type': 'Laptop',
            'attrs': attrs}


def supplier_obj(oid, name, active='Active', critical='No', srm=None, website=None):
    attrs = {'Name': [name], 'Active contract': [active], 'Critical supplier': [critical]}
    if srm:
        attrs['SRM'] = [srm]
    if website:
        attrs['Website'] = [website]
    return {'id': str(oid), 'key': f'ITSM-{oid}', 'label': name, 'type_id': '236', 'type': 'Supplier',
            'attrs': attrs}


class FakeClient:
    def __init__(self, objects):
        self.objects = objects
        self.queries = []

    def search(self, aql):
        self.queries.append(aql)
        return [dict(o) for o in self.objects]


@pytest.fixture
def laptops(init_database):
    profile = JiraAssetsProfile(name='Laptops', target='asset', object_type='260', status_attribute='Status',
                                archive_threshold_percent=10)
    profile.status_map = LAPTOP_MAP
    db.session.add(profile)
    db.session.commit()
    return profile


@pytest.fixture
def suppliers(init_database):
    profile = JiraAssetsProfile(name='Suppliers', target='supplier', object_type='Supplier',
                                status_attribute='Active contract', archive_threshold_percent=10)
    profile.status_map = {'Active': 'active', 'Inactive': 'archive'}
    db.session.add(profile)
    db.session.commit()
    return profile


def sync(profile, objects, **kw):
    return svc.run_sync(profile, kw.pop('trigger', 'manual'), client=FakeClient(objects), **kw)


# --- Client ------------------------------------------------------------------------

@pytest.mark.parametrize('url', ['http://acme.atlassian.net', 'https://evil.com', 'https://acme.atlassian.net/x',
                                 'https://user:pw@acme.atlassian.net', 'https://acme.atlassian.net.evil.com',
                                 'https://acme.atlassian.net:8443', ''])
def test_site_url_must_be_an_atlassian_site(url):
    with pytest.raises(JiraAssetsError):
        validate_site_url(url)


def test_site_url_is_normalised():
    assert validate_site_url('https://ACME.atlassian.net/') == 'https://acme.atlassian.net'


def test_type_clause_accepts_id_or_name():
    assert type_clause('260') == 'objectTypeId = 260'
    assert type_clause('Laptop "Pro"') == 'objectType = "Laptop \\"Pro\\""'


def test_normalise_object_reads_values_and_references():
    raw = {'id': 7, 'objectKey': 'ITSM-7', 'label': 'LT-7', 'objectType': {'id': '260', 'name': 'Laptop'},
           'attributes': [
               {'objectTypeAttributeId': '1', 'objectAttributeValues': [{'value': 'SN1', 'displayValue': 'SN1'}]},
               {'objectTypeAttributeId': '2', 'objectAttributeValues': [
                   {'displayValue': 'Ana Ruiz', 'referencedObject': {'label': 'Ana Ruiz'}}]},
               {'objectTypeAttributeId': '3', 'objectAttributeValues': [{'value': '2024-02-01', 'displayValue': '01/Feb/24'}]},
               {'objectTypeAttributeId': '9', 'objectAttributeValues': [{'value': 'x'}]},  # unknown attribute
           ]}
    obj = normalise_object(raw, {'1': 'Serial Number', '2': 'Assignee', '3': 'Order date'})
    assert obj['id'] == '7' and obj['key'] == 'ITSM-7' and obj['type_id'] == '260'
    assert obj['attrs'] == {'Serial Number': ['SN1'], 'Assignee': ['Ana Ruiz'], 'Order date': ['2024-02-01']}


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class FakeSession:
    """requests.Session stand-in that answers the workspace call and paged AQL calls."""

    def __init__(self, pages, workspace='ws-1', status=200):
        self.pages, self.workspace, self.status = pages, workspace, status
        self.calls, self.headers, self.auth = [], {}, None

    def request(self, method, url, timeout=None, params=None, json=None):
        self.calls.append((method, url, params, json))
        if self.status != 200:
            return FakeResponse({}, self.status)
        if url.endswith('/rest/servicedeskapi/assets/workspace'):
            return FakeResponse({'values': [{'workspaceId': self.workspace}]})
        return FakeResponse(self.pages[min(params['startAt'] // 2, len(self.pages) - 1)])


def _page(ids, total, last):
    return {'startAt': 0, 'total': total, 'isLast': last,
            'objectTypeAttributes': [{'id': '1', 'name': 'Name'}],
            'values': [{'id': i, 'objectKey': f'K-{i}', 'label': f'L{i}', 'objectType': {'id': '260'},
                        'attributes': [{'objectTypeAttributeId': '1',
                                        'objectAttributeValues': [{'value': f'L{i}'}]}]} for i in ids]}


def test_client_pages_through_aql_results_on_the_assets_api():
    session = FakeSession([_page([1, 2], 3, False), _page([3], 3, True)])
    client = JiraAssetsClient('https://acme.atlassian.net', 'me@corp.com', 'tok', session=session)
    objects = client.search('objectTypeId = 260')
    assert [o['id'] for o in objects] == ['1', '2', '3']
    assert objects[0]['attrs'] == {'Name': ['L1']}
    workspace_call, first, second = session.calls
    assert workspace_call[1] == 'https://acme.atlassian.net/rest/servicedeskapi/assets/workspace'
    assert first[1] == 'https://api.atlassian.com/jsm/assets/workspace/ws-1/v1/object/aql'
    assert first[3] == {'qlQuery': 'objectTypeId = 260'}
    assert second[2]['startAt'] == 2
    assert session.auth == ('me@corp.com', 'tok')


def test_client_stops_when_a_page_repeats():
    session = FakeSession([_page([1, 2], 10, False)])
    client = JiraAssetsClient('https://acme.atlassian.net', 'me@corp.com', 'tok', session=session)
    with pytest.raises(JiraAssetsError, match='same page'):
        client.search('objectTypeId = 260')


def test_client_reports_refused_credentials():
    client = JiraAssetsClient('https://acme.atlassian.net', 'me@corp.com', 'tok', session=FakeSession([], status=401))
    with pytest.raises(JiraAssetsError, match='refused'):
        client.search('objectTypeId = 260')


def test_client_needs_a_configured_connector(init_database):
    with pytest.raises(JiraAssetsError, match='Atlassian API connector'):
        JiraAssetsClient.from_connector()


# --- Assets ------------------------------------------------------------------------

def test_imports_new_laptops_with_mapped_status(laptops):
    ana = User(name='Ana Ruiz', email='ana@corp.com', role='user')
    db.session.add(ana)
    db.session.commit()
    client = FakeClient([laptop(1, 'LT-001', 'Assigned', serial='SN1', assignee='Ana Ruiz', order_date='2024-02-01'),
                         laptop(2, 'LT-002', 'Unassigned', serial='SN2', brand='Apple', model='MacBook Pro')])
    run = svc.run_sync(laptops, 'manual', client=client)
    assert run.status == 'success'
    assert run.created_count == 2
    assert client.queries == ['objectTypeId = 260']
    a1 = Asset.query.filter_by(jira_object_id='1').one()
    assert (a1.name, a1.serial_number, a1.status, a1.is_archived) == ('LT-001', 'SN1', 'In Use', False)
    assert a1.user_id == ana.id
    assert a1.purchase_date == date(2024, 2, 1)
    assert a1.brand.name == 'Lenovo' and a1.model.name == 'T14'
    assert Asset.query.filter_by(jira_object_id='2').one().status == 'Stored'
    assert AssetHistory.query.filter_by(asset_id=a1.id, field_changed='Jira sync').count() == 1


def test_retired_and_unmapped_objects_are_not_imported(laptops):
    run = sync(laptops, [laptop(1, 'Old', 'Recycled', serial='SN1'), laptop(2, 'Odd', 'Purchased by user')])
    assert run.created_count == 0
    assert Asset.query.count() == 0
    assert any('Purchased by user' in w for w in run.changes['warnings'])


def test_links_existing_asset_by_serial_and_reuses_brand(laptops):
    brand = Brand(name='lenovo')
    db.session.add(brand)
    existing = Asset(name='My laptop', serial_number='sn1', status='Stored')
    db.session.add(existing)
    db.session.commit()
    run = sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    assert (run.linked_count, run.created_count) == (1, 0)
    db.session.refresh(existing)
    assert existing.jira_object_id == '1'
    assert existing.status == 'In Use'
    assert existing.name == 'My laptop'          # descriptive fields stay OpsDeck's
    assert Brand.query.count() == 1


def test_only_state_follows_jira_after_import(laptops):
    sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    asset = Asset.query.one()
    asset.name = 'Renamed in OpsDeck'
    db.session.commit()
    run = sync(laptops, [laptop(1, 'LT-001 renamed in Jira', 'Broken', serial='SN1')])
    assert run.updated_count == 1
    db.session.refresh(asset)
    assert (asset.name, asset.status) == ('Renamed in OpsDeck', 'In Repair')
    history = AssetHistory.query.filter_by(asset_id=asset.id, field_changed='status (Jira sync)').one()
    assert (history.old_value, history.new_value) == ('In Use', 'In Repair')


def test_archives_and_unarchives_with_jira(laptops):
    sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    run = sync(laptops, [laptop(1, 'LT-001', 'Stolen', serial='SN1')])
    assert run.archived_count == 1
    asset = Asset.query.one()
    assert asset.is_archived is True and asset.status == 'In Use'
    run = sync(laptops, [laptop(1, 'LT-001', 'Unassigned', serial='SN1')])
    assert run.unarchived_count == 1
    db.session.refresh(asset)
    assert asset.is_archived is False and asset.status == 'Stored'


def test_unmapped_status_leaves_linked_asset_unchanged(laptops):
    sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    run = sync(laptops, [laptop(1, 'LT-001', 'Mystery', serial='SN1')])
    assert run.updated_count == 0
    assert Asset.query.one().status == 'In Use'
    assert any('Mystery' in w for w in run.changes['warnings'])


def test_objects_that_leave_the_query_are_reported_not_archived(laptops):
    sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    run = sync(laptops, [])
    assert run.archived_count == 0
    assert Asset.query.one().is_archived is False
    assert any('no longer matches' in w for w in run.changes['warnings'])


def test_serial_already_linked_elsewhere_is_skipped(laptops):
    db.session.add(Asset(name='Other', serial_number='SN1', status='In Use', jira_object_id='99'))
    db.session.commit()
    run = sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    assert run.created_count == run.linked_count == 0
    assert any('already linked' in w for w in run.changes['warnings'])


def test_link_only_profile_does_not_create(laptops):
    laptops.create_missing = False
    db.session.commit()
    run = sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')])
    assert run.created_count == 0 and Asset.query.count() == 0


def test_dry_run_changes_nothing(laptops):
    run = sync(laptops, [laptop(1, 'LT-001', 'Assigned', serial='SN1')], dry_run=True)
    assert run.status == 'success' and run.created_count == 1
    assert Asset.query.count() == 0


def test_extra_aql_filter_is_anded(laptops):
    laptops.aql_filter = '"Purchasing Entity" = "mimacom spain"'
    client = FakeClient([])
    svc.run_sync(laptops, 'manual', client=client)
    assert client.queries == ['objectTypeId = 260 AND ("Purchasing Entity" = "mimacom spain")']


def test_scheduled_run_aborts_above_archive_threshold(laptops):
    sync(laptops, [laptop(i, f'LT-{i}', 'Assigned', serial=f'SN{i}') for i in range(1, 6)])
    stolen = [laptop(i, f'LT-{i}', 'Stolen', serial=f'SN{i}') for i in range(1, 6)]
    with patch.object(svc, 'notify_admins') as notify:
        run = sync(laptops, stolen, trigger='scheduled')
    assert run.status == 'aborted'
    notify.assert_called_once()
    assert Asset.query.filter_by(is_archived=True).count() == 0
    run = sync(laptops, stolen)                   # a manual run is the admin's call
    assert run.archived_count == 5


def test_preview_fingerprint_must_match(laptops):
    plan = svc.preview(laptops, client=FakeClient([laptop(1, 'LT-001', 'Assigned', serial='SN1')]))
    run = sync(laptops, [laptop(1, 'LT-001', 'Broken', serial='SN1')], expected_fingerprint=plan['fingerprint'])
    assert run.status == 'aborted'
    assert Asset.query.count() == 0


def test_failure_is_recorded_on_the_run(laptops):
    class Broken:
        def search(self, aql):
            raise JiraAssetsError('Jira Assets answered 500 for /object/aql.')
    run = svc.run_sync(laptops, 'manual', client=Broken())
    assert run.status == 'error' and '500' in run.error


# --- Suppliers ---------------------------------------------------------------------

def test_imports_suppliers_with_owner_and_critical_flag(suppliers):
    srm = User(name='Beatrice Clerici', email='bea@corp.com', role='user')
    db.session.add(srm)
    db.session.commit()
    run = sync(suppliers, [supplier_obj(1, '1F Partners GmbH', critical='Yes', srm='Beatrice Clerici',
                                        website='https://1f.ch'),
                           supplier_obj(2, 'Gone Ltd', active='Inactive')])
    assert run.created_count == 1                 # inactive suppliers are not imported
    s = Supplier.query.filter_by(jira_object_id='1').one()
    assert (s.name, s.is_critical, s.website) == ('1F Partners GmbH', True, 'https://1f.ch')
    assert (s.owner_type, s.owner_id) == ('User', srm.id)


def test_links_supplier_by_name_and_syncs_state(suppliers):
    existing = Supplier(name='1f partners gmbh', is_critical=False)
    db.session.add(existing)
    db.session.commit()
    run = sync(suppliers, [supplier_obj(1, '1F Partners GmbH', critical='Yes')])
    assert run.linked_count == 1
    db.session.refresh(existing)
    assert existing.jira_object_id == '1' and existing.is_critical is True
    run = sync(suppliers, [supplier_obj(1, '1F Partners GmbH', active='Inactive', critical='Yes')])
    assert run.archived_count == 1
    db.session.refresh(existing)
    assert existing.is_archived is True


def test_ambiguous_supplier_name_is_skipped(suppliers):
    db.session.add_all([Supplier(name='Acme'), Supplier(name='ACME')])
    db.session.commit()
    run = sync(suppliers, [supplier_obj(1, 'Acme')])
    assert run.linked_count == run.created_count == 0
    assert any('2 OpsDeck suppliers' in w for w in run.changes['warnings'])


def test_unknown_owner_is_a_warning(suppliers):
    run = sync(suppliers, [supplier_obj(1, 'Acme', srm='Nobody Here')])
    assert run.created_count == 1
    assert Supplier.query.one().owner_id is None
    assert any('Nobody Here' in w for w in run.changes['warnings'])


# --- Scheduling ----------------------------------------------------------------------

def test_run_due_profiles_runs_enabled_due_profiles_only(app, laptops, suppliers):
    laptops.enabled, laptops.interval_hours, laptops.next_run_at = True, 24, now() - timedelta(minutes=1)
    suppliers.enabled, suppliers.interval_hours, suppliers.next_run_at = True, 24, now() + timedelta(hours=1)
    db.session.commit()
    with patch.object(svc.JiraAssetsClient, 'from_connector', return_value=FakeClient([])):
        svc.run_due_profiles(app)
    runs = JiraAssetsRun.query.all()
    assert [(r.profile_id, r.trigger) for r in runs] == [(laptops.id, 'scheduled')]
    db.session.refresh(laptops)
    assert laptops.next_run_at.replace(tzinfo=None) > (now() + timedelta(hours=23)).replace(tzinfo=None)


# --- Routes --------------------------------------------------------------------------

def _profile_form(**overrides):
    data = {'target': 'asset', 'name': 'Laptops', 'object_type': '260', 'status_attribute': 'Status',
            'map_value': ['Assigned', 'Recycled', ''], 'map_action': ['In Use', 'archive', ''],
            'create_missing': 'on', 'interval_hours': '24', 'archive_threshold_percent': '10',
            'field_serial_number': 'Serial Number', 'field_assignee': 'User'}
    data.update(overrides)
    return data


def test_profile_crud_preview_and_apply(auth_client):
    assert auth_client.get('/settings/jira-assets/').status_code == 200
    assert auth_client.get('/settings/jira-assets/profiles/new?target=asset').status_code == 200
    resp = auth_client.post('/settings/jira-assets/profiles/new', data=_profile_form(enabled='on'))
    assert resp.status_code == 302
    profile = JiraAssetsProfile.query.one()
    assert profile.status_map == {'Assigned': 'In Use', 'Recycled': 'archive'}
    assert profile.field_overrides == {'assignee': 'User'}
    assert profile.field_map['assignee'] == 'User' and profile.field_map['name'] == 'Name'
    assert profile.enabled and profile.next_run_at is not None
    assert auth_client.get(f'/settings/jira-assets/profiles/{profile.id}/edit').status_code == 200

    objects = [laptop(1, 'LT-001', 'Assigned', serial='SN1')]
    with patch.object(svc.JiraAssetsClient, 'from_connector', return_value=FakeClient(objects)):
        page = auth_client.post(f'/settings/jira-assets/profiles/{profile.id}/preview')
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert 'LT-001' in html and 'Apply 1 change' in html
        fingerprint = svc.preview(profile, client=FakeClient(objects))['fingerprint']
        resp = auth_client.post(f'/settings/jira-assets/profiles/{profile.id}/apply',
                                data={'fingerprint': fingerprint})
    run = JiraAssetsRun.query.one()
    assert resp.status_code == 302 and f'/runs/{run.id}' in resp.headers['Location']
    assert run.status == 'success' and Asset.query.count() == 1
    assert 'LT-001' in auth_client.get(f'/settings/jira-assets/runs/{run.id}').get_data(as_text=True)

    resp = auth_client.post(f'/settings/jira-assets/profiles/{profile.id}/delete')
    assert resp.status_code == 302
    assert JiraAssetsProfile.query.count() == 0 and JiraAssetsRun.query.count() == 0
    assert Asset.query.one().jira_object_id == '1'


def test_profile_form_validation(auth_client):
    resp = auth_client.post('/settings/jira-assets/profiles/new',
                            data=_profile_form(name='', map_value=[''], map_action=['']))
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert 'needs a name' in html and 'Map at least one' in html
    resp = auth_client.post('/settings/jira-assets/profiles/new',
                            data=_profile_form(map_action=['active', '', '']))
    assert resp.status_code == 400
    assert JiraAssetsProfile.query.count() == 0


def test_status_values_endpoint(auth_client):
    auth_client.post('/settings/jira-assets/profiles/new', data=_profile_form())
    profile = JiraAssetsProfile.query.one()
    objects = [laptop(1, 'a', 'Assigned'), laptop(2, 'b', 'Assigned'), laptop(3, 'c', 'Broken')]
    with patch.object(svc.JiraAssetsClient, 'from_connector', return_value=FakeClient(objects)):
        data = auth_client.get(f'/settings/jira-assets/profiles/{profile.id}/status-values').get_json()
    assert data['total'] == 3
    assert data['values'] == [{'value': 'Assigned', 'count': 2}, {'value': 'Broken', 'count': 1}]


def test_preview_without_connector_explains(auth_client):
    auth_client.post('/settings/jira-assets/profiles/new', data=_profile_form())
    profile = JiraAssetsProfile.query.one()
    resp = auth_client.post(f'/settings/jira-assets/profiles/{profile.id}/preview', follow_redirects=True)
    assert 'Atlassian API connector' in resp.get_data(as_text=True)


def test_connector_credentials_are_used(init_database):
    task = ConnectorTask(name='Atlassian', service='atlassian', enabled=False, polling_interval=3600, status='idle')
    task.set_credentials({'site_url': 'https://acme.atlassian.net', 'email': 'me@corp.com', 'api_token': 'tok'})
    db.session.add(task)
    db.session.commit()
    client = JiraAssetsClient.from_connector()
    assert client.site_url == 'https://acme.atlassian.net'
    assert client.session.auth == ('me@corp.com', 'tok')


def test_regular_users_cannot_open_the_sync(user_client):
    resp = user_client.get('/settings/jira-assets/')
    assert resp.status_code in (302, 403)


def test_status_values_endpoint_hides_error_details(auth_client):
    auth_client.post('/settings/jira-assets/profiles/new', data=_profile_form())
    profile = JiraAssetsProfile.query.one()
    with patch.object(svc.JiraAssetsClient, 'from_connector', side_effect=JiraAssetsError('internal detail')):
        resp = auth_client.get(f'/settings/jira-assets/profiles/{profile.id}/status-values')
    assert resp.status_code == 502
    assert 'internal detail' not in resp.get_data(as_text=True)
    assert 'Atlassian connector' in resp.get_json()['error']
