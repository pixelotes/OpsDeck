from src.models import Peripheral, User
from src import db # <-- 1. AÑADIR IMPORT

def test_peripheral_lifecycle(auth_client, app):
    """
    The basic peripheral lifecycle: create, edit, archive.
    """
    
    # --- 1. CREAR PERIFÉRICO ---
    response = auth_client.post('/peripherals/new', data={
        'name': 'Test Keyboard',
        'serial_number': 'PERIPH-SN-123',
        'status': 'Stored'
    }, follow_redirects=True)
    
    # The 400 should go away once models.py is fixed
    assert response.status_code == 200
    assert b'Peripheral created successfully' in response.data
    assert b'Test Keyboard' in response.data
    
    # Check the database (peripheral id 1)
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
    
    # Check the database
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
    Checking a peripheral out to a user and back in again.
    """
    # --- PREPARACIÓN ---
    # 1. Create the peripheral (id 1)
    auth_client.post('/peripherals/new', data={'name': 'Checkout Mouse', 'status': 'Stored'}, follow_redirects=True)
    
    # 2. Create a user (id 2)
    # 3. Create a location for the check-in
    with app.app_context():
        from src.models import Location
        checkout_user = User(name='Checkout User', email='checkout@test.com', role='user')
        location = Location(name='Storage Room')
        db.session.add(checkout_user)
        db.session.add(location)
        db.session.commit()
        assert checkout_user.id == 2
        location_id = location.id

    # --- 1. PROBAR CHECKOUT ---
    response = auth_client.post('/peripherals/1/checkout', data={
        'user_id': '2'  # assign to user id 2
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'has been checked out to Checkout User' in response.data
    
    # Check the database
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral.user_id == 2

    # --- 2. PROBAR CHECKIN ---
    response = auth_client.post('/peripherals/1/checkin', data={
        'return_location_id': str(location_id)
    }, follow_redirects=True)
    assert response.status_code == 200
    # Updated assertion to match the new flash message format
    assert b'has been checked in from Checkout User to Storage Room' in response.data
    
    # Check the database
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        peripheral = db.session.get(Peripheral, 1)
        assert peripheral.user_id is None