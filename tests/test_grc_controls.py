from src import db
from src.models import Documentation, Tag, User

# --- Test 8: Frameworks ---

#def test_framework_and_control_lifecycle(auth_client, app):
#    """
#    Test 8: Prueba el ciclo de vida de Frameworks y Controles
#    1. Admin crea un Framework.
#    2. Admin añade un Control a ese Framework.
#    3. Admin edita el Control.
#    """
#    # --- 1. Crear Framework ---
#    response = auth_client.post('/frameworks/new', data={
#        'name': 'Mi Framework Custom',
#        'description': 'Un framework de prueba'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Framework creado con exito' in response.data
#    assert b'Mi Framework Custom' in response.data
#
#    # Verifica en BD (ID 1)
#    with app.app_context():
#        fw = db.session.get(Framework, 1)
#        assert fw is not None
#        assert fw.name == 'Mi Framework Custom'
#        assert fw.is_custom == True # Debe ser custom
#
#    # --- 2. Añadir Control ---
#    response = auth_client.post('/frameworks/1/controls/new', data={
#        'control_id': 'C.1.1',
#        'name': 'Mi primer control',
#        'category': 'Categoría 1'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Control creado con exito' in response.data
#    assert b'Mi primer control' in response.data
#
#    # Verifica en BD (ID 1)
#    with app.app_context():
#        control = db.session.get(FrameworkControl, 1)
#        assert control is not None
#        assert control.control_id == 'C.1.1'
#        assert control.framework_id == 1
#
#    # --- 3. Editar Control ---
#    response = auth_client.post('/controls/1/edit', data={
#        'control_id': 'C.1.1-EDITED',
#        'name': 'Mi primer control (Editado)',
#        'category': 'Categoría 1'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Control actualizado con exito' in response.data
#    assert b'C.1.1-EDITED' in response.data

# --- Test 9: Documentation ---

def test_documentation_filtering(auth_client, app):
    """
    Test 9: Prueba que el filtro por Tags en la lista de Documentación funciona.
    """
    # --- Setup ---
    with app.app_context():
        # auth_client ya creó Admin (ID 1) y User (ID 2)
        admin = db.session.get(User, 1)
        
        # Crear Tags
        tag_audit = Tag(name='Auditoría')
        tag_general = Tag(name='General')
        db.session.add_all([tag_audit, tag_general])
        
        # Crear Documentación
        doc1 = Documentation(
            name='Doc de Auditoría',
            owner_id=admin.id,
            owner_type='User',
            tags=[tag_audit]
        )
        doc2 = Documentation(
            name='Doc General',
            owner_id=admin.id,
            owner_type='User',
            tags=[tag_general]
        )
        db.session.add_all([doc1, doc2])
        db.session.commit()
        
        assert tag_audit.id == 1
        assert tag_general.id == 2
        assert doc1.id == 1
        assert doc2.id == 2

    # --- Acción (Filtrar por tag 'Auditoría') ---
    # La ruta usa el nombre del tag, no el ID
    response = auth_client.get('/documentation/', query_string={'tags': 'Auditoría'})
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Doc de Auditoria' in response.data
    assert b'Doc General' not in response.data

    # --- Acción (Filtrar por tag 'General') ---
    response = auth_client.get('/documentation/', query_string={'tags': 'General'})
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Doc de Auditoria' not in response.data
    assert b'Doc General' in response.data