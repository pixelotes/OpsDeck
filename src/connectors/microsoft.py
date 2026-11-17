from .base import BaseConnector
from typing import Dict, List, Optional

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
        Get an app-only Graph token (client credentials) and attach it to the session.

        Credentials come either from the task (tenant_id / client_id / client_secret,
        stored encrypted) or, when the task has ``use_entra_app``, from the
        AZURE_OAUTH_* settings shared with Microsoft sign-in and the Entra ID user sync,
        so no secret is stored in the database at all.
        """
        from flask import current_app
        from . import msgraph

        if not self.auth:
            raise ValueError("No auth_config found for Microsoft connector")

        if self.auth.get('use_entra_app'):
            creds = msgraph.entra_app_credentials(current_app.config)
            if creds is None:
                raise ValueError(
                    "This task uses the Entra ID app registration, but AZURE_OAUTH_CLIENT_ID, "
                    "AZURE_OAUTH_CLIENT_SECRET and a single-tenant AZURE_OAUTH_TENANT_ID are not all set")
            tenant_id, client_id, client_secret = creds
        else:
            tenant_id = self.auth.get('tenant_id')
            client_id = self.auth.get('client_id')
            client_secret = self.auth.get('client_secret')
            if not tenant_id or not client_id or not client_secret:
                raise ValueError("Microsoft auth requires 'tenant_id', 'client_id', and 'client_secret'")

        try:
            access_token, _ = msgraph.fetch_app_token(self.session, tenant_id, client_id, client_secret)
        except msgraph.GraphError as e:
            raise ValueError(f"Failed to authenticate with Microsoft Graph: {e}") from e

        self.session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        })

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
