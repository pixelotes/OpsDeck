from src.models import User

def test_user_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida completo de un usuario:
    1. Creación
    2. Edición
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
    
    # Comprueba que la página de lista se cargó y muestra al nuevo usuario
    assert response.status_code == 200
    assert b'Test User' in response.data
    assert b'User created successfully!' in response.data

    # Verifica que el usuario existe en la BD
    with app.app_context():
        # El ID 1 es el admin, el nuevo usuario debe ser el ID 2
        user = User.query.get(2)
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

    # Verifica que los cambios están en la BD
    with app.app_context():
        user = User.query.get(2)
        assert user.name == 'Test User (Edited)'
        assert user.department == 'Testing-Edited'

    # --- 3. ARCHIVAR USUARIO ---
    response = auth_client.post('/users/2/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data
    
    # Verifica que el usuario está archivado en la BD
    with app.app_context():
        user = User.query.get(2)
        assert user.is_archived == True
        
    # Verifica que ya no aparece en la lista principal
    response = auth_client.get('/users/')
    assert b'Test User (Edited)' not in response.data
    
    # Verifica que sí aparece en la lista de archivados
    response = auth_client.get('/users/archived')
    assert b'Test User (Edited)' in response.data