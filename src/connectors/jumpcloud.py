from .base import BaseConnector
from typing import Dict, List, Optional


class JumpCloudConnector(BaseConnector):
    """
    Connector for JumpCloud Directory-as-a-Service API.
    
    Supports endpoints like:
    - /api/systemusers - All system users (V1 API)
    - /api/systems - All managed systems/devices (V1 API)
    
    Note: JumpCloud uses V1 API for listing users and systems.
    V2 API is primarily for associations and specific resource operations.
    
    Authentication:
    - Uses API Key (x-api-key header)
    - Optional X-Org-Id header for multi-tenant organizations
    - Generated from JumpCloud Admin Portal
    
    Pagination:
    - Uses limit/offset (skip) parameters
    - Recommended to sort by _id for consistency
    - Default: 100 items per request
    
    User Data Includes:
    - Basic info (email, username, firstname, lastname)
    - Account status (activated, suspended, etc.)
    - Last authentication timestamps
    - MFA status
    - External DN, attributes
    
    System Data Includes:
    - Hostname, display name
    - OS type and version
    - Agent version
    - Last contact timestamp
    - IP addresses  
    - Active/inactive status
    
    Note: Does NOT fetch software inventory to avoid large payload sizes
    """
    
    def __init__(self, task, subtask):
        super().__init__(task, subtask)
        self.per_page = 100  # JumpCloud recommended page size
        self.current_skip = 0
    
    def get_base_url(self) -> str:
        return "https://console.jumpcloud.com"
    
    def authenticate(self) -> None:
        """
        Set up API key authentication for JumpCloud.
        
        Requires 'api_key' in task.auth_config.
        Optional 'org_id' for multi-tenant organizations.
        
        To generate API key:
        1. Login to JumpCloud Admin Portal
        2. Click on your name/initials > My API Key
        3. Generate new API key (set expiration as needed)
        4. Copy the key
        
        To find Org ID (for multi-tenant):
        1. Login to JumpCloud Admin Portal
        2. Go to Settings > Organization
        3. Copy the Organization ID
        """
        if not self.auth:
            raise ValueError("No auth_config found for JumpCloud connector")
        
        api_key = self.auth.get('api_key')
        
        if not api_key:
            raise ValueError("No 'api_key' found in auth_config")
        
        # JumpCloud uses x-api-key header
        headers = {
            'x-api-key': api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'OpsDeck'
        }
        
        # For multi-tenant organizations, X-Org-Id header is required
        org_id = self.auth.get('org_id')
        if org_id:
            headers['X-Org-Id'] = org_id
        
        self.session.headers.update(headers)
    
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Build JumpCloud API URL with pagination.
        
        Uses limit/offset (skip) pagination with sort by _id for consistency.
        """
        base_url = self.get_base_url()
        endpoint = self.subtask.endpoint
        
        # Ensure endpoint starts with /
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        
        url = f"{base_url}{endpoint}"
        
        # Add pagination  parameters
        # JumpCloud uses 'skip' for offset and 'limit' for page size
        if page_token:
            # page_token is the skip value
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}limit={self.per_page}&skip={page_token}&sort=_id"
        else:
            # First page
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}limit={self.per_page}&skip=0&sort=_id"
        
        return url
    
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        JumpCloud v2 APIs return direct arrays.
        
        Response format: [ {...}, {...}, ... ]
        """
        # V2 endpoints return arrays directly
        if isinstance(response_data, list):
            return response_data
        
        # V1 or some special endpoints might return wrapped results
        if isinstance(response_data, dict):
            # Check for 'results' key (V1 style)
            if 'results' in response_data:
                return response_data['results']
            
            # Single object - wrap in list
            return [response_data]
        
        return []
    
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        JumpCloud uses offset pagination.
        
        Continue fetching if we got a full page.
        """
        # If response is a list
        if isinstance(response_data, list):
            # If we got fewer items than per_page, we're done
            if len(response_data) < self.per_page:
                return None
            
            # Otherwise, increment skip
            self.current_skip += self.per_page
            return str(self.current_skip)
        
        # For wrapped responses (V1 style)
        if isinstance(response_data, dict) and 'results' in response_data:
            results = response_data['results']
            if len(results) < self.per_page:
                return None
            
            self.current_skip += self.per_page
            return str(self.current_skip)
        
        return None


# Example auth_config for JumpCloud:
# {
#     "api_key": "your_jumpcloud_api_key_here",
#     "org_id": "your_org_id_here"  # Optional, required for multi-tenant organizations
# }
#
# How to generate API key:
# 1. Login to https://console.jumpcloud.com
# 2. Click on your initials/name (top right)
# 3. Select "My API Key"
# 4. Click "Generate New API Key"
# 5. Set expiration (30/60/90 days or custom)
# 6. Copy and save the key (shown only once)
#
# How to find Org ID (for multi-tenant setups):
# 1. Login to https://console.jumpcloud.com
# 2. Go to Settings > Organization
# 3. Copy the Organization ID
#
# Permissions:
# - API access must be enabled for your admin account
# - Key has same permissions as your admin account
# - Recommended: Use a dedicated admin account for API access
