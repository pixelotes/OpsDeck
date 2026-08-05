import traceback

def test_purchase_cost_calculation(auth_client, app):
    """
    Test 12: Prueba que la propiedad @total_cost de una Compra (Purchase)
    se calcula correctamente sumando sus activos y periféricos.
    """
    # --- 1. Setup ---
    # (auth_client ya ha creado un Admin (ID 1) y un User (ID 2))
    
    # Crear una Compra (ID 1)
    auth_client.post('/purchases/new', data={
        'description': 'Compra de Portátiles Q4',
        'purchase_date': '2025-11-14'
    }, follow_redirects=True)
    
    # Crear un Activo (cost=1000) y un Periférico (cost=150)
    # y enlazarlos a la Compra (ID 1)
    auth_client.post('/assets/new', data={
        'name': 'Laptop A',
        'status': 'Stored',
        'cost': 1000,
        'purchase_id': 1
    }, follow_redirects=True)
    
    auth_client.post('/peripherals/new', data={
        'name': 'Monitor A',
        'status': 'Stored',
        'cost': 150,
        'purchase_id': 1
    }, follow_redirects=True)

    # --- 2. Acción ---
    # Acceder a la página de detalles de la Compra
    try:
        response = auth_client.get('/purchases/1')
        
        # --- 3. Verify ---
        assert response.status_code == 200
        # Asumimos que la plantilla formatea el coste total como 1150.00
        assert b'1150.00' in response.data
    except Exception:
        traceback.print_exc()
        raise
