from src.models import User
from src import db


def _api_user(app, token="test-token-123", name="API User", email="api@test.com"):
    """Create a user with an API token and return the auth headers."""
    with app.app_context():
        user = User(name=name, email=email)
        user.api_token = token
        db.session.add(user)
        db.session.commit()
    return {'Authorization': f'Bearer {token}'}


def test_api_security(client, app):
    """
    Test API security and functionality.
    """
    # 1. Access without token -> 401
    response = client.get('/api/v1/users')
    assert response.status_code == 401
    assert b'Missing' in response.data or b'missing' in response.data

    # Setup User with Token
    api_token = "test-token-123"
    with app.app_context():
        # Create user manually to avoid auth_client dependency logic if any
        # Assuming existing users or creating new one
        db = app.extensions['sqlalchemy']
        user = User(name="API User", email="api@test.com")
        user.api_token = api_token 
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    # 2. Access with Invalid Token -> 401
    response = client.get('/api/v1/users', headers={'Authorization': 'Bearer invalid-token'})
    assert response.status_code == 401

    # 3. Access with Valid Token -> 200
    headers = {'Authorization': f'Bearer {api_token}'}
    response = client.get('/api/v1/users', headers=headers)
    assert response.status_code == 200
    # Check if we get a list (pagination format usually has 'items' or directly list depending on config)
    # Flask-Smorest typically returns list if many=True? Or paginated object?
    # Helper uses @blueprint.paginate(Page)
    # default Page pagination returns:
    # { "items": [...], "meta": {...} } or list?
    # Inspect response structure
    response.get_json()
    # It seems flask-smorest pagination defaults might wrap it. 
    # But let's check basic success first.

    # 4. Detail Endpoint
    response = client.get(f'/api/v1/users/{user_id}', headers=headers)
    assert response.status_code == 200
    assert response.json['name'] == "API User"


def test_new_read_only_endpoints(client, app):
    """Suppliers, contacts, changes and requests expose protected GET lists."""
    headers = _api_user(app)
    for path in ('/api/v1/suppliers', '/api/v1/contacts', '/api/v1/changes', '/api/v1/requests'):
        # Unauthenticated -> 401
        assert client.get(path).status_code == 401
        # Authenticated -> 200 list
        resp = client.get(path, headers=headers)
        assert resp.status_code == 200, path
        assert isinstance(resp.get_json(), list), path


def test_requests_crud_via_api(client, app):
    headers = _api_user(app)

    # Create (requester defaults to the API user)
    resp = client.post('/api/v1/requests', headers=headers, json={
        'title': 'API laptop request',
        'request_type': 'Hardware',
        'priority': 'High',
        'external_ref': 'REQ-001',
    })
    assert resp.status_code == 201
    rid = resp.json['id']
    assert resp.json['status'] == 'Pending'
    assert resp.json['requester_id'] is not None

    # Detail
    resp = client.get(f'/api/v1/requests/{rid}', headers=headers)
    assert resp.status_code == 200
    assert resp.json['title'] == 'API laptop request'

    # Upsert by external_ref returns the same record (200)
    resp = client.post('/api/v1/requests', headers=headers, json={
        'title': 'API laptop request (updated)',
        'external_ref': 'REQ-001',
    })
    assert resp.status_code == 200
    assert resp.json['id'] == rid
    assert resp.json['title'] == 'API laptop request (updated)'


def test_request_assignee_resolution(client, app):
    headers = _api_user(app)
    with app.app_context():
        u = User(name="Resolver", email="resolver@test.com")
        db.session.add(u)
        db.session.commit()
    resp = client.post('/api/v1/requests', headers=headers, json={
        'title': 'Assigned via API',
        'assignee': 'resolver@test.com',
    })
    assert resp.status_code == 201
    assert resp.json['assignee_id'] is not None


def test_changes_get_after_post(client, app):
    headers = _api_user(app)
    resp = client.post('/api/v1/changes', headers=headers, json={
        'title': 'API change', 'external_ref': 'CHG-001',
    })
    assert resp.status_code == 201
    cid = resp.json['id']

    resp = client.get(f'/api/v1/changes/{cid}', headers=headers)
    assert resp.status_code == 200
    assert resp.json['title'] == 'API change'

    resp = client.get('/api/v1/changes', headers=headers)
    assert resp.status_code == 200
    assert any(c['id'] == cid for c in resp.json)
