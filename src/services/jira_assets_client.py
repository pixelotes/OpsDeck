"""Read-only client for the Jira Service Management Assets REST API.

Authentication is the Atlassian API connector's email + API token (HTTP Basic). Two
hosts are involved and both are fixed here, never taken from user input beyond the
validated site URL:

* the Atlassian site (``https://<name>.atlassian.net``), only to discover the Assets
  workspace id;
* ``https://api.atlassian.com/jsm/assets/workspace/<id>/v1``, for everything else.
"""
import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

ASSETS_API = 'https://api.atlassian.com/jsm/assets/workspace/{workspace}/v1'
PAGE_SIZE = 100
MAX_OBJECTS = 20000
TIMEOUT = 30


class JiraAssetsError(Exception):
    """The Assets API could not be reached or answered something unexpected."""


def validate_site_url(site_url):
    """Return the normalised site URL, or raise JiraAssetsError.

    Only ``https://<name>.atlassian.net`` is accepted, so the stored API token can
    never be sent to another host.
    """
    parsed = urlparse((site_url or '').strip())
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or not host.endswith('.atlassian.net') or parsed.username
            or parsed.password or parsed.port or parsed.path.strip('/')):
        raise JiraAssetsError('The Atlassian site URL must be https://<your-site>.atlassian.net.')
    return f'https://{host}'


class JiraAssetsClient:
    def __init__(self, site_url, email, api_token, session=None):
        if not email or not api_token:
            raise JiraAssetsError('The Atlassian connector has no email or API token.')
        self.site_url = validate_site_url(site_url)
        self.session = session or requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({'Accept': 'application/json'})
        self._workspace = None
        self._attribute_names = {}

    @classmethod
    def from_connector(cls):
        """Build a client from the Atlassian API connector's credentials."""
        from ..models.connectors import ConnectorTask
        task = ConnectorTask.query.filter_by(service='atlassian').first()
        creds = task.credentials if task and task.auth_config else None
        if not creds:
            raise JiraAssetsError('Configure the Atlassian API connector (Settings > API Connectors) first.')
        return cls(creds.get('site_url'), creds.get('email'), creds.get('api_token'))

    # ------------------------------------------------------------------ #

    def _request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise JiraAssetsError(f'Could not reach Jira Assets: {exc.__class__.__name__}') from exc
        if response.status_code in (401, 403):
            raise JiraAssetsError(f'Jira Assets refused the request ({response.status_code}): '
                                  'check the connector email, API token and Assets permissions.')
        if response.status_code >= 400:
            raise JiraAssetsError(f'Jira Assets answered {response.status_code} for {urlparse(url).path}.')
        try:
            return response.json()
        except ValueError as exc:
            raise JiraAssetsError('Jira Assets answered something that is not JSON.') from exc

    @property
    def workspace_id(self):
        if self._workspace is None:
            data = self._request('GET', f'{self.site_url}/rest/servicedeskapi/assets/workspace')
            values = data.get('values') or []
            if not values or not values[0].get('workspaceId'):
                raise JiraAssetsError('This Atlassian site has no Assets workspace.')
            self._workspace = values[0]['workspaceId']
        return self._workspace

    @property
    def api(self):
        return ASSETS_API.format(workspace=self.workspace_id)

    def attribute_names(self, object_type_id):
        """{attribute id: attribute name} for an object type."""
        key = str(object_type_id)
        if key not in self._attribute_names:
            data = self._request('GET', f'{self.api}/objecttype/{key}/attributes')
            self._attribute_names[key] = {str(a['id']): a.get('name') for a in data or []}
        return self._attribute_names[key]

    def search(self, aql):
        """All objects matching ``aql``, normalised (see :func:`normalise_object`)."""
        objects, start, seen_pages = [], 0, set()
        while True:
            data = self._request('POST', f'{self.api}/object/aql',
                                 params={'startAt': start, 'maxResults': PAGE_SIZE, 'includeAttributes': 'true'},
                                 json={'qlQuery': aql})
            values = data.get('values') or []
            names = {str(a['id']): a.get('name') for a in data.get('objectTypeAttributes') or []}
            page_ids = tuple(str(v.get('id')) for v in values)
            if page_ids and page_ids in seen_pages:
                raise JiraAssetsError('Jira Assets returned the same page twice; stopping instead of looping.')
            seen_pages.add(page_ids)
            for value in values:
                type_id = (value.get('objectType') or {}).get('id')
                type_names = names or (self.attribute_names(type_id) if type_id else {})
                objects.append(normalise_object(value, type_names))
            if len(objects) > MAX_OBJECTS:
                raise JiraAssetsError(f'The query matches more than {MAX_OBJECTS} objects; narrow it down.')
            start += len(values)
            total = data.get('total')
            if not values or data.get('isLast') or (total is not None and start >= total):
                return objects


def normalise_object(value, attribute_names):
    """Reduce an Assets object to {'id', 'key', 'label', 'type_id', 'type', 'attrs'}.

    ``attrs`` maps attribute name -> list of values. Plain values use their raw value
    (dates as ISO strings); references and users use their display value (the
    referenced object's label).
    """
    attrs = {}
    for attribute in value.get('attributes') or []:
        attr_id = str(attribute.get('objectTypeAttributeId') or attribute.get('attributeId') or attribute.get('id'))
        name = (attribute.get('objectTypeAttribute') or {}).get('name') or attribute_names.get(attr_id) \
            or attribute.get('name')
        if not name:
            continue
        values = []
        for v in attribute.get('objectAttributeValues') or attribute.get('values') or []:
            raw = v.get('value')
            shown = v.get('displayValue')
            if v.get('referencedObject') or raw is None:
                raw = shown or (v.get('referencedObject') or {}).get('label')
            if raw not in (None, ''):
                values.append(str(raw))
        attrs[name] = values
    object_type = value.get('objectType') or {}
    return {
        'id': str(value.get('id')),
        'key': value.get('objectKey'),
        'label': value.get('label'),
        'type_id': str(object_type.get('id') or ''),
        'type': object_type.get('name'),
        'attrs': attrs,
    }


def type_clause(object_type):
    """AQL selecting an object type given as an id (260) or a name (Laptop)."""
    value = (object_type or '').strip()
    if value.isdigit():
        return f'objectTypeId = {value}'
    return 'objectType = "{}"'.format(value.replace('\\', '\\\\').replace('"', '\\"'))
