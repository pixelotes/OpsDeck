"""Every view declared as JSON must refuse in JSON — derived from the url_map.

tests/test_api_authorization.py checks the same property against a table written by
hand, which covers what someone remembered to add. This one walks app.url_map, keeps the
views marked with @json_endpoint/@api_endpoint, and asserts the contract on each. A new
JSON endpoint is therefore covered the moment it is declared, and an endpoint that
breaks the contract fails the build instead of waiting for someone to notice.

The contract, for an unauthenticated request:

* 401, never a 302 — a fetch() caller follows the redirect and parses the login page as
  if it were the payload, so the failure is silent. This is the bug this whole mechanism
  exists to make unrepeatable.
* a JSON body, never HTML.

Public endpoints are excluded from the list the guard itself uses, not from a copy: the
health check and the internal CLI routes answer JSON and are deliberately reachable
without a session.
"""
import pytest

from src import PUBLIC_ENDPOINTS
from src.utils.json_api import view_is_json


def _placeholder(converter):
    """A value that satisfies a URL converter, so a rule can be turned into a path."""
    name = type(converter).__name__
    if 'Integer' in name or 'Float' in name:
        return 1
    if 'UUID' in name:
        return '0f4d3a1e-0000-4000-8000-000000000000'
    if 'Path' in name:
        return 'x/y'
    return 'x'


def _targets(app):
    """(method, path) for every declared JSON view that should require a session."""
    adapter = app.url_map.bind('localhost')
    targets = []

    for rule in app.url_map.iter_rules():
        view = app.view_functions.get(rule.endpoint)
        if view is None or not view_is_json(view):
            continue
        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        # flask-smorest's /api/v1 authenticates by bearer token and is exercised by its
        # own tests; this contract is about the session-authenticated internal layer.
        if rule.rule.startswith('/api/v1'):
            continue

        methods = rule.methods - {'HEAD', 'OPTIONS'}
        if not methods:
            continue
        method = 'GET' if 'GET' in methods else sorted(methods)[0]

        values = {arg: _placeholder(rule._converters[arg]) for arg in rule.arguments}
        targets.append((method, adapter.build(rule.endpoint, values, method=method)))

    return targets


def test_the_url_map_actually_contains_declared_json_views(app):
    """Guard against the sweep below passing because it found nothing to check.

    Deleting the decorator everywhere, or renaming the attribute it stamps, would
    otherwise leave an empty target list and a green test.
    """
    targets = _targets(app)

    assert targets, (
        'No declared JSON views in the url_map, so the sweep below asserts nothing. '
        'Either @json_endpoint is no longer applied or view_is_json no longer sees it.'
    )

    # The point of declaring membership is to reach the endpoints the path check could
    # not. If every declared view still lives under /api/, this suite would pass just as
    # well with the old path-based guard and proves nothing about the new one.
    off_convention = [path for _, path in targets if '/api/' not in path]
    assert off_convention, (
        'Every declared JSON view still has /api/ in its path. The declaration is only '
        'load-bearing once endpoints that do not follow that naming are marked.'
    )


def test_every_declared_json_endpoint_refuses_in_json(client, app, init_database):
    """One test over every marked route, reporting all offenders rather than the first."""
    offenders = []

    for method, path in _targets(app):
        response = client.open(path, method=method)

        if response.status_code == 302:
            offenders.append(f'{method} {path} -> 302 to {response.headers.get("Location")}')
        elif response.status_code != 401:
            offenders.append(f'{method} {path} -> {response.status_code}, expected 401')
        elif not response.is_json:
            offenders.append(f'{method} {path} -> 401 but {response.content_type}')

    assert not offenders, (
        f'{len(offenders)} declared JSON endpoint(s) do not refuse in JSON:\n'
        + '\n'.join(f'  {offender}' for offender in offenders)
    )


@pytest.mark.parametrize('method,path', [
    ('GET', '/compliance/json/services'),
    ('POST', '/hr/hiring/move'),
    ('GET', '/security/activities/get-objects-by-type'),
])
def test_declaration_is_what_counts_not_the_path(client, app, init_database, method, path):
    """The endpoints from the measurement that motivated this: JSON, no /api/ in the path.

    Listed explicitly because the sweep above only sees them once they are declared, and
    their whole point is that the path-based check never did.

    Each is requested with its own method: on a method mismatch Flask leaves
    request.endpoint as None, so the declaration cannot be consulted and the guard falls
    back to the path. That is fine — a 405 for an unauthenticated caller is not the
    failure this protects against — but it does mean the method has to be right here.
    """
    response = client.open(path, method=method)

    assert response.status_code != 302, (
        f'{path} redirected to {response.headers.get("Location")}; a fetch() caller '
        'would parse the login page as the payload.'
    )
    assert not response.content_type.startswith('text/html'), (
        f'{path} answered with {response.content_type}'
    )
