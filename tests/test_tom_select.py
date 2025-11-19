import pytest

def test_tom_select_assets(auth_client):
    # The dashboard is at root '/'
    response = auth_client.get('/')
    assert response.status_code == 200
    content = response.data.decode('utf-8')
    
    # Check for CSS
    assert 'tom-select.bootstrap5.min.css' in content
    
    # Check for JS
    assert 'tom-select.complete.min.js' in content
    
    # Check for Initialization Script
    assert "new TomSelect(el" in content
    assert "plugins: {" in content
    assert "remove_button" in content
