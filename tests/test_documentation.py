import pytest
from src.models import Documentation, User
from src import db

@pytest.fixture(scope='function')
def auth_client(client, app):
    with app.app_context():
        user = User(name='Test User', email='test@example.com', role='admin')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
    
    client.post('/login', data={'email': 'test@example.com', 'password': 'password'})
    yield client

def test_create_documentation(auth_client, app):
    response = auth_client.post('/documentation/new', data={
        'name': 'New Doc',
        'description': 'Doc Description',
        'external_link': 'http://example.com'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Entrada de documentaci\xc3\xb3n creada.' in response.data
    
    with app.app_context():
        doc = Documentation.query.filter_by(name='New Doc').first()
        assert doc is not None
        assert doc.description == 'Doc Description'

def test_edit_documentation(auth_client, app):
    with app.app_context():
        doc = Documentation(name='Old Name', description='Old Desc')
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

    response = auth_client.post(f'/documentation/{doc_id}/edit', data={
        'name': 'Updated Name',
        'description': 'Updated Desc'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Entrada de documentaci\xc3\xb3n actualizada.' in response.data
    
    with app.app_context():
        doc = Documentation.query.get(doc_id)
        assert doc.name == 'Updated Name'
        assert doc.description == 'Updated Desc'

def test_delete_documentation(auth_client, app):
    with app.app_context():
        doc = Documentation(name='To Delete')
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

    response = auth_client.post(f'/documentation/{doc_id}/delete', follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Entrada de documentaci\xc3\xb3n eliminada.' in response.data
    
    with app.app_context():
        doc = Documentation.query.get(doc_id)
        assert doc is None
