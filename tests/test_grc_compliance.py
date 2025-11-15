import io
import os
from src import db
from src.models import (
    User, Policy, PolicyVersion, PolicyAcknowledgement, 
    Course, CourseAssignment, CourseCompletion, Attachment
)
from datetime import datetime, timedelta

# --- Tests 5, 6: Policies ---

def test_policy_acknowledgement_flow(client, app):
    """
    Test 5: Prueba el flujo completo de GRC para un usuario:
    1. (Setup) Admin crea una política y se la asigna a un usuario.
    2. (Login) El usuario inicia sesión.
    3. (Acción) El usuario acepta la política.
    4. (Verify) Se comprueba que el registro de aceptación existe.
    """
    # --- 1. Setup (como Admin) ---
    with app.app_context():
        # Limpiar BD
        db.drop_all()
        db.create_all()
        
        # Crear Admin (ID 1) y Usuario (ID 2)
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        test_user = User(name='Test User', email='user@test.com', role='user')
        test_user.set_password('password')
        
        # Crear Política y Versión (ID 1)
        policy = Policy(title='Test Policy')
        policy_version = PolicyVersion(
            policy=policy,
            version_number='1.0',
            status='Active',
            content='Debes aceptar esto.',
            effective_date=datetime.utcnow().date()
        )
        # Asignar la política al usuario
        policy_version.users_to_acknowledge.append(test_user)
        
        db.session.add_all([admin, test_user, policy, policy_version])
        db.session.commit()
        
        assert policy_version.id == 1
        assert test_user.id == 2

    # --- 2. Login (como 'Test User') ---
    response = client.post('/login', data={
        'email': 'user@test.com',
        'password': 'password'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Logged in successfully' in response.data

    # --- 3. Acción (Usuario acepta la política) ---
    # El usuario visita la página de la política
    response = client.get('/policies/version/1')
    assert b'Debes aceptar esto.' in response.data
    
    # El usuario envía el POST para aceptar
    response = client.post('/policies/version/1/acknowledge', follow_redirects=True)
    assert response.status_code == 200
    assert b'You have successfully acknowledged' in response.data

    # --- 4. Verify (Comprobar en BD) ---
    with app.app_context():
        ack = db.session.query(PolicyAcknowledgement).filter_by(
            policy_version_id=1,
            user_id=2
        ).first()
        assert ack is not None
        assert ack.user_id == 2

def test_policy_report_shows_unacknowledged(auth_client, app):
    """
    Test 6: Prueba que el informe de cumplimiento muestra correctamente
    a los usuarios que no han aceptado una política.
    """
    # --- Setup ---
    # auth_client ya ha creado un Admin (ID 1) y un User (ID 2)
    with app.app_context():
        test_user = User(name='Test User', email='user@test.com', role='user')
        db.session.add(test_user)
        db.session.commit()
        test_user = db.session.get(User, 2)
        
        # Crear Política y Versión (ID 1)
        policy = Policy(title='Unacknowledged Policy')
        policy_version = PolicyVersion(
            policy=policy,
            version_number='1.0',
            status='Active',
            content='...',
            effective_date=datetime.utcnow().date()
        )
        # Asignar a 'Test User'
        policy_version.users_to_acknowledge.append(test_user)
        db.session.add_all([policy, policy_version])
        db.session.commit()

    # --- Acción (Admin comprueba el informe) ---
    response = auth_client.get('/compliance/policy-report')
    
    # --- Verify ---
    assert response.status_code == 200
    assert b'Unacknowledged Policy' in response.data
    # 'Test User' (ID 2) no ha aceptado, así que debe aparecer
    assert b'Test User' in response.data 

# --- Test 7: Training ---

def test_user_completes_training(client, app):
    """
    Test 7: Prueba el flujo completo de un usuario completando formación.
    1. (Setup) Admin crea Curso y Asignación para un Usuario.
    2. (Login) El usuario inicia sesión.
    3. (Acción) El usuario completa el curso.
    4. (Verify) Se comprueba que el registro CourseCompletion existe.
    """
    # Asegurar que el UPLOAD_FOLDER existe
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # --- 1. Setup (como Admin) ---
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
            due_date=(datetime.utcnow() + timedelta(days=30)).date()
        )
        
        db.session.add_all([admin, test_user, course, assignment])
        db.session.commit()
        
        assert assignment.id == 1
        assert test_user.id == 2

    # --- 2. Login (como 'Test User') ---
    client.post('/login', data={'email': 'user@test.com', 'password': 'password'}, follow_redirects=True)

    # --- 3. Acción (Usuario completa el curso) ---
    # El usuario visita su página de formación
    response = client.get('/training/')
    assert b'Test Course' in response.data
    
    # El usuario envía el POST para completar (con un adjunto simulado)
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
    # Verificar mensaje de éxito (puede variar)
    assert (b'Successfully marked' in response.data or 
            b'marked as complete' in response.data or
            b'Course completed' in response.data)

    # --- 4. Verify (Comprobar en BD) ---
    with app.app_context():
        completion = db.session.query(CourseCompletion).filter_by(assignment_id=1).first()
        assert completion is not None
        assert completion.notes == 'Curso completado.'
        
        # Comprobar que el adjunto polimórfico se creó
        attachment = db.session.query(Attachment).filter_by(
            linkable_type='CourseCompletion',
            linkable_id=completion.id
        ).first()
        assert attachment is not None
        assert attachment.filename == 'certificate.pdf'
