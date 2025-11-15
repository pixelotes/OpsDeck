import io
import os
from src.models import Supplier, Attachment
from src import db

def test_supplier_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida completo de un proveedor:
    1. Creación
    2. Edición
    3. Archivado
    """
    
    # --- 1. CREAR PROVEEDOR ---
    response = auth_client.post('/suppliers/new', data={
        'name': 'Test Supplier Inc.',
        'email': 'contact@testsupplier.com',
        'compliance_status': 'Pending'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Test Supplier Inc.' in response.data
    assert b'Supplier created successfully!' in response.data

    # Verifica en la BD (El ID 1 será el primer proveedor)
    with app.app_context():
        supplier = db.session.get(Supplier, 1)
        assert supplier is not None
        assert supplier.name == 'Test Supplier Inc.'

    # --- 2. EDITAR PROVEEDOR ---
    response = auth_client.post('/suppliers/1/edit', data={
        'name': 'Test Supplier (Edited)',
        'email': 'edited@testsupplier.com',
        'compliance_status': 'Approved'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Test Supplier (Edited)' in response.data
    assert b'Supplier updated successfully!' in response.data

    # Verifica en la BD
    with app.app_context():
        supplier = db.session.get(Supplier, 1)
        assert supplier.name == 'Test Supplier (Edited)'
        assert supplier.compliance_status == 'Approved'

    # --- 3. ARCHIVAR PROVEEDOR ---
    response = auth_client.post('/suppliers/1/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data
    
    # Verifica en la BD
    with app.app_context():
        supplier = db.session.get(Supplier, 1)
        assert supplier.is_archived == True

def test_supplier_attachment_upload(auth_client, app):
    """
    Prueba la subida de un adjunto a un proveedor.
    """
    # Asegurar que el UPLOAD_FOLDER existe
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Primero, crea el proveedor
    response = auth_client.post('/suppliers/new', data={'name': 'Supplier for Attachments'}, follow_redirects=True)
    assert response.status_code == 200
    
    # Simula la subida de un archivo con el referrer correcto
    data = {
        'supplier_id': '1',
        'file': (io.BytesIO(b"dummy file content"), 'test_contract.pdf')
    }
    
    # NO usar follow_redirects, usar environ_base para establecer HTTP_REFERER
    response = auth_client.post(
        '/attachments/upload', 
        data=data, 
        content_type='multipart/form-data',
        environ_base={'HTTP_REFERER': '/suppliers/1'}
    )

    # Debe ser un redirect (302/303)
    assert response.status_code in [302, 303]
    
    # Verifica que el adjunto está en la BD
    with app.app_context():
        attachment = db.session.query(Attachment).filter_by(
            linkable_id=1, 
            linkable_type='Supplier'
        ).first()
        assert attachment is not None
        assert attachment.filename == 'test_contract.pdf'

    # Verifica que el archivo aparece en la página de detalles
    response = auth_client.get('/suppliers/1')
    assert b'test_contract.pdf' in response.data