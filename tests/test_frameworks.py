import pytest
from src.models import db, Framework, FrameworkControl

def test_list_frameworks(auth_client, app):
    """
    Test 1: Comprueba que la página de lista de frameworks se carga.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()

    response = auth_client.get('/frameworks/')
    assert response.status_code == 200
    assert b"Marcos de Trabajo y Normativas" in response.data
    # Comprueba que los frameworks del seeder (de 'seed-db-prod') están
    assert b"ISO27001:2022" in response.data
    assert b"ITIL v4" in response.data

def test_framework_access_as_user(user_client, app):
    """
    Test 2: Comprueba que un usuario normal PUEDE ver la lista,
    pero NO PUEDE acceder a las páginas de creación/edición.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()

    # Los usuarios pueden ver la lista
    response = user_client.get('/frameworks/')
    assert response.status_code == 200
    assert b"Marcos de Trabajo y Normativas" in response.data

    # Los usuarios NO pueden crear
    response = user_client.get('/frameworks/new')
    assert response.status_code == 302 # Redirige (asumiendo @admin_required)
    
    # Los usuarios NO pueden editar (incluso si conocen la ID)
    with app.app_context():
        fw = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_id = fw.id

    response = user_client.get(f'/frameworks/{fw_id}/edit')
    assert response.status_code == 302 # Redirige

