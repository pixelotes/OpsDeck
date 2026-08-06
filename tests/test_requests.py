"""
Tests for src/routes/requests.py and the Request model.
Covers: model creation, CRUD routes, and the service-desk lifecycle
(Pending -> Triage -> In Progress -> Completed -> Closed, plus Cancelled).
"""
import io
import pytest
from datetime import timedelta
from src import db
from src.utils.timezone_helper import now
from src.models import Request, User, BusinessService, Tag
from src.models import Module, Permission, AccessLevel


@pytest.fixture
def request_data(app, init_database):
    """Creates sample data for request testing."""
    with app.app_context():
        requester = User(name="Reqie Requester", email="requester@test.com", role="user")
        requester.set_password("password")
        assignee = User(name="Andy Assignee", email="assignee@test.com", role="user")
        assignee.set_password("password")
        db.session.add_all([requester, assignee])
        db.session.commit()

        service = BusinessService(name="Email Platform", status="Active")
        db.session.add(service)

        tag = Tag(name="urgent")
        db.session.add(tag)
        db.session.commit()

        req = Request(
            title="Need a new laptop",
            request_type="Hardware",
            priority="High",
            status="Pending",
            description="My laptop is broken.",
            requester_id=requester.id,
        )
        db.session.add(req)
        db.session.commit()

        yield {
            'request_id': req.id,
            'requester_id': requester.id,
            'assignee_id': assignee.id,
            'service_id': service.id,
            'tag_id': tag.id,
        }


# --- Model ---

def test_request_creation(init_database):
    """Request model can be created with relationships."""
    db = init_database
    user = User(name="Owner", email="owner@test.com", role="admin")
    db.session.add(user)
    db.session.commit()

    req = Request(
        title="Access to CRM",
        request_type="Access",
        priority="Medium",
        status="Pending",
        requester_id=user.id,
    )
    db.session.add(req)
    db.session.commit()

    assert req.id is not None
    assert req.requester == user
    assert req.status == "Pending"
    assert req.request_type == "Access"


# --- List ---

def test_list_requests_loads(auth_client, request_data):
    response = auth_client.get('/requests/')
    assert response.status_code == 200


def test_list_requests_shows_existing(auth_client, request_data):
    response = auth_client.get('/requests/')
    assert b'Need a new laptop' in response.data


def test_list_requests_status_filter(auth_client, request_data):
    response = auth_client.get('/requests/?status=Pending')
    assert response.status_code == 200
    assert b'Need a new laptop' in response.data
    # Filtering by a status the request is not in should hide it
    response = auth_client.get('/requests/?status=Closed')
    assert b'Need a new laptop' not in response.data


# --- Detail ---

def test_detail_loads(auth_client, request_data):
    response = auth_client.get(f'/requests/{request_data["request_id"]}')
    assert response.status_code == 200
    assert b'Need a new laptop' in response.data


def test_detail_not_found(auth_client, request_data):
    response = auth_client.get('/requests/99999')
    assert response.status_code == 404


# --- New ---

def test_new_form_loads(auth_client, request_data):
    response = auth_client.get('/requests/new')
    assert response.status_code == 200


