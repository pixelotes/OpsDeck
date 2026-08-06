from src.models import db, Framework, FrameworkControl

def test_list_frameworks(auth_client, app):
    """
    Test 1: the frameworks list page loads.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()

    response = auth_client.get('/frameworks/')
    assert response.status_code == 200
    assert b"Frameworks & Standards" in response.data
    # The frameworks created by 'seed-db-prod' are present
    assert b"ISO27001:2022" in response.data
    assert b"ITIL v4" in response.data

def test_framework_access_as_user(user_client, app):
    """
    Test 2: a regular user can see the list but cannot reach the create and
    edit pages.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()

    # Los usuarios pueden ver la lista
    # Grant minimal permissions first
    with app.app_context():
        from src.seeder_prod import seed_modules
        from src.models import Permission, User, Module, AccessLevel
        from src.services.permissions_cache import permissions_cache
        seed_modules()
        
        user = User.query.filter_by(email='user@test.com').first()
        module = Module.query.filter_by(slug='compliance').first()
        
        # Grant READ_ONLY
        perm = Permission(user_id=user.id, module_id=module.id, access_level=AccessLevel.READ_ONLY)
        db.session.add(perm)
        db.session.commit()
        permissions_cache.invalidate()

    response = user_client.get('/frameworks/')
    assert response.status_code == 200
    assert b"Frameworks & Standards" in response.data

    # Los usuarios NO pueden crear
    response = user_client.get('/frameworks/new')
    # Should be 403 Forbidden or Redirect depending on implementation. 
    # Logic: @requires_permission checks READ access. create() checks has_write_permission.
    # If using @requires_permission('compliance'), it allows entry if READ.
    # Then inside create(), it checks has_write_permission.
    # Let's verify the route code for /new
    
    # Actually wait, route /new has @requires_permission('compliance'). 
    # And inside: if not has_write_permission... flash... redirect.
    # So it should be 302 redirecting to list.
    assert response.status_code == 302 
    
    # Los usuarios NO pueden editar (incluso si conocen la ID)
    with app.app_context():
        fw = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_id = fw.id

    response = user_client.get(f'/frameworks/{fw_id}/edit')
    assert response.status_code == 302 # Redirige

