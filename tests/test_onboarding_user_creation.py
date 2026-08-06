from src.utils.timezone_helper import now
from src.models import User
from src.models.onboarding import OnboardingProcess, ProcessItem

def test_onboarding_creates_checklist_item(auth_client, app):
    """
    Test that starting a new onboarding process automatically adds the 'CreateUser' item first.
    """
    with app.app_context():
        # Setup data
        manager = User(name="Mgr", email="m@t.com")
        db = app.extensions['sqlalchemy']
        db.session.add(manager)
        db.session.commit()
        manager_id = manager.id

    # Start Onboarding
    response = auth_client.post('/onboarding/new', data={
        'new_hire_name': 'Test Newhire',
        'start_date': '2025-01-01',
        'manager_id': manager_id
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    with app.app_context():
        process = OnboardingProcess.query.filter_by(new_hire_name='Test Newhire').first()
        assert process is not None
        
        # Check for CreateUser item
        create_user_item = ProcessItem.query.filter_by(
            onboarding_process_id=process.id, 
            item_type='CreateUser'
        ).first()
        
        assert create_user_item is not None
        assert "Create user account" in create_user_item.description
        assert not create_user_item.is_completed

def test_create_user_action(auth_client, app):
    """
    Test the 'Create User' button action.
    """
    # 1. Setup Process with CreateUser item
    with app.app_context():
        db = app.extensions['sqlalchemy']
        process = OnboardingProcess(new_hire_name="Jane Doe", start_date=now())
        db.session.add(process)
        db.session.commit()
        
        item = ProcessItem(
            onboarding_process_id=process.id,
            description="Create user",
            item_type='CreateUser'
        )
        db.session.add(item)
        db.session.commit()
        
        process_id = process.id
        item_id = item.id

    # 2. Call the Create User route
    url = f'/onboarding/process/{process_id}/create_user/{item_id}'
    response = auth_client.post(url, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'User created!' in response.data
    assert b'jane.doe@example.com' in response.data
    
    with app.app_context():
        # Verify User Created
        user = User.query.filter_by(email='jane.doe@example.com').first()
        assert user is not None
        assert user.name == "Jane Doe"
        
        # Verify Process Linked
        process = db.session.get(OnboardingProcess, process_id)
        assert process.user_id == user.id

        # Verify Item Completed
        item = db.session.get(ProcessItem, item_id)
        assert item.is_completed
