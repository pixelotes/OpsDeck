"""Tests for Organization Settings feature."""
from src.models import OrganizationSettings


def test_organization_settings_page_loads(auth_client, app):
    """Test that the organization settings page loads correctly."""
    response = auth_client.get('/settings/organization/settings')
    assert response.status_code == 200
    assert b'Organization Settings' in response.data
    assert b'Legal Information' in response.data


def test_organization_settings_update(auth_client, app):
    """Test updating organization settings."""
    response = auth_client.post('/settings/organization/settings', data={
        'legal_name': 'OpsDeck S.L.',
        'tax_id': 'B-12345678',
        'primary_domain': 'opsdeck.com',
        'email_domains': 'opsdeck.com, opsdeck.es'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Organization settings updated successfully' in response.data
    
    # Verify data was saved
    with app.app_context():
        settings = OrganizationSettings.query.first()
        assert settings is not None
        assert settings.legal_name == 'OpsDeck S.L.'
        assert settings.tax_id == 'B-12345678'
        assert settings.primary_domain == 'opsdeck.com'
        assert 'opsdeck.com' in settings.email_domains_list
        assert 'opsdeck.es' in settings.email_domains_list


def test_organization_settings_singleton(auth_client, app):
    """Test that OrganizationSettings maintains singleton pattern."""
    # First access creates the singleton
    auth_client.get('/settings/organization/settings')
    
    # Update with some data
    auth_client.post('/settings/organization/settings', data={
        'legal_name': 'First Visit',
        'tax_id': 'A-111',
        'primary_domain': '',
        'email_domains': ''
    }, follow_redirects=True)
    
    # Second access should reuse the same record
    auth_client.post('/settings/organization/settings', data={
        'legal_name': 'Second Visit',
        'tax_id': 'B-222',
        'primary_domain': '',
        'email_domains': ''
    }, follow_redirects=True)
    
    with app.app_context():
        count = OrganizationSettings.query.count()
        assert count == 1, f"Expected 1 OrganizationSettings record, found {count}"
        
        settings = OrganizationSettings.query.first()
        assert settings.legal_name == 'Second Visit'
        assert settings.tax_id == 'B-222'


def test_location_with_new_fields(auth_client, app):
    """Test creating a location with the new physical address fields."""
    # Create a location with all new fields
    response = auth_client.post('/locations/new', data={
        'name': 'Barcelona Office',
        'address': 'Carrer de la Marina 100',
        'city': 'Barcelona',
        'zip_code': '08005',
        'country': 'Spain',
        'timezone': 'Europe/Madrid',
        'tax_id_override': '',
        'phone': '+34 93 123 4567',
        'reception_email': 'reception@bcn.opsdeck.com'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Location created successfully' in response.data
    
    # Verify data was saved
    from src.models import Location
    with app.app_context():
        location = Location.query.filter_by(name='Barcelona Office').first()
        assert location is not None
        assert location.address == 'Carrer de la Marina 100'
        assert location.city == 'Barcelona'
        assert location.zip_code == '08005'
        assert location.country == 'Spain'
        assert location.timezone == 'Europe/Madrid'
        assert location.phone == '+34 93 123 4567'
        assert location.reception_email == 'reception@bcn.opsdeck.com'
        assert location.is_physical_site == True
