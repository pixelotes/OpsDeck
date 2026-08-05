from src.models import User, Policy, PolicyVersion, db, PolicyAcknowledgement
from src.utils.timezone_helper import today

def test_my_policies_flow(client, app):
    with app.app_context():
        # Setup data
        user = User.query.filter_by(email="admin@opsdeck.io").first()
        if not user:
            user = User(name="Test User", email="test@opsdeck.io", role="admin")
            user.set_password("password")
            db.session.add(user)
            db.session.commit()
            
        policy = Policy(title="Test Policy", category="General")
        db.session.add(policy)
        db.session.commit()
        
        version = PolicyVersion(
            policy_id=policy.id,
            version_number="1.0",
            status="Active",
            effective_date=today(),
            content="Policy content"
        )
        # Assign to user specifically to test logic
        version.users_to_acknowledge.append(user)
        db.session.add(version)
        db.session.commit()
        
        version_id = version.id

    # Login
    client.post('/login', data={'email': user.email, 'password': 'password'})
    
    # 1. Access My Policies
    resp = client.get('/compliance/my-policies', follow_redirects=True)
    assert resp.status_code == 200
    assert b"My Policies" in resp.data
    assert b"Test Policy - v1.0" in resp.data
    assert b"View & Acknowledge" in resp.data
    assert f"policies/version/{version_id}".encode() in resp.data
    assert b"Pending" in resp.data
    
    # 2. Acknowledge Policy
    resp = client.post(f'/policies/version/{version_id}/acknowledge', follow_redirects=True)
    assert resp.status_code == 200
    assert b"successfully acknowledged" in resp.data
    
    # 3. Verify Update
    resp = client.get('/compliance/my-policies', follow_redirects=True)
    assert resp.status_code == 200
    assert b"Acknowledged on" in resp.data
    assert b"Pending" not in resp.data
    
    # Cleanup
    with app.app_context():
        db.session.query(PolicyAcknowledgement).delete()
        db.session.query(PolicyVersion).delete()
        db.session.query(Policy).delete()
        if user.email == "test@opsdeck.io":
            db.session.delete(user)
        db.session.commit()
