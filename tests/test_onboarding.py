from src.utils.timezone_helper import now
from src.models.onboarding import OnboardingProcess, OffboardingProcess, OnboardingPack, ProcessItem, ProcessTemplate
from src.models import User, Software

def test_onboarding_packs_crud(auth_client, app):
    """
    Test creation and item management of Onboarding Packs.
    """
    # 1. Create Pack
    response = auth_client.post('/onboarding/packs/new', data={
        'name': 'Developer Pack',
        'description': 'Tools for devs'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Developer Pack' in response.data

    with app.app_context():
        pack = OnboardingPack.query.filter_by(name='Developer Pack').first()
        assert pack is not None
        pack_id = pack.id
        
        # Create a Software to link
        sw = Software(name="VS Code", description="IDE")
        db = app.extensions['sqlalchemy']
        db.session.add(sw)
        db.session.commit()
        software_id = sw.id

    # 2. Add Item to Pack
    response = auth_client.post(f'/onboarding/packs/{pack_id}', data={
        'item_type': 'Software',
        'software_id': software_id,
        'description': '' # Should auto-fill
    }, follow_redirects=True)
    assert response.status_code == 200
    
    with app.app_context():
        pack = db.session.get(OnboardingPack, pack_id)
        assert len(pack.items) == 1
        assert pack.items[0].item_type == 'Software'
        assert "Provisionar acceso a: VS Code" in pack.items[0].description

def test_onboarding_process_flow(auth_client, app):
    """
    Test Starting Onboarding -> Checklist Generation -> Completion
    """
    # Setup Data
    with app.app_context():
        db = app.extensions['sqlalchemy']
        
        # User for Manager and Buddy
        manager = User(name="Manager User", email="mgr@test.com")
        buddy = User(name="Buddy User", email="buddy@test.com")
        db.session.add_all([manager, buddy])
        
        # Pack
        pack = OnboardingPack(name="Sales Pack")
        db.session.add(pack)
        db.session.flush()
        
        # Template Task
        t = ProcessTemplate(name="Sign NDA", process_type="onboarding")
        db.session.add(t)
        db.session.commit()
        
        pack_id = pack.id
        manager_id = manager.id
        buddy_id = buddy.id

    # 1. Start Onboarding
    start_date = now().strftime('%Y-%m-%d')
    response = auth_client.post('/onboarding/new', data={
        'new_hire_name': 'New Guy',
        'start_date': start_date,
        'pack_id': pack_id,
        'manager_id': manager_id,
        'buddy_id': buddy_id
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Onboarding started for New Guy' in response.data

    # 2. Verify Checklist Items
    with app.app_context():
        process = OnboardingProcess.query.filter_by(new_hire_name='New Guy').first()
        assert process is not None
        item_descs = [i.description for i in process.items]
        
        # Check Global Task
        assert "Sign NDA" in item_descs
        # Check Social Tasks (Manager & Buddy)
        assert any("Manager User" in d for d in item_descs)
        assert any("Buddy User" in d for d in item_descs)
        
        process_id = process.id
        item_id = process.items[0].id

    # 3. Toggle Item
    response = auth_client.post(f'/onboarding/item/{item_id}/toggle', follow_redirects=True)
    assert response.status_code == 200
    
    with app.app_context():
        item = db.session.get(ProcessItem, item_id)
        assert item.is_completed

    # 4. Complete Process
    response = auth_client.post(f'/onboarding/process/onboarding/{process_id}/complete', follow_redirects=True)
    assert response.status_code == 200
    assert b'completed' in response.data
    
    with app.app_context():
        process = db.session.get(OnboardingProcess, process_id)
        assert process.status == 'Completed'

def test_offboarding_process_flow(auth_client, app):
    """
    Test Starting Offboarding -> Intelligent Checklist -> Completion & Archiving
    """
    # Setup Data: User with assigned Software
    with app.app_context():
        db = app.extensions['sqlalchemy']
        user = User(name="Leaviing User", email="bye@test.com")
        db.session.add(user)
        db.session.flush()
        
        sw = Software(name="Slack")
        db.session.add(sw)
        db.session.flush()
        
        # Assign software (creates license/assignment implication generally, 
        # but the offboarding route checks License model directly)
        from src.models import License
        lic = License(name="Slack Pro", software_id=sw.id, user_id=user.id)
        db.session.add(lic)
        
        # Global Task
        t = ProcessTemplate(name="Exit Interview", process_type="offboarding")
        db.session.add(t)
        
        db.session.commit()
        user_id = user.id

    # 1. Start Offboarding
    dept_date = now().strftime('%Y-%m-%d')
    response = auth_client.post('/onboarding/offboarding/new', data={
        'user_id': user_id,
        'departure_date': dept_date
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Offboarding started' in response.data

    # 2. Verify Checklist
    with app.app_context():
        process = OffboardingProcess.query.filter_by(user_id=user_id).first()
        item_descs = [i.description for i in process.items]
        
        # Check Intelligent Item (License Revocation)
        assert any("Revoke License: Slack Pro" in d for d in item_descs)
        # Check Global Task
        assert "Exit Interview" in item_descs
        
        process_id = process.id

    # 3. Complete Process
    response = auth_client.post(f'/onboarding/process/offboarding/{process_id}/complete', follow_redirects=True)
    assert response.status_code == 200
    
    with app.app_context():
        process = db.session.get(OffboardingProcess, process_id)
        assert process.status == 'Completed'

        # Verify User Archived
        user = db.session.get(User, user_id)
        assert user.is_archived
