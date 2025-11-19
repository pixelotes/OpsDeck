import pytest
from src.models import Asset, Supplier, Policy, Framework, FrameworkControl, ComplianceLink, User
from src import db

@pytest.fixture(scope='function')
def ui_data(app):
    with app.app_context():
        # Create User for login
        user = User(name='Test User', email='test@example.com', role='admin')
        user.set_password('password')
        db.session.add(user)
        
        # Create objects to view
        asset = Asset(name='Test Asset UI', status='In Use')
        supplier = Supplier(name='Test Supplier UI')
        policy = Policy(title='Test Policy UI', category='General')
        
        db.session.add_all([asset, supplier, policy])
        db.session.commit()
        
        yield {
            'user': user,
            'asset_id': asset.id,
            'supplier_id': supplier.id,
            'policy_id': policy.id
        }

def test_render_asset_detail(client, ui_data):
    client.post('/login', data={'email': 'test@example.com', 'password': 'password'})
    response = client.get(f"/assets/{ui_data['asset_id']}")
    assert response.status_code == 200
    assert b'Compliance Links' in response.data

def test_render_supplier_detail(client, ui_data):
    client.post('/login', data={'email': 'test@example.com', 'password': 'password'})
    response = client.get(f"/suppliers/{ui_data['supplier_id']}")
    assert response.status_code == 200
    assert b'Compliance Links' in response.data

def test_render_policy_detail(client, ui_data):
    client.post('/login', data={'email': 'test@example.com', 'password': 'password'})
    response = client.get(f"/policies/{ui_data['policy_id']}")
    assert response.status_code == 200
    assert b'Compliance Links' in response.data
