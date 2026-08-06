from src import db
from src.models import Documentation, Tag, User

# --- Test 8: Frameworks ---

#def test_framework_and_control_lifecycle(auth_client, app):
#    """
#    Test 8: Prueba el ciclo de vida de Frameworks y Controles
#    1. Admin crea un Framework.
#    2. An admin adds a control to that framework.
#    3. Admin edita el Control.
#    """
#    # --- 1. Create a framework ---
#    response = auth_client.post('/frameworks/new', data={
#        'name': 'Mi Framework Custom',
#        'description': 'Un framework de prueba'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Framework creado con exito' in response.data
#    assert b'Mi Framework Custom' in response.data
#
#    # Check the database (id 1)
#    with app.app_context():
#        fw = db.session.get(Framework, 1)
#        assert fw is not None
#        assert fw.name == 'Mi Framework Custom'
#        assert fw.is_custom == True # Debe ser custom
#
#    # --- 2. Add a control ---
#    response = auth_client.post('/frameworks/1/controls/new', data={
#        'control_id': 'C.1.1',
#        'name': 'Mi primer control',
#        'category': 'Category 1'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Control creado con exito' in response.data
#    assert b'Mi primer control' in response.data
#
#    # Check the database (id 1)
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
#        'category': 'Category 1'
#    }, follow_redirects=True)
#    
#    assert response.status_code == 200
#    assert b'Control actualizado con exito' in response.data
#    assert b'C.1.1-EDITED' in response.data

# --- Test 9: Documentation ---

def test_documentation_filtering(auth_client, app):
    """
    Test 9: the tag filter on the documentation list works.
    """
    # --- Setup ---
    with app.app_context():
        # auth_client already created an admin (id 1) and a user (id 2)
        admin = db.session.get(User, 1)
        
        # Create tags
        tag_audit = Tag(name='Auditoria')  # <-- CAMBIO: Sin acento
        tag_general = Tag(name='General')
        db.session.add_all([tag_audit, tag_general])
        
        # Create documentation
        doc1 = Documentation(
            name='Doc de Auditoria',  # <-- CAMBIO: Sin acento
            description='Una descripción de prueba.',
            owner_id=admin.id,
            owner_type='User',
            tags=[tag_audit]
        )
        doc2 = Documentation(
            name='Doc General',
            description='Otra descripción de prueba.',
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

    # --- Act: filter by the 'Auditoria' tag ---
    # The route takes the tag name, not its id
    response = auth_client.get('/documentation/', query_string={'tags': 'Auditoria'}) # <-- CAMBIO: Sin acento
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Doc de Auditoria' in response.data
    assert b'Doc General' not in response.data

    # --- Act: filter by the 'General' tag ---
    response = auth_client.get('/documentation/', query_string={'tags': 'General'})
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Doc de Auditoria' not in response.data
    assert b'Doc General' in response.data
