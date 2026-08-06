from src.models import Contact
from src import db

def test_contact_lifecycle(auth_client, app):
    """
    Prueba el ciclo de vida de un Contacto, que depende de un Proveedor.
    """
    
    # --- Arrange: create a supplier first ---
    # Driven through the client rather than the database, to exercise the whole flow
    auth_client.post('/suppliers/new', data={'name': 'Test Supplier for Contact'}, follow_redirects=True)
    
    # --- 1. CREAR CONTACTO ---
    # Assumes the contacts route reads 'supplier_id' from the form
    response = auth_client.post('/contacts/new', data={
        'name': 'Test Contact',
        'email': 'contact@supplier.com',
        'supplier_id': '1' # Enlazado al Proveedor ID 1 que acabamos de crear
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Contact created successfully!' in response.data
    
    # The contact is in the database
    with app.app_context():
        contact = db.session.get(Contact,1)
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

    # The contact is archived
    with app.app_context():
        contact = db.session.get(Contact,1)
        assert contact.is_archived