def test_create_framework(auth_client, app):
    """
    Test 3: creating a custom framework.
    """
    # It does not exist
    with app.app_context():
        assert Framework.query.filter_by(name='Mi Framework de Test').first() is None
    
    response = auth_client.post('/frameworks/new', data={
        'name': 'Mi Framework de Test',
        'description': 'Una descripción de prueba',
        'link': 'https://example.com',
        'is_active': 'on'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # It should redirect to the edit page after creating
    assert b"Editar Framework" in response.data
    assert b"Mi Framework de Test" in response.data
    
    # It was saved to the database
    with app.app_context():
        fw = Framework.query.filter_by(name='Mi Framework de Test').first()
        assert fw is not None
        assert fw.description == 'Una descripción de prueba'
        assert fw.is_custom is True
        assert fw.is_active is True

def test_edit_framework(auth_client, app):
    """
    Test 4: editing a framework.
    Importante para probar que NO se pueden editar los 'built-in'.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_iso_id = fw_iso.id
        # Production frameworks are seeded as inactive by default
        assert fw_iso.is_active is False
    
    # --- Parte 1: Editar 'is_active' en un 'built-in' (DEBE funcionar) ---
    # Activate it first
    response = auth_client.post(f'/frameworks/{fw_iso_id}/edit', data={
        'name': 'Nombre Falso', # Este campo debe ser ignorado
        'description': 'Descripción Falsa',  # ignored too
        'link': 'https://fake.com',  # ignored too
        'is_active': 'on' # Activarlo (checkbox marcado)
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"Framework updated." in response.data
    # El nombre NO debe cambiar
    assert b"Nombre Falso" not in response.data
    assert b"ISO27001:2022" in response.data
    
    # It was activated in the database
    with app.app_context():
        fw_iso_updated = db.session.get(Framework,fw_iso_id)
        assert fw_iso_updated.name == 'ISO27001:2022'  # unchanged
        assert fw_iso_updated.is_active is True  # this one did change

    # --- Parte 2: Editar 'name' en un 'custom' (DEBE funcionar) ---
    with app.app_context():
        fw_custom = Framework(name='Custom Original', is_custom=True, is_active=True)
        db.session.add(fw_custom)
        db.session.commit()
        fw_custom_id = fw_custom.id
    
    response = auth_client.post(f'/frameworks/{fw_custom_id}/edit', data={
        'name': 'Custom Modificado',
        'description': 'Nueva descripción',
        'link': 'https://new-link.com',
        'is_active': 'on'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"Framework updated." in response.data
    
    with app.app_context():
        fw_custom_updated = db.session.get(Framework,fw_custom_id)
        assert fw_custom_updated.name == 'Custom Modificado'
        assert fw_custom_updated.description == 'Nueva descripción'

def test_add_control_to_custom_framework(auth_client, app):
    """
    Test 5: adding a control to a custom framework.
    """
    # Arrange: create a custom framework
    with app.app_context():
        fw = Framework(name='Framework para Controles', is_custom=True)
        db.session.add(fw)
        db.session.commit()
        fw_id = fw.id
        assert fw.framework_controls.count() == 0
    
    # Simula la llamada AJAX (fetch) desde el modal
    response = auth_client.post('/frameworks/control/add', data={
        'framework_id': fw_id,
        'control_id_text': 'C.1.1',
        'name': 'Mi Nuevo Control',
        'description': 'Descripción del control'
    })
    
    # Check the JSON response
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert json_data['reload'] is True
    
    # Check the database
    with app.app_context():
        fw = db.session.get(Framework,fw_id)
        assert fw.framework_controls.count() == 1
        control = fw.framework_controls.first()
        assert control.name == 'Mi Nuevo Control'
        assert control.control_id == 'C.1.1'

def test_add_control_fail_on_builtin(auth_client, app):
    """
    Test 6: a control cannot be added to a built-in framework.
    """
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_iso_id = fw_iso.id
        iso_control_count = fw_iso.framework_controls.count()
    
    response = auth_client.post('/frameworks/control/add', data={
        'framework_id': fw_iso_id,
        'control_id_text': 'HACK.1',
        'name': 'Control Falso',
        'description': 'Intentando hackear'
    })
    
    # Check the JSON error response
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # Nothing was added
    with app.app_context():
        fw_iso = db.session.get(Framework,fw_iso_id)
        assert fw_iso.framework_controls.count() == iso_control_count

def test_delete_control_from_custom_framework(auth_client, app):
    """
    Test 7: Prueba eliminar un control de un framework personalizado.
    """
    # Arrange: create a framework and a control
    with app.app_context():
        fw = Framework(name='Framework para Borrar Control', is_custom=True)
        control = FrameworkControl(control_id='DEL.1', name='Control a Borrar')
        fw.framework_controls.append(control)
        db.session.add(fw)
        db.session.commit()
        control_id = control.id
        assert db.session.get(FrameworkControl,control_id) is not None
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks/control/{control_id}/delete')
    
    # Check the JSON response
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert json_data['reload'] is True
    
    # Check the database
    with app.app_context():
        assert db.session.get(FrameworkControl,control_id) is None

def test_delete_control_fail_on_builtin(auth_client, app):
    """
    Test 8: a control cannot be removed from a built-in framework.
    """
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        control_to_delete = fw_iso.framework_controls.first()
        assert control_to_delete is not None
        control_id = control_to_delete.id
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks/control/{control_id}/delete')

    # Check the JSON error response
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # The control is still in the database
    with app.app_context():
        assert db.session.get(FrameworkControl,control_id) is not None

def test_delete_custom_framework(auth_client, app):
    """
    Test 9: Prueba eliminar un framework personalizado.
    """
    # Arrange: create a framework and a control
    with app.app_context():
        fw = Framework(name='Framework a Borrar', is_custom=True)
        fw.framework_controls.append(FrameworkControl(control_id='C.1', name='Test'))
        db.session.add(fw)
        db.session.commit()
        fw_id = fw.id
        assert db.session.get(Framework,fw_id) is not None
        assert FrameworkControl.query.count() > 0
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks//{fw_id}/delete')
    
    # Check the JSON response
    # NOTE: The original test expected 200, but if the route is not correct or handles it differently it might fail.
    # Assuming the route is /frameworks/<int:id>/delete
    response = auth_client.post(f'/frameworks/{fw_id}/delete')

    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert 'redirect_url' in json_data
    
    # Check the database
    with app.app_context():
        assert db.session.get(Framework,fw_id) is None
        # The controls were cascade-deleted
        assert FrameworkControl.query.count() == 0

def test_delete_framework_fail_on_builtin(auth_client, app):
    """
    Test 10: a built-in framework cannot be deleted.
    """
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_iso_id = fw_iso.id
        assert fw_iso is not None
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks/{fw_iso_id}/delete')
    
    # Check the JSON error response
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # It is still in the database
    with app.app_context():
        assert db.session.get(Framework,fw_iso_id) is not None