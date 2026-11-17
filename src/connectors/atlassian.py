from .base import BaseConnector
from typing import Dict, List, Optional


class AtlassianConnector(BaseConnector):
    """
    Connector for Atlassian Cloud APIs (Jira, Confluence).
    
    Supports endpoints like:
    - /rest/api/3/users/search (Jira)
    - /wiki/rest/api/space (Confluence)
    
    Authentication:
    - Uses API tokens with email
    - Expects 'email' and 'api_token' in task.auth_config
    """
    
    def get_base_url(self) -> str:
        """
        Base URL includes the site domain.
        Expected in auth_config as 'site_url'
        e.g., 'https://yourcompany.atlassian.net'
        """
        if not self.auth:
            raise ValueError("No auth_config found for Atlassian connector")
        
        site_url = self.auth.get('site_url')
        if not site_url:
            raise ValueError("No 'site_url' found in auth_config")
        
        return site_url.rstrip('/')
    
    def authenticate(self) -> None:
        """
        Set up basic auth for Atlassian API.
        Uses email + API token.
        """
        if not self.auth:
            raise ValueError("No auth_config found for Atlassian connector")
        
        email = self.auth.get('email')
        api_token = self.auth.get('api_token')
        
        if not email or not api_token:
            raise ValueError("Atlassian auth requires 'email' and 'api_token' in auth_config")
        
        # Atlassian uses HTTP Basic Auth
        self.session.auth = (email, api_token)
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        Atlassian APIs use different field names:
        - Jira: usually direct array or 'values'
        - Confluence: 'results'
        """
        # Try common field names
        for key in ['values', 'results', 'items']:
            if key in response_data:
                return response_data[key]
        
        # Fallback: if response itself is a list
        if isinstance(response_data, list):
            return response_data
            
        return []
    
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        Atlassian pagination varies:
        - Jira uses 'startAt' + 'maxResults' (offset-based)
        - Confluence uses 'next' cursor in '_links'
        
        For simplicity, we'll check both patterns.
        """
        # Check for cursor-based (Confluence style)
        if '_links' in response_data and 'next' in response_data['_links']:
            return 'next'  # Signal that there's a next page
        
        # Check for offset-based (Jira style)
        if 'startAt' in response_data and 'maxResults' in response_data and 'total' in response_data:
            start_at = response_data['startAt']
            max_results = response_data['maxResults']
            total = response_data['total']
            
            next_start = start_at + max_results
            if next_start < total:
                return str(next_start)  # Return next offset
        
        return None
    
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Override to handle Atlassian's pagination patterns.
        """
        base_url = self.get_base_url()
        endpoint = self.subtask.endpoint
        url = f"{base_url}{endpoint}"
        
        if page_token:
            if page_token == 'next':
                # This would need the actual next URL from _links
                # For now, we'll skip this advanced case
                pass
            else:
                # Offset-based pagination
                separator = '&' if '?' in url else '?'
                url = f"{url}{separator}startAt={page_token}"
        
        return url
