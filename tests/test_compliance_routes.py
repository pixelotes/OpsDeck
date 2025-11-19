import pytest
from src.models import Framework, FrameworkControl, Asset, ComplianceLink, User
from src import db

@pytest.fixture(scope='function')
def compliance_data(app):
    with app.app_context():
        # Create Frameworks
        fw1 = Framework(name='Active FW', description='Active', is_active=True)
        fw2 = Framework(name='Inactive FW', description='Inactive', is_active=False)
        db.session.add_all([fw1, fw2])
        db.session.commit()

        # Create Controls
        c1 = FrameworkControl(framework_id=fw1.id, control_id='A.1', name='Control 1', description='Desc 1')
        c2 = FrameworkControl(framework_id=fw2.id, control_id='B.1', name='Control 2', description='Desc 2')
        db.session.add_all([c1, c2])
        db.session.commit()

        # Create Asset
        asset = Asset(name='Test Asset', status='In Use')
        db.session.add(asset)
        db.session.commit()

        yield {
            'fw1_id': fw1.id,
            'fw2_id': fw2.id,
            'c1_id': c1.id,
            'c2_id': c2.id,
            'asset_id': asset.id
        }

def test_get_frameworks(user_client, compliance_data):
    response = user_client.get('/compliance/frameworks')
    assert response.status_code == 200
    data = response.json
    assert len(data) == 1
    assert data[0]['name'] == 'Active FW'

def test_get_framework_controls(user_client, compliance_data):
    # Active framework
    response = user_client.get(f"/compliance/frameworks/{compliance_data['fw1_id']}/controls")
    assert response.status_code == 200
    data = response.json
    assert len(data) == 1
    assert data[0]['control_id'] == 'A.1'

    # Inactive framework
    response = user_client.get(f"/compliance/frameworks/{compliance_data['fw2_id']}/controls")
    assert response.status_code == 400
    assert 'Framework is disabled' in response.json['error']

def test_create_compliance_link(user_client, compliance_data):
    payload = {
        'framework_control_id': compliance_data['c1_id'],
        'linkable_id': compliance_data['asset_id'],
        'linkable_type': 'Asset',
        'description': 'Test Link'
    }
    response = user_client.post('/compliance/link', json=payload)
    assert response.status_code == 201
    assert response.json['status'] == 'success'

    # Verify in DB
    link = ComplianceLink.query.first()
    assert link is not None
    assert link.description == 'Test Link'

def test_create_duplicate_link(user_client, compliance_data):
    payload = {
        'framework_control_id': compliance_data['c1_id'],
        'linkable_id': compliance_data['asset_id'],
        'linkable_type': 'Asset',
        'description': 'Test Link'
    }
    # First creation
    user_client.post('/compliance/link', json=payload)
    
    # Duplicate creation
    response = user_client.post('/compliance/link', json=payload)
    assert response.status_code == 409
    assert 'Link already exists' in response.json['error']

def test_link_to_disabled_framework(user_client, compliance_data):
    payload = {
        'framework_control_id': compliance_data['c2_id'], # Belongs to inactive FW
        'linkable_id': compliance_data['asset_id'],
        'linkable_type': 'Asset',
        'description': 'Should fail'
    }
    response = user_client.post('/compliance/link', json=payload)
    assert response.status_code == 400
    assert 'Framework is disabled' in response.json['error']

def test_delete_compliance_link(user_client, compliance_data, app):
    # Create link manually
    with app.app_context():
        link = ComplianceLink(
            framework_control_id=compliance_data['c1_id'],
            linkable_id=compliance_data['asset_id'],
            linkable_type='Asset',
            description='To Delete'
        )
        db.session.add(link)
        db.session.commit()
        link_id = link.id

    # Delete
    response = user_client.delete(f'/compliance/link/{link_id}')
    assert response.status_code == 200
    assert response.json['status'] == 'success'

    # Verify deletion
    with app.app_context():
        assert db.session.get(ComplianceLink, link_id) is None
