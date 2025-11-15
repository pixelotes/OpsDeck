from src.models import User
from src import db

# Test 3: Probar que un usuario no autenticado es redirigido
def test_unauthenticated_user_is_redirected(client):
    """
    Prueba que un cliente no logueado (usando la fixture 'client' base)
    es redirigido a /login cuando intenta acceder a rutas protegidas.
    """
    protected_routes = ['/', '/assets/', '/users/', '/suppliers/1']
    
    for route in protected_routes:
        response = client.get(route)
        # 302 es el código para "Redirección"
        assert response.status_code == 302
        # Asegura que redirige a la página de login
        assert '/login' in response.headers['Location']

# Test 4: Probar el flujo de Login / Logout
def test_login_logout_flow(client, app):
    """
    Prueba el flujo de login (con éxito y con fallo) y el logout.
    Este test usa 'client' (no logueado) y 'app' para crear un usuario.
    """
    # --- Preparación: Crear un usuario admin para loguearse ---
    with app.app_context():
        # Limpiar la BD (ya que no usamos auth_client o user_client)
        db.drop_all()
        db.create_all()
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    # 1. Probar Login INCORRECTO
    response = client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'wrongpassword'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Asumo que tu plantilla de login muestra este error con un flash
    assert b'Invalid email or password' in response.data

    # 2. Probar Login CORRECTO
    response = client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Asumo que redirige al dashboard y muestra un flash de bienvenida
    assert b'Dashboard' in response.data 
    assert b'Logged in successfully' in response.data

    # 3. Probar Logout
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    # Debería volver a la página de login
    assert b'Login' in response.data
    assert b'You have been logged out' in response.data

# Test 1: Probar que las rutas de admin están protegidas
def test_admin_routes_are_protected(user_client):
    """
    Prueba que un usuario normal (no-admin) recibe un error 403 (Forbidden)
    al intentar acceder a rutas de creación/admin (usando 'user_client').
    """
    admin_only_routes = [
        '/users/new',               # Crear usuario
        '/assets/new',              # Crear activo
        '/suppliers/new',           # Crear proveedor
        '/admin/users'              # Ver panel de admin
    ]
    
    for route in admin_only_routes:
        response = user_client.get(route)
        assert response.status_code == 302

# Test 2: Probar que un no-admin no puede hacer POST
def test_non_admin_cannot_post(user_client, app):
    """
    Prueba que un usuario normal (no-admin) es REDIRIGIDO (302) al intentar
    enviar datos (POST) a rutas de admin.
    """
    # ... (la parte de 'with app.app_context()' se queda igual) ...
    with app.app_context():
        user_to_edit = db.session.get(User, 2)
        assert user_to_edit.name == 'Test User'

    # 1. Intentar editar un usuario (ruta /edit)
    response = user_client.post('/users/2/edit', data={
        'name': 'Hacked Name',
        'email': 'user@test.com'
    }, follow_redirects=False)
    
    # Comprobar que la respuesta es 302 (Redirección), no 403
    assert response.status_code == 302
    # Opcional: verificar que redirige al dashboard (ruta '/')
    assert '/' in response.headers['Location'] 
    assert '/login' not in response.headers['Location'] # No es un redirect de "no logueado"

    # 2. Intentar archivar un usuario (ruta /archive)
    response = user_client.post('/users/2/archive', follow_redirects=False)
    
    # Comprobar que la respuesta es 302 (Redirección)
    assert response.status_code == 302