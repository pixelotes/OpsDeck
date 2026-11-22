"""Atlassian connector: pagination, site URL validation and credential handling."""
from urllib.parse import parse_qs, urlsplit

import pytest

from src import db
from src.connectors.atlassian import AtlassianConnector, validate_site_url
from src.models.connectors import ConnectorSubtask, ConnectorTask

SITE = 'https://acme.atlassian.net'
CREDS = {'site_url': SITE, 'email': 'admin@acme.com', 'api_token': 'tok'}


class FakeTask:
    service = 'atlassian'

    def __init__(self, creds=None):
        self.credentials = dict(CREDS if creds is None else creds)


class FakeSubtask:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.name = 'Test'
        self.pagination_type = 'offset'


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def connector_for(endpoint, responder, creds=None):
    """Connector whose session.get answers with responder(url) and records the URLs."""
    conn = AtlassianConnector(FakeTask(creds), FakeSubtask(endpoint))
    conn.calls = []

    def get(url, timeout=None):
        conn.calls.append(url)
        return FakeResponse(responder(url))

    conn.session.get = get
    return conn


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --- Jira users: bare array, no total -------------------------------------------------

def jira_users(total):
    users = [{'accountId': f'u{i}'} for i in range(total)]

    def responder(url):
        q = query(url)
        start, size = int(q['startAt']), int(q['maxResults'])
        return users[start:start + size]
    return responder


@pytest.mark.parametrize('endpoint', ['/rest/api/3/users', '/rest/api/3/users/search'])
def test_jira_users_are_fetched_past_the_first_page(endpoint):
    conn = connector_for(endpoint, jira_users(250))
    result = conn.fetch_all_pages()
    assert result['total_count'] == 250
    assert len({u['accountId'] for u in result['items']}) == 250
    assert [query(u)['startAt'] for u in conn.calls] == ['0', '100', '200']


def test_jira_users_exact_multiple_of_page_size_stops_on_empty_page():
    conn = connector_for('/rest/api/3/users', jira_users(200))
    assert conn.fetch_all_pages()['total_count'] == 200
    assert len(conn.calls) == 3


# --- Jira projects: startAt/maxResults/total/isLast ------------------------------------

def test_jira_projects_follow_total():
    projects = [{'key': f'P{i}'} for i in range(130)]

    def responder(url):
        q = query(url)
        start, size = int(q['startAt']), min(int(q['maxResults']), 50)  # server caps at 50
        page = projects[start:start + size]
        return {'startAt': start, 'maxResults': size, 'total': len(projects),
                'isLast': start + size >= len(projects), 'values': page}

    conn = connector_for('/rest/api/3/project/search', responder)
    result = conn.fetch_all_pages()
    assert [p['key'] for p in result['items']] == [p['key'] for p in projects]
    assert [query(u)['startAt'] for u in conn.calls] == ['0', '50', '100']


# --- Confluence spaces: _links.next ----------------------------------------------------

def test_confluence_spaces_follow_next_links_without_duplicates():
    spaces = [{'key': f'S{i}'} for i in range(60)]

    def responder(url):
        start = int(query(url).get('start', 0))
        page = spaces[start:start + 25]
        links = {'base': f'{SITE}/wiki', 'context': '/wiki'}
        if start + 25 < len(spaces):
            links['next'] = f'/rest/api/space?next=true&limit=25&start={start + 25}'
        return {'results': page, 'start': start, 'limit': 25, 'size': len(page), '_links': links}

    conn = connector_for('/wiki/rest/api/space', responder)
    result = conn.fetch_all_pages()
    assert [s['key'] for s in result['items']] == [s['key'] for s in spaces]
    assert len(conn.calls) == 3
    assert conn.calls[1] == f'{SITE}/wiki/rest/api/space?next=true&limit=25&start=25'


def test_confluence_v2_cursor_links_are_relative_to_the_site():
    def responder(url):
        if 'cursor' in url:
            return {'results': [{'key': 'B'}], '_links': {'base': f'{SITE}/wiki'}}
        return {'results': [{'key': 'A'}], '_links': {'next': '/wiki/api/v2/spaces?cursor=abc'}}

    conn = connector_for('/wiki/api/v2/spaces', responder)
    assert [s['key'] for s in conn.fetch_all_pages()['items']] == ['A', 'B']
    assert conn.calls[1] == f'{SITE}/wiki/api/v2/spaces?cursor=abc'


def test_next_link_to_another_host_is_refused():
    def responder(url):
        return {'results': [], '_links': {'next': 'https://evil.example.com/steal'}}

    conn = connector_for('/wiki/rest/api/space', responder)
    with pytest.raises(ValueError, match='another host'):
        conn.fetch_all_pages()
    assert len(conn.calls) == 1


# --- Base loop guards ----------------------------------------------------------------

def test_a_repeated_url_fails_the_run_instead_of_looping():
    def responder(url):
        return {'results': [{'key': 'X'}], '_links': {'next': '/rest/api/space?start=0'}}

    conn = connector_for('/wiki/rest/api/space', responder)
    with pytest.raises(RuntimeError, match='repeated'):
        conn.fetch_all_pages()
    assert len(conn.calls) == 2


