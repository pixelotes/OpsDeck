import io
import os
from src import db
from src.models import (
    User, Policy, PolicyVersion, PolicyAcknowledgement, 
    Course, CourseAssignment, CourseCompletion, Attachment
)
from datetime import timedelta
from src.utils.timezone_helper import now

# --- Tests 5, 6: Policies ---

def test_policy_acknowledgement_flow(client, app):
    """
    Test 5: the whole GRC flow for a user.
    1. An admin creates a policy and assigns it to a user.
    2. The user logs in.
    3. The user acknowledges the policy.
    4. The acknowledgement record exists.
    """
    # --- 1. Arrange, as an admin ---
    with app.app_context():
        # Reset the database
        db.drop_all()
        db.create_all()
        
        # Create an admin (id 1) and a user (id 2)
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        test_user = User(name='Test User', email='user@test.com', role='user')
        test_user.set_password('password')
        
        # Create a policy and a version (id 1)
        policy = Policy(title='Test Policy')
        policy_version = PolicyVersion(
            policy=policy,
            version_number='1.0',
            status='Active',
            content='Debes aceptar esto.',
            effective_date=now().date()
        )
        # Assign the policy to the user
        policy_version.users_to_acknowledge.append(test_user)
        
        db.session.add_all([admin, test_user, policy, policy_version])
        db.session.commit()
        
        assert policy_version.id == 1
        assert test_user.id == 2

        # --- Grant Permissions ---
        from src.seeder_prod import seed_modules
        from src.models import Permission, Module, AccessLevel
        from src.services.permissions_cache import permissions_cache
        seed_modules()
        
        # Grant knowledge_policy permission
        module_kp = Module.query.filter_by(slug='knowledge_policy').first()
        perm_kp = Permission(user_id=test_user.id, module_id=module_kp.id, access_level=AccessLevel.READ_ONLY)
        db.session.add(perm_kp)

        # Grant health_dashboard permission (required for dashboard redirect)
        module_hd = Module.query.filter_by(slug='health_dashboard').first()
        perm_hd = Permission(user_id=test_user.id, module_id=module_hd.id, access_level=AccessLevel.READ_ONLY)
        db.session.add(perm_hd)

        db.session.commit()
        permissions_cache.invalidate()

    # --- 2. Login (como 'Test User') ---
    response = client.post('/login', data={
        'email': 'user@test.com',
        'password': 'password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Logged in successfully' in response.data

    # --- 3. Act: the user acknowledges the policy ---
    # The user opens the policy page
    response = client.get('/policies/version/1')
    assert b'Debes aceptar esto.' in response.data
    
    # The user posts the acknowledgement
    # The user posts the acknowledgement
    
    response = client.post('/policies/version/1/acknowledge', follow_redirects=True)
    assert response.status_code == 200
    assert b'You have successfully acknowledged' in response.data

    # --- 4. Assert against the database ---
    with app.app_context():
        ack = db.session.query(PolicyAcknowledgement).filter_by(
            policy_version_id=1,
            user_id=2
        ).first()
        assert ack is not None
        assert ack.user_id == 2

def test_policy_report_shows_unacknowledged(auth_client, app):
    """
    Test 6: the compliance report lists the users who have not acknowledged
    a policy.
    """
    # --- Setup ---
    # auth_client has already created an admin (id 1) and a user (id 2)
    with app.app_context():
        test_user = User(name='Test User', email='user@test.com', role='user')
        db.session.add(test_user)
        db.session.commit()
        test_user = db.session.get(User, 2)
        
        # Create a policy and a version (id 1)
        policy = Policy(title='Unacknowledged Policy')
        policy_version = PolicyVersion(
            policy=policy,
            version_number='1.0',
            status='Active',
            content='...',
            effective_date=now().date()
        )
        # Assign it to 'Test User'
        policy_version.users_to_acknowledge.append(test_user)
        db.session.add_all([policy, policy_version])
        db.session.commit()

    # --- Act: an admin checks the report ---
    response = auth_client.get('/compliance/policy-report')
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Unacknowledged Policy' in response.data
    # 'Test User' (id 2) has not acknowledged, so they must be listed
    assert b'Test User' in response.data 

# --- Test 7: Training ---

def test_user_completes_training(client, app):
    """
    Test 7: the whole flow of a user completing training.
    1. An admin creates a course and assigns it to a user.
    2. The user logs in.
    3. The user completes the course.
    4. The CourseCompletion record exists.
    """
    # Make sure UPLOAD_FOLDER exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # --- 1. Arrange, as an admin ---
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        test_user = User(name='Test User', email='user@test.com', role='user')
        test_user.set_password('password')
        
        course = Course(title='Test Course', completion_days=30)
        
        assignment = CourseAssignment(
            course=course,
            user=test_user,
            due_date=(now() + timedelta(days=30)).date()
        )
        
        db.session.add_all([admin, test_user, course, assignment])
        db.session.commit()
        
        assert assignment.id == 1
        assert test_user.id == 2

    # --- 2. Login (como 'Test User') ---
    client.post('/login', data={'email': 'user@test.com', 'password': 'password'}, follow_redirects=True)

    # --- 3. Act: the user completes the course ---
    # The user opens their training page
    response = client.get('/training/')
    assert b'Test Course' in response.data
    
    # The user posts the completion, with a stub attachment
    data = {
        'notes': 'Curso completado.',
        'certificate': (io.BytesIO(b"dummy cert data"), 'certificate.pdf')
    }
    response = client.post(
        '/training/completion/1/complete', # 1 es el assignment.id
        data=data, 
        follow_redirects=True, 
        content_type='multipart/form-data'
    )
    
    assert response.status_code == 200
    # Check for a success message; the wording may vary
    assert (b'Successfully marked' in response.data or 
            b'marked as complete' in response.data or
            b'Course completed' in response.data)

    # --- 4. Assert against the database ---
    with app.app_context():
        completion = db.session.query(CourseCompletion).filter_by(assignment_id=1).first()
        assert completion is not None
        assert completion.notes == 'Curso completado.'
        
        # The polymorphic attachment was created
        attachment = db.session.query(Attachment).filter_by(
            linkable_type='CourseCompletion',
            linkable_id=completion.id
        ).first()
        assert attachment is not None
        assert attachment.filename == 'certificate.pdf'
