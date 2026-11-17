from .base import BaseConnector
from typing import Dict, List, Optional
import requests

class MicrosoftConnector(BaseConnector):
    """
    Connector for Microsoft 365 (Graph API).
    
    Supports endpoints like:
    - /v1.0/users
    - /v1.0/groups
    
    Authentication:
    - Uses OAuth2 Client Credentials Flow (Tenant ID, Client ID, Client Secret)
    """
    
    def get_base_url(self) -> str:
        return "https://graph.microsoft.com"
    
    def authenticate(self) -> None:
        """
        Authenticate using Client Credentials Flow to get an access token.
        """
        if not self.task.auth_config:
            raise ValueError("No auth_config found for Microsoft connector")
        
        tenant_id = self.task.auth_config.get('tenant_id')
        client_id = self.task.auth_config.get('client_id')
        client_secret = self.task.auth_config.get('client_secret')
        
        if not tenant_id or not client_id or not client_secret:
            raise ValueError("Microsoft auth requires 'tenant_id', 'client_id', and 'client_secret'")
            
        # Get access token
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials'
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=30)
            response.raise_for_status()
            
            token_data = response.json()
            access_token = token_data['access_token']
            
            self.session.headers.update({
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            })
            
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to authenticate with Microsoft Graph: {str(e)}")
    
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        Microsoft Graph API returns items in 'value' key.
        """
        if 'value' in response_data:
            return response_data['value']
            
        return []
    
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        Microsoft Graph uses '@odata.nextLink' which is a full URL.
        """
        next_link = response_data.get('@odata.nextLink')
        if next_link:
            # We return the full URL as the token because our base connector 
            # might expect just a token. However, for Graph API, it's easier 
            # to just handle the full URL in build_request_url
            return next_link
        return None
        
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Override to handle full URL pagination.
        """
        if page_token and page_token.startswith('http'):
            return page_token
            
        return super().build_request_url(page_token)
