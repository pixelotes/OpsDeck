from .base import BaseConnector
from typing import Dict, List, Optional
import json
import time
import jwt
import requests


class GoogleWorkspaceConnector(BaseConnector):
    """
    Connector for Google Workspace Admin API and Chrome Management API.
    
    Supports endpoints like:
    - /admin/directory/v1/users (Admin SDK)
    - /admin/directory/v1/groups (Admin SDK)
    - /admin/directory/v1/customer/my_customer/devices/chromeos (Admin SDK)
    - /v1/customers/my_customer/telemetry/devices (Chrome Management API)
    
    Authentication:
    - Uses OAuth2 service account (recommended for production)
    - Supports both service account JSON and access tokens
    
    auth_config with a service account:
    - service_account_json: the key file downloaded from Google Cloud, parsed as a dict
      (it must contain client_email and private_key)
    - delegated_user: the admin the service account impersonates (domain-wide delegation)

    Or with access token (for testing):
    {
        "access_token": "ya29...."
    }
    """
    
    # Google Workspace Admin SDK + Chrome Management API scopes
    SCOPES = [
        'https://www.googleapis.com/auth/admin.directory.user.readonly',
        'https://www.googleapis.com/auth/admin.directory.group.readonly',
        'https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly',
        'https://www.googleapis.com/auth/chrome.management.telemetry.readonly',
    ]
    
    def get_base_url(self) -> str:
        """
        Return the appropriate base URL based on the endpoint.
        Admin SDK uses googleapis.com, Chrome Management uses chromemanagement.googleapis.com
        """
        endpoint = self.subtask.endpoint
        
        # Chrome Management API endpoints start with /v1/customers
        if endpoint.startswith('/v1/customers'):
            return "https://chromemanagement.googleapis.com"
        
        # Default to Admin SDK
        return "https://www.googleapis.com"
    
    def _generate_jwt_token(self, service_account_info: Dict, delegated_user: str) -> str:
        """
        Generate a JWT token for service account authentication.
        
        Args:
            service_account_info: Service account JSON data
            delegated_user: Email of the user to impersonate (for domain-wide delegation)
            
        Returns:
            JWT token string
        """
        now = int(time.time())
        
        # Create JWT payload
        payload = {
            'iss': service_account_info['client_email'],
            'sub': delegated_user,  # User to impersonate
            'scope': ' '.join(self.SCOPES),
            'aud': 'https://oauth2.googleapis.com/token',
            'iat': now,
            'exp': now + 3600  # Token valid for 1 hour
        }
        
        # Sign the JWT with the private key
        private_key = service_account_info['private_key']
        token = jwt.encode(payload, private_key, algorithm='RS256')
        
        # PyJWT may return bytes or str depending on version
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        
        return token
    
    def _exchange_jwt_for_access_token(self, jwt_token: str) -> str:
        """
        Exchange JWT token for an OAuth2 access token.
        
        Args:
            jwt_token: Signed JWT token
            
        Returns:
            Access token string
        """
        token_url = 'https://oauth2.googleapis.com/token'
        
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': jwt_token
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=30)
            response.raise_for_status()
            
            token_data = response.json()
            return token_data['access_token']
        except requests.exceptions.HTTPError as e:
            # Get more details from the error response
            error_detail = ""
            try:
                error_data = response.json()
                error_detail = f": {error_data.get('error_description', error_data.get('error', 'Unknown error'))}"
            except ValueError:  # the error body is not JSON
                pass
            
            raise ValueError(
                f"Failed to exchange JWT for access token (HTTP {response.status_code}){error_detail}. "
                f"Check that domain-wide delegation is enabled and scopes are granted in Google Workspace Admin Console."
            ) from e
    
    def authenticate(self) -> None:
        """
        Set up OAuth2 authentication for Google API.
        
        Supports two methods:
        1. Service account JSON (recommended) - generates access token automatically
        2. Access token (for testing) - uses provided token directly
        """
        if not self.task.auth_config:
            raise ValueError("No auth_config found for Google Workspace connector")
        
        # Method 1: Service account JSON (recommended)
        service_account_json = self.task.auth_config.get('service_account_json')
        if service_account_json:
            # Parse if it's a string
            if isinstance(service_account_json, str):
                service_account_info = json.loads(service_account_json)
            else:
                service_account_info = service_account_json
            
            # Get delegated user (required for domain-wide delegation)
            delegated_user = self.task.auth_config.get('delegated_user')
            if not delegated_user:
                raise ValueError(
                    "Missing 'delegated_user' in auth_config. "
                    "For Google Workspace, you must specify which admin user to impersonate. "
                    "Example: 'admin@yourdomain.com'"
                )
            
            # Generate JWT and exchange for access token
            jwt_token = self._generate_jwt_token(service_account_info, delegated_user)
            access_token = self._exchange_jwt_for_access_token(jwt_token)
            
            self.session.headers.update({
                'Authorization': f'Bearer {access_token}'
            })
            return
        
        # Method 2: Direct access token (for testing)
        access_token = self.task.auth_config.get('access_token')
        if access_token:
            self.session.headers.update({
                'Authorization': f'Bearer {access_token}'
            })
            return
        
        raise ValueError(
            "No valid credentials in auth_config. Provide either:\n"
            "1. 'service_account_json' + 'delegated_user' (recommended), or\n"
            "2. 'access_token' (for testing)"
        )
    
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Override to add required query parameters for Google Workspace APIs.
        
        Google Admin SDK requires 'customer' parameter for users and groups.
        """
        base_url = self.get_base_url()
        endpoint = self.subtask.endpoint
        url = f"{base_url}{endpoint}"
        
        # Add required parameters based on endpoint
        params = []
        
        # Users and Groups endpoints require 'customer' parameter
        if '/users' in endpoint or '/groups' in endpoint:
            params.append('customer=my_customer')
        
        # Chrome Management API requires readMask
        if '/telemetry/devices' in endpoint:
            # Request identification and status fields
            params.append('readMask=name,deviceId,serialNumber,orgUnitId,lastSyncTime')
        
        # Add pagination token if present
        if page_token:
            params.append(f'pageToken={page_token}')
        
        # Append parameters to URL
        if params:
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}{'&'.join(params)}"
        
        return url
    
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        Google APIs typically return items in 'users', 'groups', 'devices', etc.
        """
        # Try common field names
        for key in ['users', 'groups', 'devices', 'chromeosdevices', 'items']:
            if key in response_data:
                return response_data[key]
        
        # Fallback: if response itself is a list
        if isinstance(response_data, list):
            return response_data
            
        return []
    
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        Google uses 'nextPageToken' for pagination.
        """
        return response_data.get('nextPageToken')
