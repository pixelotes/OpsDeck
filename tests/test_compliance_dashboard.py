import pytest
from src.models import Framework, FrameworkControl, User
from src import db

@pytest.fixture(scope='function')
def auth_client(client, app):
    with app.app_context():
        user = User(name='Test User', email='test@example.com', role='admin')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
    
    client.post('/login', data={'email': 'test@example.com', 'password': 'password'})
    yield client

def test_dashboard_rendering(auth_client, app):
    with app.app_context():
        # Create a framework and control
        fw = Framework(name='Test Framework', description='Test Desc', is_active=True)
        db.session.add(fw)
        db.session.commit()
        
        ctrl = FrameworkControl(framework_id=fw.id, control_id='T.1', name='Test Control')
        db.session.add(ctrl)
        db.session.commit()

    response = auth_client.get('/compliance/dashboard')
    assert response.status_code == 200
    content = response.data.decode('utf-8')
    assert 'Test Framework' in content
    assert 'Test Control' in content
    assert 'Export PDF' in content

def test_pdf_export(auth_client, app):
    with app.app_context():
        # Create a framework
        fw = Framework(name='PDF Framework', is_active=True)
        db.session.add(fw)
        db.session.commit()

    response = auth_client.get('/compliance/dashboard/pdf')
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/pdf'
    assert response.headers['Content-Disposition'] == 'attachment; filename=compliance_report.pdf'
    # We can't easily check PDF content, but status and headers are good indicators
