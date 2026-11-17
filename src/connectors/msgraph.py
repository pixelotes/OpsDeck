"""Shared Microsoft Graph access (app-only, client credentials).

Used by the Entra ID user sync and by the Microsoft 365 API connector so both obtain
tokens and call Graph the same way, and can share one app registration: the
AZURE_OAUTH_* settings that also drive "Sign in with Microsoft".
"""
import time

import requests

GRAPH = 'https://graph.microsoft.com/v1.0'
GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
REQUEST_TIMEOUT = 30
# Refresh this many seconds before the token's stated expiry.
TOKEN_EXPIRY_MARGIN = 120


class GraphError(Exception):
    """A Graph or token request failed. Messages never include secrets or response bodies."""


def token_url(tenant_id):
    return f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'


def entra_app_credentials(config):
    """(tenant_id, client_id, client_secret) from the AZURE_OAUTH_* settings, or None.

    Only a single-tenant configuration with a client secret qualifies.
    """
    from src import azure_oauth_configured
    if not (azure_oauth_configured(config) and config.get('AZURE_OAUTH_CLIENT_SECRET')):
        return None
    return (config['AZURE_OAUTH_TENANT_ID'].strip(), config['AZURE_OAUTH_CLIENT_ID'],
            config['AZURE_OAUTH_CLIENT_SECRET'])


def fetch_app_token(http, tenant_id, client_id, client_secret, error_cls=GraphError):
    """Client-credentials token for Graph. Returns (access_token, expires_in_seconds)."""
    try:
        resp = http.post(
            token_url(tenant_id),
            data={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': GRAPH_SCOPE,
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise error_cls(f'Could not reach the Microsoft token endpoint ({type(exc).__name__}).') from exc
    if not resp.ok:
        raise error_cls(f'Could not obtain a Graph token (HTTP {resp.status_code}).')
    data = resp.json()
    token = data.get('access_token')
    if not token:
        raise error_cls('The Microsoft token endpoint returned no access token.')
    return token, int(data.get('expires_in') or 3600)


class GraphClient:
    """Minimal read-only Graph client with a cached, auto-refreshed app token."""

    #: Exception raised on failures; subclasses may narrow it to their own error type.
    error_cls = GraphError

    def __init__(self, tenant_id, client_id, client_secret, session=None):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()
        self._token = None
        self._token_expires_at = 0.0

    def _get_token(self):
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        token, expires_in = fetch_app_token(self.http, self.tenant_id, self.client_id,
                                            self.client_secret, self.error_cls)
        self._token = token
        self._token_expires_at = time.monotonic() + max(expires_in - TOKEN_EXPIRY_MARGIN, 60)
        return token

    def get(self, url, params=None, allow_404=False):
        if not url.startswith('https://'):
            url = GRAPH + url
        try:
            resp = self.http.get(url, params=params, timeout=REQUEST_TIMEOUT,
                                 headers={'Authorization': f'Bearer {self._get_token()}'})
        except requests.RequestException as exc:
            raise self.error_cls(f'Could not reach Microsoft Graph ({type(exc).__name__}).') from exc
        if allow_404 and resp.status_code == 404:
            return None
        if not resp.ok:
            raise self.error_cls(f'Microsoft Graph error {resp.status_code} for {url.split("?")[0]}')
        return resp.json()

    def paginate(self, url, params=None):
        """Yield every item of a collection, following @odata.nextLink."""
        while url:
            page = self.get(url, params=params)
            params = None  # nextLink already carries the query
            yield from page.get('value', [])
            url = page.get('@odata.nextLink')
