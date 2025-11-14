import io
from src import db
from src.models import Attachment, Supplier, User, Asset

# --- Test 10: Attachments ---

def test_attachment_deletion(auth_client, app):
    """
    Test 10: Prueba que un adjunto puede ser eliminado.
    """
    # --- 1. Setup: Crear un Proveedor y subir un Adjunto ---
    auth_client.post('/suppliers/new', data={'name': 'Supplier para Borrar Adjunto'}, follow_redirects=True)

    data = {
        'supplier_id': '1',
        'file': (io.BytesIO(b"dummy data"), 'file_to_delete.pdf')
    }
    auth_client.post(
        '/attachments/upload',
        data=data, 
        follow_redirects=True, 
        content_type='multipart/form-data'
    )
    
    # Verifica que el adjunto existe (ID 1)
    with app.app_context():
        attachment = db.session.get(Attachment, 1)
        assert attachment is not None
        assert attachment.filename == 'file_to_delete.pdf'
        
    # --- 2. Acción: Borrar el adjunto ---
    response = auth_client.post('/attachments/delete/1', follow_redirects=True)
    assert response.status_code == 200
    assert b'Attachment deleted successfully' in response.data

    # --- 3. Verify: Comprobar que ya no existe ---
    with app.app_context():
        attachment = db.session.get(Attachment, 1)
        assert attachment is None
        
    # Y que ya no aparece en la página de detalles
    response = auth_client.get('/suppliers/1')
    assert b'file_to_delete.pdf' not in response.data

# --- Test 11: User Inventory PDF ---

def test_user_inventory_snapshot_pdf(auth_client, app):
    """
    Test 11: Prueba que se genera un snapshot PDF para un usuario.
    No prueba el contenido del PDF, solo que el registro del adjunto se crea.
    """
    # --- 1. Setup: Asignar un activo al Usuario de Prueba ---
    # auth_client crea Admin (ID 1) y User (ID 2)
    with app.app_context():
        # Primero CREA el usuario
        test_user = User(name='Test User', email='user@test.com', role='user')
        db.session.add(test_user)
        db.session.commit() # El usuario ahora existe, con ID 2
        
        asset = Asset(
            name='Laptop para Snapshot',
            status='In Use',
            user=test_user # Asignar al usuario
        )
        db.session.add(asset)
        db.session.commit()
        
        assert test_user.id == 2 

    # --- 2. Acción: Generar el snapshot (como Admin) ---
    response = auth_client.post(f'/users/2/inventory/generate', follow_redirects=True)
    assert response.status_code == 200
    assert b'Snapshot de inventario generado' in response.data

    # --- 3. Verify: Comprobar que el adjunto existe ---
    with app.app_context():
        # Buscar el adjunto enlazado al Usuario ID 2
        attachment = db.session.query(Attachment).filter_by(
            linkable_type='User',
            linkable_id=2
        ).first()
        
        assert attachment is not None
        assert attachment.filename.startswith('Inventory_Test_User')
        assert attachment.filename.endswith('.pdf')
    
    # Verificar que aparece en la página de detalles del usuario
    response = auth_client.get('/users/2')
    assert b'Inventory_Test_User' in response.data