def test_create_framework(auth_client, app):
    """
    Test 3: Prueba la creación de un nuevo framework personalizado.
    (Corresponde a tu petición: "crear framework")
    """
    # Comprueba que no existe
    with app.app_context():
        assert Framework.query.filter_by(name='Mi Framework de Test').first() is None
    
    response = auth_client.post('/frameworks/new', data={
        'name': 'Mi Framework de Test',
        'description': 'Una descripción de prueba',
        'link': 'https://example.com',
        'is_active': 'on'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Debería redirigir a la página de EDICIÓN tras crear
    assert b"Editar Framework" in response.data
    assert b"Mi Framework de Test" in response.data
    
    # Comprueba que se ha guardado en la BBDD
    with app.app_context():
        fw = Framework.query.filter_by(name='Mi Framework de Test').first()
        assert fw is not None
        assert fw.description == 'Una descripción de prueba'
        assert fw.is_custom is True
        assert fw.is_active is True

def test_edit_framework(auth_client, app):
    """
    Test 4: Prueba la edición de un framework.
    Importante para probar que NO se pueden editar los 'built-in'.
    """
    # Seed frameworks first
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_iso_id = fw_iso.id
        assert fw_iso.is_active is True
    
    # --- Parte 1: Editar 'is_active' en un 'built-in' (DEBE funcionar) ---
    response = auth_client.post(f'/frameworks/{fw_iso_id}/edit', data={
        'name': 'Nombre Falso', # Este campo debe ser ignorado
        'description': 'Descripción Falsa', # Este también
        'link': 'https://fake.com', # Este también
        'is_active': '' # Desactivarlo (checkbox no marcado)
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b"Framework actualizado" in response.data
    # El nombre NO debe cambiar
    assert b"Nombre Falso" not in response.data
    assert b"ISO27001:2022" in response.data
    
    # Comprobar en BBDD
    with app.app_context():
        fw_iso_updated = Framework.query.get(fw_iso_id)
        assert fw_iso_updated.name == 'ISO27001:2022' # No cambió
        assert fw_iso_updated.is_active is False # SÍ cambió

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
    assert b"Framework actualizado" in response.data
    
    with app.app_context():
        fw_custom_updated = Framework.query.get(fw_custom_id)
        assert fw_custom_updated.name == 'Custom Modificado'
        assert fw_custom_updated.description == 'Nueva descripción'

def test_add_control_to_custom_framework(auth_client, app):
    """
    Test 5: Prueba añadir un control a un framework personalizado.
    (Corresponde a tu petición: "añadir control")
    """
    # Setup: Crear un framework custom
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
    
    # Comprueba la respuesta JSON
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert json_data['reload'] is True
    
    # Comprueba la BBDD
    with app.app_context():
        fw = Framework.query.get(fw_id)
        assert fw.framework_controls.count() == 1
        control = fw.framework_controls.first()
        assert control.name == 'Mi Nuevo Control'
        assert control.control_id == 'C.1.1'

def test_add_control_fail_on_builtin(auth_client, app):
    """
    Test 6: Prueba que NO se puede añadir un control a un framework 'built-in'.
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
    
    # Comprueba la respuesta JSON de error
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # Comprueba que no se añadió nada
    with app.app_context():
        fw_iso = Framework.query.get(fw_iso_id)
        assert fw_iso.framework_controls.count() == iso_control_count

def test_delete_control_from_custom_framework(auth_client, app):
    """
    Test 7: Prueba eliminar un control de un framework personalizado.
    (Corresponde a tu petición: "eliminar control")
    """
    # Setup: Crear framework y control
    with app.app_context():
        fw = Framework(name='Framework para Borrar Control', is_custom=True)
        control = FrameworkControl(control_id='DEL.1', name='Control a Borrar')
        fw.framework_controls.append(control)
        db.session.add(fw)
        db.session.commit()
        control_id = control.id
        assert FrameworkControl.query.get(control_id) is not None
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks/control/{control_id}/delete')
    
    # Comprueba la respuesta JSON
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert json_data['reload'] is True
    
    # Comprueba la BBDD
    with app.app_context():
        assert FrameworkControl.query.get(control_id) is None

def test_delete_control_fail_on_builtin(auth_client, app):
    """
    Test 8: Prueba que NO se puede eliminar un control de un 'built-in'.
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

    # Comprueba la respuesta JSON de error
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # Comprueba que el control sigue en la BBDD
    with app.app_context():
        assert FrameworkControl.query.get(control_id) is not None

def test_delete_custom_framework(auth_client, app):
    """
    Test 9: Prueba eliminar un framework personalizado.
    (Corresponde a tu petición: "eliminar frameworks")
    """
    # Setup: Crear framework y control
    with app.app_context():
        fw = Framework(name='Framework a Borrar', is_custom=True)
        fw.framework_controls.append(FrameworkControl(control_id='C.1', name='Test'))
        db.session.add(fw)
        db.session.commit()
        fw_id = fw.id
        assert Framework.query.get(fw_id) is not None
        assert FrameworkControl.query.count() > 0
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks//{fw_id}/delete')
    
    # Comprueba la respuesta JSON
    # NOTE: The original test expected 200, but if the route is not correct or handles it differently it might fail.
    # Assuming the route is /frameworks/<int:id>/delete
    response = auth_client.post(f'/frameworks/{fw_id}/delete')

    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data['success'] is True
    assert 'redirect_url' in json_data
    
    # Comprueba la BBDD
    with app.app_context():
        assert Framework.query.get(fw_id) is None
        # Comprueba que los controles se borraron en cascada
        assert FrameworkControl.query.count() == 0

def test_delete_framework_fail_on_builtin(auth_client, app):
    """
    Test 10: Prueba que NO se puede eliminar un framework 'built-in'.
    """
    with app.app_context():
        from src.seeder_prod import seed_production_frameworks
        seed_production_frameworks()
        fw_iso = Framework.query.filter_by(name='ISO27001:2022').first()
        fw_iso_id = fw_iso.id
        assert fw_iso is not None
    
    # Simula la llamada AJAX (fetch)
    response = auth_client.post(f'/frameworks/{fw_iso_id}/delete')
    
    # Comprueba la respuesta JSON de error
    assert response.status_code == 403 # Forbidden
    json_data = response.get_json()
    assert json_data['success'] is False
    assert "incorporados" in json_data['message']
    
    # Comprueba que sigue en la BBDD
    with app.app_context():
        assert Framework.query.get(fw_iso_id) is not None