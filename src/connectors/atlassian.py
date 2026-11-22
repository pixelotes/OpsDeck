import os
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .base import BaseConnector

ALLOWED_HOSTS_ENV = 'ATLASSIAN_ALLOWED_HOSTS'


def _allowed_extra_hosts() -> set:
    """Hosts allowed besides *.atlassian.net, from ATLASSIAN_ALLOWED_HOSTS (comma separated)."""
    raw = os.environ.get(ALLOWED_HOSTS_ENV, '')
    return {h.strip().lower().rstrip('.') for h in raw.split(',') if h.strip()}


def validate_site_url(site_url: str) -> str:
    """
    Return the normalised site URL (scheme://host[:port], no path) or raise ValueError.

    The site URL receives the API token as HTTP Basic auth, so it must be an
    https URL on an Atlassian Cloud host (*.atlassian.net) or on a host listed
    in ATLASSIAN_ALLOWED_HOSTS. Anything else (http, internal addresses, other
    domains, embedded credentials) is refused.
    """
    try:
        parts = urlsplit((site_url or '').strip())
        host = (parts.hostname or '').lower().rstrip('.')
        port = parts.port
    except ValueError:
        raise ValueError('Site URL is not a valid URL') from None
    if parts.scheme != 'https':
        raise ValueError('Site URL must use https')
    if not host or parts.username or parts.password:
        raise ValueError('Site URL must be a plain https://<site>.atlassian.net address')
    if parts.query or parts.fragment or parts.path.strip('/'):
        raise ValueError('Site URL must not include a path, e.g. https://your-company.atlassian.net')
    if not (host.endswith('.atlassian.net') or host in _allowed_extra_hosts()):
        raise ValueError(
            'Site URL must be an Atlassian Cloud address (*.atlassian.net)'
            f' or a host listed in {ALLOWED_HOSTS_ENV}')
    netloc = f'{host}:{port}' if port and port != 443 else host
    return urlunsplit(('https', netloc, '', '', ''))


def _with_params(url: str, **params) -> str:
    """Set query parameters on a URL, replacing any existing value."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: str(v) for k, v in params.items()})
    return urlunsplit(parts._replace(query=urlencode(query)))


class AtlassianConnector(BaseConnector):
    """
    Connector for Atlassian Cloud APIs (Jira, Confluence).

    Pagination:
    - Jira list endpoints (``/rest/api/3/users``, ``/users/search``) return a bare
      array with no total: request ``startAt``/``maxResults`` and continue while
      a page comes back full.
    - Jira paged endpoints (``/rest/api/3/project/search``) return
      ``startAt``/``maxResults``/``total``/``isLast`` with ``values``.
    - Confluence (``/wiki/rest/api/space``) returns ``_links.next``, a path
      relative to ``_links.base`` (or the site), which is followed as is.

    Authentication: HTTP Basic with ``email`` and ``api_token`` from the task
    credentials, sent only to the validated ``site_url`` host.
    """

    page_size = 100

    def __init__(self, task, subtask):
        super().__init__(task, subtask)
        self._start_at = 0

    def get_base_url(self) -> str:
        if not self.auth:
            raise ValueError("No auth_config found for Atlassian connector")
        site_url = self.auth.get('site_url')
        if not site_url:
            raise ValueError("No 'site_url' found in auth_config")
        # Re-validated on every run: credentials stored before validation existed
        # must not send the token to an arbitrary host either.
        return validate_site_url(site_url)

    def authenticate(self) -> None:
        if not self.auth:
            raise ValueError("No auth_config found for Atlassian connector")
        email = self.auth.get('email')
        api_token = self.auth.get('api_token')
        if not email or not api_token:
            raise ValueError("Atlassian auth requires 'email' and 'api_token' in auth_config")
        self.get_base_url()  # refuse before any credential is attached to the session
        self.session.auth = (email, api_token)
        self.session.headers.update({'Accept': 'application/json'})

    def parse_items(self, response_data) -> List[Dict]:
        if isinstance(response_data, list):
            return response_data
        for key in ('values', 'results', 'items'):
            if key in response_data:
                return response_data[key]
        return []

    def _is_confluence(self) -> bool:
        return self.subtask.endpoint.startswith('/wiki/')

    def get_pagination_token(self, response_data) -> Optional[str]:
        # Jira list endpoints: bare array, no total. A full page means "maybe more".
        if isinstance(response_data, list):
            if len(response_data) < self.page_size:
                return None
            return str(self._start_at + len(response_data))

        # Confluence: follow _links.next, relative to _links.base or the site.
        links = response_data.get('_links') or {}
        if self._is_confluence():
            next_link = links.get('next')
            if not next_link:
                return None
            site = self.get_base_url()
            if next_link.startswith(('http://', 'https://')):
                url = next_link
            elif next_link.startswith('/wiki/'):
                url = site + next_link
            else:
                # v1 links are relative to _links.base, e.g. https://x.atlassian.net/wiki
                base = links.get('base') or f'{site}/wiki'
                url = f"{base.rstrip('/')}/{next_link.lstrip('/')}"
            return self._same_site(url)

        # Jira paged endpoints.
        if response_data.get('isLast') is True:
            return None
        values = self.parse_items(response_data)
        if not values:
            return None
        start_at = response_data.get('startAt', self._start_at)
        next_start = start_at + len(values)
        total = response_data.get('total')
        if total is not None and next_start >= total:
            return None
        if total is None and 'isLast' not in response_data and len(values) < self.page_size:
            return None
        return str(next_start)

    def _same_site(self, url: str) -> str:
        """Refuse a next link that would send the credentials to another host."""
        site = urlsplit(self.get_base_url())
        target = urlsplit(url)
        if (target.scheme != 'https' or target.username or target.password
                or (target.hostname or '').rstrip('.') != site.hostname
                or (target.port or 443) != (site.port or 443)):
            raise ValueError(f'Refusing to follow pagination link to another host: {target.hostname}')
        return url

    def build_request_url(self, page_token: Optional[str] = None) -> str:
        if page_token and page_token.startswith('https://'):
            return self._same_site(page_token)

        url = f"{self.get_base_url()}{self.subtask.endpoint}"
        if self._is_confluence():
            return _with_params(url, limit=self.page_size)

        self._start_at = int(page_token) if page_token else 0
        return _with_params(url, startAt=self._start_at, maxResults=self.page_size)
