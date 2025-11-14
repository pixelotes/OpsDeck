from src.models import Peripheral, User, PeripheralAssignment
from src import db # <-- 1. AÑADIR IMPORT

def test_peripheral_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida básico de un Periférico: Crear, Editar, Archivar.
    """
    
    # --- 1. CREAR PERIFÉRICO ---
    response = auth_client.post('/peripherals/new', data={
        'name': 'Test Keyboard',
        'serial_number': 'PERIPH-SN-123',
        'status': 'Stored'
    }, follow_redirects=True)
    
    # El error 400 debería resolverse arreglando models.py
    assert response.status_code == 200
    assert b'Peripheral created successfully' in response.data
    assert b'Test Keyboard' in response.data
    
    # Verifica en la BD (Peripheral ID 1)
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral is not None
        assert peripheral.serial_number == 'PERIPH-SN-123'

    # --- 2. EDITAR PERIFÉRICO ---
    response = auth_client.post('/peripherals/1/edit', data={
        'name': 'Test Keyboard (Edited)',
        'serial_number': 'PERIPH-SN-456',
        'status': 'In Use'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Peripheral updated successfully' in response.data
    
    # Verifica en la BD
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral.name == 'Test Keyboard (Edited)'

    # --- 3. ARCHIVAR PERIFÉRICO ---
    response = auth_client.post('/peripherals/1/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data

def test_peripheral_checkout_checkin(auth_client, app):
    """
    Prueba el flujo de asignar (checkout) y retornar (checkin) un periférico.
    """
    # --- PREPARACIÓN ---
    # 1. Crear el Periférico (Peripheral ID 1)
    auth_client.post('/peripherals/new', data={'name': 'Checkout Mouse', 'status': 'Stored'}, follow_redirects=True)
    
    # 2. Crear un Usuario (User ID 2)
    with app.app_context():
        checkout_user = User(name='Checkout User', email='checkout@test.com', role='user')
        db.session.add(checkout_user) # <-- 3. ESTO AHORA FUNCIONA
        db.session.commit()
        assert checkout_user.id == 2

    # --- 1. PROBAR CHECKOUT ---
    response = auth_client.post('/peripherals/1/checkout', data={
        'user_id': '2' # Asignar al User ID 2
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'has been checked out to Checkout User' in response.data
    
    # Verifica en la BD
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral.user_id == 2

    # --- 2. PROBAR CHECKIN ---
    response = auth_client.post('/peripherals/1/checkin', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been checked in' in response.data
    
    # Verifica en la BD
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral.user_id is None