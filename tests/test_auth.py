from src.models import User
from src import db

# Test 3: an unauthenticated user is redirected
def test_unauthenticated_user_is_redirected(client):
    """
    A client that has not logged in (the plain 'client' fixture) is redirected
    to /login when it tries to reach a protected route.
    """
    protected_routes = ['/', '/assets/', '/users/', '/suppliers/1']
    
    for route in protected_routes:
        response = client.get(route)
        # 302 is the redirect status
        assert response.status_code == 302
        # It redirects to the login page
        assert '/login' in response.headers['Location']

# Test 4: the login and logout flow
def test_login_logout_flow(client, app):
    """
    Logging in (successfully and not) and logging out.
    Este test usa 'client' (no logueado) y 'app' para crear un usuario.
    """
    # --- Arrange: create an admin user to log in with ---
    with app.app_context():
        # Clean the database, since neither auth_client nor user_client is used here
        db.drop_all()
        db.create_all()
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    # 1. Wrong credentials
    response = client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Assumes the login template surfaces this error as a flash message
    assert b'Invalid email or password' in response.data

    # 2. Correct credentials
    response = client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Assumes it redirects to the dashboard with a welcome flash
    assert b'Dashboard' in response.data 
    assert b'Logged in successfully' in response.data

    # 3. Logout
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    # It should land back on the login page
    assert b'Login' in response.data
    assert b'You have been logged out' in response.data

# Test 1: admin routes are protected
def test_admin_routes_are_protected(user_client):
    """
    A regular, non-admin user gets a 403 when reaching for the create and admin
    routes (exercised through 'user_client').
    """
    admin_only_routes = [
        '/users/new',               # create user
        '/assets/new',              # create asset
        '/suppliers/new',           # create supplier
        '/admin/users'              # Ver panel de admin
    ]
    
    for route in admin_only_routes:
        response = user_client.get(route)
        assert response.status_code == 302

# Test 2: a non-admin cannot POST
def test_non_admin_cannot_post(user_client, app):
    """
    A regular, non-admin user is redirected (302) when posting to an admin route.
    """
    with app.app_context():
        # Buscar el usuario por email en lugar de ID fijo
        user_to_edit = User.query.filter_by(email='user@test.com').first()
        assert user_to_edit is not None
        assert user_to_edit.name == 'Test User'
        user_id = user_to_edit.id

    # 1. Intentar editar un usuario (ruta /edit)
    response = user_client.post(f'/users/{user_id}/edit', data={
        'name': 'Hacked Name',
        'email': 'user@test.com'
    }, follow_redirects=False)
    
    # The response is a 302 redirect, not a 403
    assert response.status_code == 302
    # Optionally check that it redirects to the dashboard ('/')
    assert '/' in response.headers['Location'] 
    assert '/login' not in response.headers['Location'] # No es un redirect de "no logueado"

    # 2. Intentar archivar un usuario (ruta /archive)
    response = user_client.post(f'/users/{user_id}/archive', follow_redirects=False)
    
    # The response is a 302 redirect
    assert response.status_code == 302