import io
import os
from src import db
from src.models import Attachment, Supplier, User, Asset

# --- Test 10: Attachments ---

def test_attachment_deletion(auth_client, app):
    """
    Test 10: Prueba que un adjunto puede ser eliminado.
    """
    # Asegurar que el UPLOAD_FOLDER existe
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # --- 1. Setup: Crear un Proveedor y subir un Adjunto ---
    response = auth_client.post('/suppliers/new', data={'name': 'Supplier para Borrar Adjunto'}, follow_redirects=True)
    assert response.status_code == 200

    data = {
        'supplier_id': '1',
        'file': (io.BytesIO(b"dummy data"), 'file_to_delete.pdf')
    }
    
    # NO usar follow_redirects, establecer HTTP_REFERER con environ_base
    response = auth_client.post(
        '/attachments/upload',
        data=data, 
        content_type='multipart/form-data',
        environ_base={'HTTP_REFERER': '/suppliers/1'}
    )
    
    # Debe ser un redirect (302 o 303)
    assert response.status_code in [302, 303], f"Expected redirect, got {response.status_code}"
    
    # Verificar que el adjunto se creó en la BD
    with app.app_context():
        attachment = db.session.get(Attachment, 1)
        assert attachment is not None
        assert attachment.filename == 'file_to_delete.pdf'
        assert attachment.linkable_type == 'Supplier'
        assert attachment.linkable_id == 1
        
    # Verificar que aparece en la página del supplier
    response = auth_client.get('/suppliers/1')
    assert b'file_to_delete.pdf' in response.data
        
    # --- 2. Acción: Borrar el adjunto ---
    response = auth_client.post(
        '/attachments/delete/1',
        environ_base={'HTTP_REFERER': '/suppliers/1'}
    )
    
    # Debe ser un redirect
    assert response.status_code in [302, 303], f"Expected redirect, got {response.status_code}"

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
    # Asegurar que el UPLOAD_FOLDER existe
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # --- 1. Setup: Asignar un activo al Usuario de Prueba ---
    with app.app_context():
        # Primero CREA el usuario
        test_user = User(name='Test User', email='user@test.com', role='user')
        db.session.add(test_user)
        db.session.commit()
        user_id = test_user.id
        
        asset = Asset(
            name='Laptop para Snapshot',
            status='In Use',
            user_id=user_id
        )
        db.session.add(asset)
        db.session.commit()

    # --- 2. Acción: Generar el snapshot (como Admin) ---
    response = auth_client.post(f'/users/{user_id}/inventory/generate', follow_redirects=True)
    assert response.status_code == 200
    # Buscar variaciones del mensaje
    assert (b'Snapshot de inventario generado' in response.data or 
            b'inventory snapshot generated' in response.data.lower() or
            b'Inventory snapshot generated' in response.data)

    # --- 3. Verify: Comprobar que el adjunto existe ---
    with app.app_context():
        # Buscar el adjunto enlazado al Usuario
        attachment = db.session.query(Attachment).filter_by(
            linkable_type='User',
            linkable_id=user_id
        ).first()
        
        assert attachment is not None
        assert attachment.filename.startswith('Inventory_Test_User')
        assert attachment.filename.endswith('.pdf')
    
    # Verificar que aparece en la página de detalles del usuario
    response = auth_client.get(f'/users/{user_id}')
    assert b'Inventory_Test_User' in response.data