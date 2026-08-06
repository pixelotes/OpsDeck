import pytest
from src.models import OrgChartSnapshot, User, db

@pytest.fixture
def snapshot_user(app):
    with app.app_context():
        user = User(name='Snapshot User', email='snapshot@example.com', role='admin')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        return user

def test_create_org_chart_snapshot(auth_client, app, snapshot_user):
    """Test creating an org chart snapshot."""
    # Ensure we have some users for the chart
    with app.app_context():
        u1 = User(name='CEO', email='ceo@example.com')
        u2 = User(name='CTO', email='cto@example.com', manager=u1)
        db.session.add(u1)
        db.session.add(u2)
        db.session.commit()

    response = auth_client.post('/users/org-chart/snapshot', data={
        'name': 'Test Snapshot 2024',
        'notes': 'End of year structure'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Organizational structure snapshot saved successfully.' in response.data
    assert b'Test Snapshot 2024' in response.data

    with app.app_context():
        snapshot = OrgChartSnapshot.query.filter_by(name='Test Snapshot 2024').first()
        assert snapshot is not None
        assert snapshot.notes == 'End of year structure'
        assert len(snapshot.chart_data) >= 2 # CEO + CTO + admin user + snapshot user

def test_list_org_chart_snapshots(auth_client, app):
    """Test listing org chart snapshots."""
    # Create a dummy snapshot
    with app.app_context():
        snapshot = OrgChartSnapshot(
            name='Historical 2023',
            chart_data=[],
            notes='Old one'
        )
        db.session.add(snapshot)
        db.session.commit()

    response = auth_client.get('/users/org-chart/snapshots')
    assert response.status_code == 200
    assert b'Historical 2023' in response.data

def test_view_org_chart_snapshot(auth_client, app):
    """Test viewing a specific snapshot."""
    with app.app_context():
        data = [{'id': 1, 'name': 'Boss', 'title': 'The Boss'}]
        snapshot = OrgChartSnapshot(
            name='Detail View Test',
            chart_data=data,
            notes='Testing view'
        )
        db.session.add(snapshot)
        db.session.commit()
        snapshot_id = snapshot.id

    response = auth_client.get(f'/users/org-chart/snapshots/{snapshot_id}')
    assert response.status_code == 200
    assert b'Detail View Test' in response.data
    assert b'Detail View Test' in response.data
    assert b'The Boss' in response.data

def test_link_snapshot_to_audit(auth_client, app):
    """Test linking an org chart snapshot to an audit control (evidence)."""
    from src.models import ComplianceAudit, AuditControlLink, Framework, FrameworkControl, User
    
    with app.app_context():
        # 1. Create Snapshot
        snapshot = OrgChartSnapshot(name='Evidence Snapshot', chart_data=[], notes='For Audit')
        db.session.add(snapshot)
        
        # 2. Create Audit & Item
        fw = Framework(name='Test Ref', is_custom=True)
        fc = FrameworkControl(control_id='REF.1', name='Ref Control')
        fw.framework_controls.append(fc)
        db.session.add(fw)
        db.session.commit()
        
        lead = User.query.first() or User(name='Lead', email='lead@test.com', role='admin') # Fallback if no user
        if not lead.id:
             db.session.add(lead)
             db.session.commit()

        audit = ComplianceAudit.create_snapshot(
            framework_id=fw.id,
            name='Snapshot Audit',
            internal_lead_id=lead.id,
            auditor_contact_id=None
        )
        item = audit.audit_items.first()
        
        # 3. Create Link
        link = AuditControlLink(
            audit_item_id=item.id,
            linkable_type='OrgChartSnapshot',
            linkable_id=snapshot.id,
            description='Proof of structure'
        )
        db.session.add(link)
        db.session.commit()
        
        link_id = link.id
        snapshot_id = snapshot.id

    # 4. Verify Link Retrieval
    with app.app_context():
        link = db.session.get(AuditControlLink, link_id)
        assert link is not None
        assert link.linkable_type == 'OrgChartSnapshot'
        assert link.linked_object.id == snapshot_id
        assert link.linked_object.name == 'Evidence Snapshot'

