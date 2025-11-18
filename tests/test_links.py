import pytest
from src.models import Link, Tag, User, Group, Software
from src import db

def test_list_links_empty(auth_client):
    """Test listing links when there are none."""
    response = auth_client.get('/links/')
    assert response.status_code == 200
    assert b'Links' in response.data
    assert b'No entries found' in response.data

def test_create_link(auth_client, app):
    """Test creating a new link."""
    # Create a tag and software first
    with app.app_context():
        tag = Tag(name='TestTag')
        software = Software(name='TestSoftware')
        db.session.add_all([tag, software])
        db.session.commit()
        tag_id = tag.id
        software_id = software.id

    data = {
        'name': 'New Link',
        'url': 'https://example.com',
        'description': 'A test link',
        'owner': 'User-1', # Assuming admin user has ID 1
        'software_id': software_id,
        'tags': [tag_id]
    }
    
    response = auth_client.post('/links/new', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Enlace creado.' in response.data
    assert b'New Link' in response.data
    assert b'https://example.com' in response.data

    # Verify in DB
    with app.app_context():
        link = Link.query.first()
        assert link is not None
        assert link.name == 'New Link'
        assert link.url == 'https://example.com'
        assert link.owner_id == 1
        assert link.owner_type == 'User'
        assert link.software_id == software_id
        assert len(link.tags) == 1
        assert link.tags[0].name == 'TestTag'

def test_edit_link(auth_client, app):
    """Test editing an existing link."""
    # Create a link first
    with app.app_context():
        link = Link(name='Old Name', url='http://old.com')
        db.session.add(link)
        db.session.commit()
        link_id = link.id

    data = {
        'name': 'Updated Name',
        'url': 'https://updated.com',
        'description': 'Updated description',
        'owner': '', # Clear owner
        'software_id': '',
        'tags': []
    }

    response = auth_client.post(f'/links/{link_id}/edit', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Enlace actualizado.' in response.data
    assert b'Updated Name' in response.data
    assert b'https://updated.com' in response.data

    # Verify in DB
    with app.app_context():
        link = Link.query.get(link_id)
        assert link.name == 'Updated Name'
        assert link.url == 'https://updated.com'
        assert link.owner_id is None

def test_delete_link(auth_client, app):
    """Test deleting a link."""
    # Create a link first
    with app.app_context():
        link = Link(name='To Delete', url='http://delete.me')
        db.session.add(link)
        db.session.commit()
        link_id = link.id

    response = auth_client.post(f'/links/{link_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Enlace eliminado.' in response.data

    # Verify in DB
    with app.app_context():
        link = Link.query.get(link_id)
        assert link is None