def test_hitting_the_page_limit_fails_instead_of_truncating():
    conn = connector_for('/rest/api/3/users', jira_users(1000))
    conn.max_pages = 3
    with pytest.raises(RuntimeError, match='partial report'):
        conn.fetch_all_pages()


def test_get_requests_send_no_content_type():
    conn = connector_for('/rest/api/3/users', jira_users(1))
    conn.fetch_all_pages()
    assert 'Content-Type' not in conn.session.headers
    assert conn.session.headers['Accept'] == 'application/json'
    assert conn.session.auth == ('admin@acme.com', 'tok')


def test_a_stored_unsafe_site_url_never_receives_the_token():
    conn = connector_for('/rest/api/3/users', jira_users(1),
                         creds={**CREDS, 'site_url': 'http://169.254.169.254'})
    with pytest.raises(ValueError):
        conn.fetch_all_pages()
    assert conn.calls == []
    assert conn.session.auth is None


# --- Site URL validation -------------------------------------------------------------

@pytest.mark.parametrize('url, expected', [
    ('https://acme.atlassian.net', SITE),
    ('https://ACME.atlassian.net/', SITE),
    ('  https://acme.atlassian.net  ', SITE),
])
def test_valid_site_urls(url, expected):
    assert validate_site_url(url) == expected


@pytest.mark.parametrize('url', [
    'http://acme.atlassian.net',
    'https://acme.atlassian.net.evil.com',
    'https://evil.com/acme.atlassian.net',
    'https://atlassian.net.evil.com',
    'https://localhost',
    'https://127.0.0.1',
    'https://169.254.169.254',
    'https://user:pw@acme.atlassian.net',
    'https://evil.com#@acme.atlassian.net',
    'https://acme.atlassian.net/wiki',
    'ftp://acme.atlassian.net',
    'acme.atlassian.net',
    '',
])
def test_invalid_site_urls(url):
    with pytest.raises(ValueError):
        validate_site_url(url)


def test_allow_list_admits_extra_hosts(monkeypatch):
    with pytest.raises(ValueError):
        validate_site_url('https://jira.acme.com')
    monkeypatch.setenv('ATLASSIAN_ALLOWED_HOSTS', 'jira.acme.com, other.example.org')
    assert validate_site_url('https://jira.acme.com') == 'https://jira.acme.com'
    with pytest.raises(ValueError):
        validate_site_url('http://jira.acme.com')


# --- Credentials form ----------------------------------------------------------------

def make_atlassian_task(auth_config=None):
    task = ConnectorTask(name='atlassian sync', service='atlassian', enabled=False,
                         polling_interval=7200)
    if auth_config:
        task.set_credentials(auth_config)
    db.session.add_all([task, ConnectorSubtask(task=task, name='Users', endpoint='/rest/api/3/users')])
    db.session.commit()
    return task.id


def post_creds(auth_client, task_id, **data):
    return auth_client.post(f'/settings/connectors/task/{task_id}/configure-credentials', data=data)


def stored(app, task_id):
    with app.app_context():
        return db.session.get(ConnectorTask, task_id).credentials


def test_unsafe_site_url_is_rejected(auth_client, app):
    with app.app_context():
        task_id = make_atlassian_task()
    post_creds(auth_client, task_id, site_url='http://10.0.0.5', email='a@acme.com', api_token='t')
    with app.app_context():
        assert db.session.get(ConnectorTask, task_id).auth_config is None


def test_site_url_is_normalised_on_save(auth_client, app):
    with app.app_context():
        task_id = make_atlassian_task()
    post_creds(auth_client, task_id, site_url='https://ACME.atlassian.net/', email='a@acme.com', api_token='t')
    assert stored(app, task_id) == {'site_url': SITE, 'email': 'a@acme.com', 'api_token': 't'}


def test_changing_the_site_requires_the_token_again(auth_client, app):
    with app.app_context():
        task_id = make_atlassian_task(CREDS)
    post_creds(auth_client, task_id, site_url='https://other.atlassian.net',
               email=CREDS['email'], api_token='')
    assert stored(app, task_id) == CREDS

    post_creds(auth_client, task_id, site_url='https://other.atlassian.net',
               email=CREDS['email'], api_token='new')
    assert stored(app, task_id)['site_url'] == 'https://other.atlassian.net'
    assert stored(app, task_id)['api_token'] == 'new'


def test_changing_the_email_requires_the_token_again(auth_client, app):
    with app.app_context():
        task_id = make_atlassian_task(CREDS)
    post_creds(auth_client, task_id, site_url=SITE, email='someone@else.com', api_token='')
    assert stored(app, task_id) == CREDS


def test_same_site_and_email_keep_the_stored_token(auth_client, app):
    with app.app_context():
        task_id = make_atlassian_task(CREDS)
    post_creds(auth_client, task_id, site_url=SITE + '/', email='ADMIN@acme.com', api_token='')
    assert stored(app, task_id) == {**CREDS, 'email': 'ADMIN@acme.com'}
