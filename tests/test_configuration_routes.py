from src.models import Configuration, User
import json

def test_configuration_lifecycle(auth_client, app):
    """
    Tests the full lifecycle of a Configuration: Create, Edit (Snapshot), Compare.
    """
    # Verify User exists
    with app.app_context():
        print("User count:", User.query.count())
        admin = User.query.filter_by(email='admin@test.com').first()
        print(f"Admin exists: {admin.email if admin else 'No'}")

    # --- 1. CREATE CONFIGURATION ---
    response = auth_client.post('/configuration/new', data={
        'name': 'Prod Firewall',
        'description': 'Main firewall rules'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Prod Firewall' in response.data
    assert b'Version 1' in response.data  # Should have initial version
    
    # Verify DB
    with app.app_context():
        config = Configuration.query.first()
        assert config is not None
        assert config.name == 'Prod Firewall'
        assert config.versions.count() == 1
        assert config.latest_version.version_number == 1
        assert config.latest_version.data == {}

    # --- 2. CREATE SNAPSHOT (EDIT) ---
    # Simulate saving new data (Groups/Keys)
    new_data = {
        "Network": {
            "inbound": "allow 80, 443",
            "outbound": "deny all"
        },
        "General": {
            "logging": "enabled"
        }
    }
    
    response = auth_client.post(f'/configuration/{config.id}/snapshot', data={
        'config_data': json.dumps(new_data),
        'commit_message': 'Added network rules'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Snapshot v2 saved' in response.data
    
    # Verify DB
    with app.app_context():
        config = Configuration.query.first()
        assert config.latest_version.version_number == 2
        assert config.latest_version.data['Network']['inbound'] == 'allow 80, 443'

    # --- 3. COMPARE VERSIONS ---
    response = auth_client.get(f'/configuration/{config.id}/compare?v1=1&v2=2')
    
    assert response.status_code == 200
    assert b'Compare Versions' in response.data
    assert b'Prod Firewall' in response.data
    # Should see added keys in the diff view
    # Since deepdiff might group them, we look for key strings
    assert b'Network' in response.data 
    assert b'inbound' in response.data
    assert b'allow 80, 443' in response.data
    
    print("Configuration Lifecycle Test Passed!")
