from src.models import Asset, User, AssetAssignment
from src import db # <-- 1. AÑADIR IMPORT

def test_asset_lifecycle(auth_client, app):
    """
    The basic asset lifecycle: create, edit, archive.
    """
    
    # --- 1. CREAR ACTIVO ---
    response = auth_client.post('/assets/new', data={
        'name': 'Test Laptop',
        'serial_number': 'TEST-SN-123',
        'status': 'Stored'
    }, follow_redirects=True)
    
    # The 400 should go away once models.py is fixed
    assert response.status_code == 200
    assert b'Asset created successfully' in response.data
    assert b'Test Laptop' in response.data
    
    # Check the database (asset id 1)
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        asset = db.session.get(Asset, 1)
        assert asset is not None
        assert asset.serial_number == 'TEST-SN-123'

    # --- 2. EDITAR ACTIVO ---
    response = auth_client.post('/assets/1/edit', data={
        'name': 'Test Laptop (Edited)',
        'serial_number': 'TEST-SN-456',
        'status': 'In Use'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Asset updated successfully' in response.data
    
    # Check the database
    with app.app_context():
        # 2. CORREGIR LegacyAPIWarning
        asset = db.session.get(Asset, 1)
        assert asset.name == 'Test Laptop (Edited)'
        assert asset.serial_number == 'TEST-SN-456'

    # --- 3. ARCHIVAR ACTIVO ---
    response = auth_client.post('/assets/1/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data

def test_asset_checkout_checkin(auth_client, app):
    """
    Prueba el flujo de asignar (checkout) y retornar (checkin) un activo.
    """
    from src.models import Location
    
    # --- PREPARACIÓN ---
    # 1. Create the asset (id 1)
    auth_client.post('/assets/new', data={'name': 'Checkout Laptop', 'status': 'Stored'}, follow_redirects=True)
    
    # 2. Create a user and a location for the test
    with app.app_context():
        checkout_user = User(name='Checkout User', email='checkout@test.com', role='user')
        db.session.add(checkout_user)
        test_location = Location(name='Test Office')
        db.session.add(test_location)
        db.session.commit()
        user_id = checkout_user.id
        location_id = test_location.id

    # --- 1. PROBAR CHECKOUT ---
    response = auth_client.post('/assets/1/checkout', data={
        'user_id': str(user_id),
        'location_mode': 'keep'  # Keep at current location
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'has been checked out to Checkout User' in response.data
    
    # Check the database
    with app.app_context():
        asset = db.session.get(Asset, 1)
        assert asset.user_id == user_id
        assignment = db.session.query(AssetAssignment).first()
        assert assignment is not None
        assert assignment.checked_in_date is None

    # --- 2. PROBAR CHECKIN (now requires return_location_id) ---
    response = auth_client.post('/assets/1/checkin', data={
        'return_location_id': str(location_id)
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'has been returned to Test Office' in response.data
    
    # Check the database
    with app.app_context():
        asset = db.session.get(Asset, 1)
        assert asset.user_id is None
        assert asset.location_id == location_id  # Location should be set
        assignment = db.session.query(AssetAssignment).first()
        assert assignment.checked_in_date is not None