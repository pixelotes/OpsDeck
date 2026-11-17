from .base import BaseConnector
from typing import Dict, List, Optional
import logging

import requests

logger = logging.getLogger(__name__)


class GitHubConnector(BaseConnector):
    """
    Connector for GitHub REST API v3.
    
    Supports endpoints like:
    - /orgs/{org}/members - Organization members
    - /orgs/{org}/outside_collaborators - External collaborators
    - /orgs/{org}/repos - Organization repositories
    - /users/{username}/repos - User repositories
    
    Authentication:
    - Uses Personal Access Token (PAT) or GitHub App token
    - Expects 'access_token' in task.auth_config
    
    Pagination:
    - GitHub uses Link headers (RFC 5988) with rel="next"
    - Also supports ?page=N&per_page=100 query params
    """
    
    def __init__(self, task, subtask):
        super().__init__(task, subtask)
        # GitHub recommends 100 items per page
        self.per_page = 100
    
    def get_base_url(self) -> str:
        return "https://api.github.com"
    
    def authenticate(self) -> None:
        """
        Set up token authentication for GitHub API.
        
        Requires 'access_token' in task.auth_config.
        Format: ghp_xxxxxxxxxxxx (classic token) or github_pat_xxxx (fine-grained)
        
        Required scopes depend on endpoints:
        - read:org - for members and outside collaborators
        - repo - for repositories
        """
        logger.debug("[GitHub] Starting authentication")
        
        if not self.task.auth_config:
            logger.error("[GitHub] No auth_config found in task")
            raise ValueError("No auth_config found for GitHub connector")
        
        access_token = self.task.auth_config.get('access_token')
        
        if not access_token:
            logger.error("[GitHub] No 'access_token' in auth_config")
            raise ValueError("No 'access_token' found in auth_config")
        
        # Validate token format (basic check)
        token_prefix = access_token[:10] if len(access_token) > 10 else access_token
        logger.debug(f"[GitHub] Token prefix: {token_prefix}...")
        
        if access_token == "ghp_REPLACE_WITH_YOUR_TOKEN":
            logger.error("[GitHub] Token is still the placeholder value!")
            raise ValueError("GitHub access_token is still the placeholder 'ghp_REPLACE_WITH_YOUR_TOKEN'. Please configure a real token.")
        
        # GitHub uses "token" or "Bearer" in Authorization header
        # Modern approach uses "token" prefix
        self.session.headers.update({
            'Authorization': f'token {access_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'OpsDeck'
        })
        
        logger.info("[GitHub] Authentication headers configured successfully")
    
    def build_request_url(self, page_token: Optional[str] = None) -> str:
        """
        Build GitHub API URL with pagination.
        
        GitHub supports both Link headers and query params.
        We'll use query params for simplicity.
        """
        base_url = self.get_base_url()
        endpoint = self.subtask.endpoint
        
        # Check for placeholder organization
        if 'YOUR_ORG' in endpoint:
            logger.error(f"[GitHub] Endpoint contains placeholder 'YOUR_ORG': {endpoint}")
            raise ValueError("GitHub endpoint still contains placeholder 'YOUR_ORG'. Please configure your organization name in the task settings.")
        
        # Ensure endpoint starts with /
        if not endpoint.startswith('/'):
            endpoint = '/' + endpoint
        
        url = f"{base_url}{endpoint}"
        
        # Add pagination parameters
        if page_token:
            # page_token is the page number
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}page={page_token}&per_page={self.per_page}"
        else:
            # First page
            separator = '&' if '?' in url else '?'
            url = f"{url}{separator}per_page={self.per_page}"
        
        logger.debug(f"[GitHub] Built URL: {url}")
        return url
    
    def parse_items(self, response_data: Dict) -> List[Dict]:
        """
        GitHub APIs typically return a direct array.
        
        Some endpoints (like search) return {"items": [...], "total_count": N}
        """
        # If response is already a list, return it
        if isinstance(response_data, list):
            return response_data
        
        # If it's a search result with 'items' key
        if isinstance(response_data, dict) and 'items' in response_data:
            return response_data['items']
        
        # If it's a single object (not common for list endpoints)
        if isinstance(response_data, dict):
            return [response_data]
        
        return []
    
    def get_pagination_token(self, response_data: Dict) -> Optional[str]:
        """
        GitHub pagination uses Link headers.
        
        However, if we're using page numbers, we need to track manually.
        For simplicity, we'll use the Link header from the response.
        """
        # We'll store the last response in the connector to access headers
        # This is a bit of a hack, but works for our use case
        
        # Alternative: parse page numbers from the endpoint
        # Since GitHub returns an empty array when no more pages,
        # we can check if we got a full page
        
        if isinstance(response_data, list):
            # If we got fewer items than per_page, we're done
            if len(response_data) < self.per_page:
                return None
            
            # Otherwise, increment page number
            # We need to track current page - let's use a counter
            if not hasattr(self, '_current_page'):
                self._current_page = 1
            
            self._current_page += 1
            return str(self._current_page)
        
        # For search endpoints with items
        if isinstance(response_data, dict) and 'items' in response_data:
            items = response_data['items']
            if len(items) < self.per_page:
                return None
            
            if not hasattr(self, '_current_page'):
                self._current_page = 1
            
            self._current_page += 1
            return str(self._current_page)
        
        return None
    
    def fetch_page(self, url: str) -> 'requests.Response':
        """
        Override to store response for Link header parsing.
        """
        response = super().fetch_page(url)
        self._last_response = response
        return response


# Example auth_config for GitHub:
# {
#     "access_token": "ghp_xxxxxxxxxxxxxxxxxxxx"
# }
#
# Required token scopes:
# - read:org - for organization members and collaborators
# - repo - for repositories (public and private)
# - read:user - for user information
