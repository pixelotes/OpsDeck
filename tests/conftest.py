import pytest
from src import create_app, db
from src.models import User

@pytest.fixture(scope='module')
def app():
    """Crea una instancia de la aplicación Flask para pruebas."""
    app = create_app()
    app.config.update({
        "TESTING": True,
        # Usar una base de datos en memoria para las pruebas
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,  # Deshabilita CSRF para facilitar los POSTs
        "SECRET_KEY": "test-secret-key" # Clave simple para pruebas
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture(scope='module')
def client(app):
    """Un cliente de pruebas para la aplicación."""
    return app.test_client()

@pytest.fixture(scope='module')
def runner(app):
    """Un runner para los comandos CLI de Flask."""
    return app.test_cli_runner()

@pytest.fixture(scope='function')
def auth_client(client, app):
    """
    Un cliente de pruebas que ya está autenticado como administrador.
    Se ejecuta 'por función', por lo que cada test empieza "limpio".
    """
    with app.app_context():
        # Borra todos los datos antes de cada test
        db.drop_all()
        db.create_all()
        
        # Crea el usuario admin
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

    # Inicia sesión
    client.post('/login', data={
        'email': 'admin@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    yield client # El test se ejecuta aquí, con el cliente logueado

    # Cierra sesión después del test
    client.get('/logout', follow_redirects=True)

    with app.app_context():
        db.session.remove()

@pytest.fixture(scope='function')
def user_client(client, app):
    """
    Un cliente de pruebas que ya está autenticado como un USUARIO NORMAL.
    Se ejecuta 'por función', por lo que cada test empieza "limpio".
    """
    with app.app_context():
        # Borra todos los datos antes de cada test
        db.drop_all()
        db.create_all()
        
        # Crea el usuario admin (ID 1)
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        
        # Crea el usuario normal (ID 2)
        user = User(name='Test User', email='user@test.com', role='user')
        user.set_password('password')
        
        db.session.add_all([admin, user])
        db.session.commit()

    # Inicia sesión como el usuario normal
    client.post('/login', data={
        'email': 'user@test.com',
        'password': 'password'
    }, follow_redirects=True)
    
    yield client # El test se ejecuta aquí, con el cliente logueado

    # Cierra sesión después del test
    client.get('/logout', follow_redirects=True)

    with app.app_context():
        db.session.remove()