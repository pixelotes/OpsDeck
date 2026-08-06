from src.models import db, Asset, Policy

def test_linkable_objects_endpoint_auth(client):
    """Ensure endpoint refuses without authentication, in JSON.

    This asserted a 302 to the login page, which pinned the bug rather than the
    behaviour: the caller is TomSelect, and it parsed that login HTML as its options
    list. Now that the view is declared with @json_endpoint the guard answers 401 JSON.
    """
    response = client.get('/compliance/json/linkable-objects?type=Asset')
    assert response.status_code == 401
    assert response.is_json

def test_linkable_objects_assets(auth_client):
    """Test searching for Assets."""
    # Create a test asset
    asset = Asset(name="MacBook Pro M1", serial_number="SN-001", status="Active", cost=2000)
    db.session.add(asset)
    db.session.commit()

    response = auth_client.get('/compliance/json/linkable-objects?type=Asset&q=macbook')
    assert response.status_code == 200
    data = response.json
    assert len(data) >= 1
    assert data[0]['name'] == 'MacBook Pro M1'
    assert data[0]['details'] == 'SN-001'

def test_linkable_objects_policies(auth_client):
    """Test searching for Policies."""
    policy = Policy(title="Access Control Policy", category="Security", description="Desc")
    db.session.add(policy)
    db.session.commit()

    response = auth_client.get('/compliance/json/linkable-objects?type=Policy&q=access')
    assert response.status_code == 200
    data = response.json
    assert len(data) >= 1
    assert data[0]['name'] == 'Access Control Policy'
    assert data[0]['details'] == 'Security'

def test_linkable_objects_invalid_type(auth_client):
    """Test invalid type returns empty list."""
    response = auth_client.get('/compliance/json/linkable-objects?type=InvalidType')
    assert response.status_code == 200
    assert response.json == []

def test_linkable_objects_no_query(auth_client):
    """Test valid type with no query returns all (limit 50)."""
    response = auth_client.get('/compliance/json/linkable-objects?type=User')
    assert response.status_code == 200
    # Should return users (since auth_client creates a user)
    assert len(response.json) > 0 # At least the logged in user
