from src.models import User
from src import db

def test_user_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida completo de un usuario:
    1. Creation
    2. Editing
    3. Archivado
    
    Usamos 'auth_client' para estar logueados como admin.
    Usamos 'app' para poder acceder al contexto de la BD y verificar.
    """
    
    # --- 1. CREAR USUARIO ---
    response = auth_client.post('/users/new', data={
        'name': 'Test User',
        'email': 'test@example.com',
        'department': 'Testing',
        'job_title': 'QA'
    }, follow_redirects=True)
    
    # The list page loaded and shows the new user
    assert response.status_code == 200
    assert b'Test User' in response.data
    assert b'User created successfully!' in response.data

    # The user exists in the database
    with app.app_context():
        # El ID 1 es el admin, el nuevo usuario debe ser el ID 2
        user = db.session.get(User, 2)
        assert user is not None
        assert user.name == 'Test User'
        assert user.department == 'Testing'

    # --- 2. EDITAR USUARIO ---
    response = auth_client.post('/users/2/edit', data={
        'name': 'Test User (Edited)',
        'email': 'test@example.com',
        'department': 'Testing-Edited',
        'job_title': 'QA Edited'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Test User (Edited)' in response.data
    assert b'User updated successfully!' in response.data

    # The changes reached the database
    with app.app_context():
        user = db.session.get(User, 2)
        assert user.name == 'Test User (Edited)'
        assert user.department == 'Testing-Edited'

    # --- 3. ARCHIVAR USUARIO ---
    response = auth_client.post('/users/2/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data
    
    # The user is archived in the database
    with app.app_context():
        user = db.session.get(User, 2)
        assert user.is_archived
        
    # It no longer appears in the main list
    response = auth_client.get('/users/')
    assert b'Test User (Edited)' not in response.data
    
    # It does appear in the archived list
    response = auth_client.get('/users/archived')
    assert b'Test User (Edited)' in response.data


def test_user_known_ip(init_database):
    """Test UserKnownIP model creation and repr."""
    from src.models import UserKnownIP
    
    db = init_database
    user = User(name="IP User", email="ip@test.com")
    db.session.add(user)
    db.session.commit()
    
    known_ip = UserKnownIP(
        user_id=user.id,
        ip_address="192.168.1.100"
    )
    db.session.add(known_ip)
    db.session.commit()
    
    assert repr(known_ip) == f"<UserKnownIP 192.168.1.100 for User {user.id}>"
    assert user.known_ips[0] == known_ip