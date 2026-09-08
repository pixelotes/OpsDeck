"""The Organizational Health figures, block by block.

The page had one test that rendered it. These pin each block's arithmetic and, above
all, that risk severity follows the configured matrix and appetite instead of the 5×5
red corner the view used to hard-code.
"""
from datetime import timedelta

import pytest

from src.extensions import db
from src.models import User
from src.models.security import Risk, SecurityIncident
from src.services import health_dashboard_service as svc
from src.utils.timezone_helper import today


def _risk(name, impact, likelihood, status='Open', treatment='Mitigate', **extra):
    return Risk(risk_description=name, status=status, treatment_strategy=treatment,
                inherent_impact=impact, inherent_likelihood=likelihood,
                residual_impact=impact, residual_likelihood=likelihood, **extra)


# --- pure arithmetic ---------------------------------------------------------------

@pytest.mark.parametrize('critical, high, expected', [
    (0, 0, 100),
    (1, 1, 80),        # 100 - 15 - 5 (a critical counts in `high` too, as the page always did)
    (2, 5, 45),
    (10, 20, 0),       # floored at zero
])
def test_health_score(critical, high, expected):
    assert svc.health_score(critical, high) == expected


@pytest.mark.parametrize('critical, high, incidents, expected', [
    (0, 0, 0, 'operational'),
    (0, 2, 0, 'operational'),
    (0, 3, 0, 'degraded'),
    (1, 0, 0, 'critical'),
    (0, 0, 1, 'critical'),
])
def test_global_status(critical, high, incidents, expected):
    assert svc.global_status(critical, high, incidents) == expected


def test_compliance_tasks_orders_due_before_upcoming():
    critical = [{'type': 'security', 'severity': 'critical', 'title': 'Expired', 'description': 'x', 'link': '/a'}]
    expirations = {
        'finance': [{'name': 'Card', 'days': 45, 'meta': 'Visa', 'link': '/b'}],
        'identity': [{'name': 'Key', 'type': 'API Key', 'days': 3, 'link': '/c'}],
        'certificates': [], 'legal': [{'name': 'Sub', 'cost': 12.5, 'days': 80, 'link': '/d'}],
    }
    tasks = svc.compliance_tasks(critical, expirations)
    assert [t['title'] for t in tasks] == ['Expired', 'Key', 'Card', 'Sub']
    assert [t['severity'] for t in tasks] == ['critical', 'warning', 'info', 'info']
    assert tasks[3]['meta'] == '€12.50'


# --- risk posture follows the configured matrix -------------------------------------

def test_risk_posture_counts_open_non_accepted_risks(app, init_database):
    with app.app_context():
        db.session.add_all([
            _risk('red', 5, 5),                                   # Critical
            _risk('amber', 4, 4),                                 # High (64%)
            _risk('closed red', 5, 5, status='Closed'),           # ignored
            _risk('accepted red', 5, 5, treatment='Accept'),      # ignored
            _risk('green', 1, 1),                                 # Low
        ])
        db.session.commit()
        posture = svc.risk_posture()
    assert posture['critical_risks'] == 1
    assert posture['high_risks'] == 2          # High + Critical, as before
    assert posture['health_score'] == 100 - 15 - 2 * 5


def test_risk_posture_uses_the_configured_appetite(auth_client, app, init_database):
    """Tighten the appetite through the settings form and the same risk turns critical."""
    with app.app_context():
        db.session.add(_risk('amber', 4, 3))    # 12/25 = 48%: High on the default appetite
        db.session.commit()
        assert svc.risk_posture()['critical_risks'] == 0

    auth_client.post('/settings/organization/settings', data={
        'risk_appetite_medium_from': '10', 'risk_appetite_high_from': '20',
        'risk_appetite_critical_from': '40',
    }, follow_redirects=True)

    with app.app_context():
        assert svc.risk_posture()['critical_risks'] == 1


def test_count_risks_by_level_is_what_my_dashboard_uses(app, init_database):
    with app.app_context():
        owner = User(name='Owner', email='owner@test.com', role='user')
        db.session.add(owner)
        db.session.flush()
        db.session.add_all([_risk('a', 5, 5, owner_id=owner.id), _risk('b', 2, 2, owner_id=owner.id)])
        db.session.commit()
        mine = Risk.query.filter_by(owner_id=owner.id).all()
        assert svc.count_risks_by_level(mine)['Critical'] == 1


def test_active_incidents(app, init_database):
    with app.app_context():
        db.session.add_all([
            SecurityIncident(title='open', description='x', status='Open', severity='SEV-1'),
            SecurityIncident(title='closed', description='x', status='Closed', severity='SEV-1'),
        ])
        db.session.commit()
        assert svc.active_incident_count() == 1
        with app.test_request_context():
            items = svc.critical_action_items()
    assert [i['title'] for i in items] == ['open']


def test_expiration_horizon_groups_and_sorts(app, init_database):
    from src.models import License
    with app.app_context():
        db.session.add_all([
            License(name='soon', expiry_date=today() + timedelta(days=10)),
            License(name='later', expiry_date=today() + timedelta(days=60)),
            License(name='far', expiry_date=today() + timedelta(days=200)),
        ])
        db.session.commit()
        with app.test_request_context():
            expirations, subscriptions = svc.expiration_horizon(days=90)
    assert [i['name'] for i in expirations['legal']] == ['soon', 'later']
    assert subscriptions == []


def test_page_still_renders(auth_client):
    response = auth_client.get('/org-health')
    assert response.status_code == 200
    assert b'organizational' in response.data.lower() or b'health' in response.data.lower()
