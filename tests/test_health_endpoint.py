"""/health is what Kubernetes probes and the container HEALTHCHECK call, over plain HTTP.

Everything else redirects to https in production; if this did too, a probe would follow
the redirect to an https port nobody serves inside the pod and the pod would never be
ready.
"""
from sqlalchemy.pool import StaticPool

from src import create_app


def test_health_is_served_over_plain_http_in_production(monkeypatch):
    for var in ('OAUTHLIB_INSECURE_TRANSPORT', 'FLASK_ENV', 'FLASK_DEBUG'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('SECRET_KEY', 'k' * 48)
    app = create_app(test_config={
        'TESTING': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}},
        'RATELIMIT_ENABLED': False, 'MFA_ENABLED': False,
    })
    client = app.test_client()
    # The rest of the site still forces https...
    assert client.get('/login').status_code == 302
    # ...but the probe endpoint answers where it is asked.
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'healthy'}