def test_new_request_post(auth_client, request_data, app):
    data = {
        'title': 'VPN access request',
        'request_type': 'Access',
        'priority': 'Medium',
        'description': 'Need VPN to work remotely.',
        'justification': 'Remote onboarding.',
        'target_type': 'service',
        'service_id': request_data['service_id'],
        'assignee_id': request_data['assignee_id'],
        'tag_ids': [request_data['tag_id']],
    }
    response = auth_client.post('/requests/new', data=data, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        req = Request.query.filter_by(title='VPN access request').first()
        assert req is not None
        assert req.status == 'Pending'
        assert req.service_id == request_data['service_id']
        assert req.assignee_id == request_data['assignee_id']
        assert len(req.tags) == 1


# --- Edit ---

def test_edit_request_post(auth_client, request_data, app):
    data = {
        'title': 'Need a new laptop (updated)',
        'request_type': 'Hardware',
        'priority': 'Critical',
        'description': 'Updated description.',
        'justification': 'Still broken.',
        'target_type': '',
    }
    response = auth_client.post(
        f'/requests/{request_data["request_id"]}/edit', data=data, follow_redirects=True
    )
    assert response.status_code == 200

    with app.app_context():
        req = db.session.get(Request, request_data['request_id'])
        assert req.title == 'Need a new laptop (updated)'
        assert req.priority == 'Critical'


# --- Lifecycle ---

def test_full_lifecycle(auth_client, request_data, app):
    rid = request_data['request_id']

    # Pending -> Triage
    auth_client.post(f'/requests/{rid}/triage', follow_redirects=True)
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'Triage'
        assert req.triaged_at is not None
        assert req.triaged_by_id is not None

    # Triage -> In Progress
    auth_client.post(f'/requests/{rid}/start', follow_redirects=True)
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'In Progress'
        assert req.started_at is not None

    # In Progress -> Completed (with resolution notes)
    auth_client.post(
        f'/requests/{rid}/complete',
        data={'resolution_notes': 'Laptop delivered.'},
        follow_redirects=True,
    )
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'Completed'
        assert req.completed_at is not None
        assert req.resolution_notes == 'Laptop delivered.'

    # Completed -> Closed
    auth_client.post(f'/requests/{rid}/close', follow_redirects=True)
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'Closed'
        assert req.closed_at is not None


def test_invalid_transition_is_blocked(auth_client, request_data, app):
    """Starting a Pending request (skipping triage) should not change status."""
    rid = request_data['request_id']
    auth_client.post(f'/requests/{rid}/start', follow_redirects=True)
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'Pending'  # unchanged


def test_cancel_request(auth_client, request_data, app):
    rid = request_data['request_id']
    auth_client.post(f'/requests/{rid}/cancel', follow_redirects=True)
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.status == 'Cancelled'
        assert req.closed_at is not None


def test_edit_blocked_when_closed(auth_client, request_data, app):
    """A cancelled/closed request cannot be edited."""
    rid = request_data['request_id']
    auth_client.post(f'/requests/{rid}/cancel', follow_redirects=True)
    response = auth_client.post(
        f'/requests/{rid}/edit',
        data={'title': 'should not save', 'request_type': 'General', 'priority': 'Low'},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        req = db.session.get(Request, rid)
        assert req.title == 'Need a new laptop'  # unchanged


# --- Evidence upload ---

def test_add_evidence_upload(auth_client, request_data, app):
    rid = request_data['request_id']
    data = {
        'file': (io.BytesIO(b'approval screenshot bytes'), 'approval.png'),
    }
    response = auth_client.post(
        f'/requests/{rid}/add_evidence', data=data,
        content_type='multipart/form-data', follow_redirects=True
    )
    assert response.status_code == 200
    with app.app_context():
        req = db.session.get(Request, rid)
        assert len(req.attachments) == 1
        att = req.attachments[0]
        assert att.filename == 'approval.png'
        assert att.linkable_type == 'Request'
        assert att.linkable_id == rid


def test_add_evidence_no_file(auth_client, request_data, app):
    rid = request_data['request_id']
    response = auth_client.post(
        f'/requests/{rid}/add_evidence', data={},
        content_type='multipart/form-data', follow_redirects=True
    )
    assert response.status_code == 200
    with app.app_context():
        req = db.session.get(Request, rid)
        assert len(req.attachments) == 0


# --- Permission gating ---

def _login(client, email, password='password'):
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def test_read_permission_required(client, app, request_data):
    """A user without the operations module is redirected away from the list."""
    with app.app_context():
        u = User(name='No Access', email='noaccess@test.com', role='user')
        u.set_password('password')
        db.session.add(u)
        db.session.commit()

    _login(client, 'noaccess@test.com')
    response = client.get('/requests/', follow_redirects=False)
    assert response.status_code == 302  # redirected to dashboard, not served


def test_write_permission_required(client, app, request_data):
    """A read-only operations user cannot create a request."""
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        module = Module.query.filter_by(slug='operations').first()
        if not module:
            module = Module(name='Operations', slug='operations')
            db.session.add(module)
            db.session.flush()
        reader = User(name='Read Only', email='readonly@test.com', role='user')
        reader.set_password('password')
        db.session.add(reader)
        db.session.flush()
        db.session.add(Permission(module_id=module.id, user_id=reader.id,
                                  access_level=AccessLevel.READ_ONLY))
        db.session.commit()
        permissions_cache.invalidate()

    _login(client, 'readonly@test.com')

    # Read access works
    assert client.get('/requests/').status_code == 200

    # Write is blocked
    response = client.post('/requests/new', data={
        'title': 'Should not be created',
        'request_type': 'General',
        'priority': 'Low',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert Request.query.filter_by(title='Should not be created').first() is None


# --- My Dashboard & action alerts surface assigned requests ---

def _assign_request(app, request_data, status):
    with app.app_context():
        assignee = db.session.get(User, request_data['assignee_id'])
        req = db.session.get(Request, request_data['request_id'])
        req.assignee_id = assignee.id
        req.status = status
        db.session.commit()
        return assignee.email


def test_assigned_open_request_in_action_alerts(app, request_data):
    from src.routes.main import get_action_required_alerts
    _assign_request(app, request_data, 'Triage')
    with app.app_context():
        assignee = db.session.get(User, request_data['assignee_id'])
        with app.test_request_context():
            alerts = get_action_required_alerts(assignee)
    assert any('Need a new laptop' in a['message'] for a in alerts)


def test_completed_request_not_in_action_alerts(app, request_data):
    from src.routes.main import get_action_required_alerts
    _assign_request(app, request_data, 'Completed')
    with app.app_context():
        assignee = db.session.get(User, request_data['assignee_id'])
        with app.test_request_context():
            alerts = get_action_required_alerts(assignee)
    assert not any('Need a new laptop' in a['message'] for a in alerts)


def test_assigned_request_shown_on_my_dashboard(client, app, request_data):
    email = _assign_request(app, request_data, 'In Progress')
    _login(client, email)
    response = client.get('/my-dashboard')
    assert response.status_code == 200
    assert b'Need a new laptop' in response.data


# --- "My Tickets" (opened by me) vs assigned distinction ---

def test_opened_request_not_in_action_alerts(app, request_data):
    """A request I opened (not assigned to me) must NOT surface in the bell."""
    from src.routes.main import get_action_required_alerts
    with app.app_context():
        requester = db.session.get(User, request_data['requester_id'])
        with app.test_request_context():
            alerts = get_action_required_alerts(requester)
    assert not any('Need a new laptop' in a['message'] for a in alerts)


def test_my_open_tickets_includes_opened_request(app, request_data):
    from src.routes.main import get_my_open_tickets
    with app.app_context():
        requester = db.session.get(User, request_data['requester_id'])
        with app.test_request_context():
            tickets = get_my_open_tickets(requester)
    assert any(t['title'] == 'Need a new laptop' for t in tickets)


def test_my_open_tickets_excludes_old_closed(app, request_data):
    from src.routes.main import get_my_open_tickets
    with app.app_context():
        req = db.session.get(Request, request_data['request_id'])
        req.status = 'Closed'
        req.closed_at = now() - timedelta(days=20)
        db.session.commit()
        requester = db.session.get(User, request_data['requester_id'])
        with app.test_request_context():
            tickets = get_my_open_tickets(requester)
    assert not any(t['title'] == 'Need a new laptop' for t in tickets)


def test_my_open_tickets_includes_recently_closed(app, request_data):
    from src.routes.main import get_my_open_tickets
    with app.app_context():
        req = db.session.get(Request, request_data['request_id'])
        req.status = 'Closed'
        req.closed_at = now() - timedelta(days=5)
        db.session.commit()
        requester = db.session.get(User, request_data['requester_id'])
        with app.test_request_context():
            tickets = get_my_open_tickets(requester)
    assert any(t['title'] == 'Need a new laptop' for t in tickets)


def test_my_tickets_card_on_my_dashboard(client, app, request_data):
    with app.app_context():
        email = db.session.get(User, request_data['requester_id']).email
    _login(client, email)
    response = client.get('/my-dashboard')
    assert response.status_code == 200
    assert b'My Tickets' in response.data
    assert b'Need a new laptop' in response.data
