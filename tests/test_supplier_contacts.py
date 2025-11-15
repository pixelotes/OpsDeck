from src.models import Contact, Supplier

def test_contact_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida de un Contacto, que depende de un Proveedor.
    """
    
    # --- PREPARACIÓN: Crear un Proveedor primero ---
    # (No podemos usar la BD directamente, usamos el cliente para simular el flujo completo)
    auth_client.post('/suppliers/new', data={'name': 'Test Supplier for Contact'}, follow_redirects=True)
    
    # --- 1. CREAR CONTACTO ---
    # Asumimos que la ruta de contactos usa 'supplier_id' en el formulario
    response = auth_client.post('/contacts/new', data={
        'name': 'Test Contact',
        'email': 'contact@supplier.com',
        'supplier_id': '1' # Enlazado al Proveedor ID 1 que acabamos de crear
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Contact created successfully!' in response.data
    
    # Verifica que el contacto está en la BD
    with app.app_context():
        contact = Contact.query.get(1)
        assert contact is not None
        assert contact.name == 'Test Contact'
        assert contact.supplier_id == 1

    # --- 2. EDITAR CONTACTO ---
    response = auth_client.post('/contacts/1/edit', data={
        'name': 'Test Contact (Edited)',
        'email': 'edited@supplier.com',
        'supplier_id': '1'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Contact updated successfully!' in response.data
    
    # --- 3. ARCHIVAR CONTACTO ---
    response = auth_client.post('/contacts/1/archive', follow_redirects=True)
    assert response.status_code == 200
    assert b'has been archived' in response.data

    # Verifica que el contacto está archivado
    with app.app_context():
        contact = Contact.query.get(1)
        assert contact.is_archived == True