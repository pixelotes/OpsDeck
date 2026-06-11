"""Regression tests for offboarding transfers.

- Service ownership transfer must mark its ProcessItem complete. The item is
  created with item_type 'ServiceOwnership'; the route used to filter 'Service'
  so the owner changed but the checklist item stayed open.
- ProxyFix is applied only when TRUST_PROXY is set.
"""
import os
from datetime import date
from src.models import db, User
from src.models.services import BusinessService
from src.models.onboarding import OffboardingProcess, ProcessItem


def _user(name, email):
    u = User(name=name, email=email, role='user')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    return u


def test_service_transfer_marks_offboarding_item(auth_client, app):
    with app.app_context():
        owner = _user('Departing', 'dep@test.com')
        new_owner = _user('Newbie', 'new@test.com')
        svc = BusinessService(name='Billing API', owner_id=owner.id)
        db.session.add(svc)
        proc = OffboardingProcess(user_id=owner.id, departure_date=date(2026, 7, 1))
        db.session.add(proc)
        db.session.flush()
        item = ProcessItem(offboarding_process_id=proc.id, description='TRANSFER SERVICE',
                           item_type='ServiceOwnership', linked_object_id=svc.id, is_completed=False)
        db.session.add(item)
        db.session.commit()
        svc_id, item_id, new_id = svc.id, item.id, new_owner.id

    auth_client.post(f'/onboarding/transfer/service/{svc_id}',
                     data={'new_owner_id': new_id}, follow_redirects=True)

    with app.app_context():
        assert db.session.get(BusinessService, svc_id).owner_id == new_id
        assert db.session.get(ProcessItem, item_id).is_completed is True


def test_proxyfix_applied_only_when_trusted():
    from werkzeug.middleware.proxy_fix import ProxyFix
    from sqlalchemy.pool import StaticPool
    from src import create_app
    cfg = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}},
        'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False, 'SECRET_KEY': 'k', 'MFA_ENABLED': False,
    }
    prev = os.environ.get('TRUST_PROXY')
    try:
        os.environ['TRUST_PROXY'] = '1'
        assert isinstance(create_app(test_config=cfg).wsgi_app, ProxyFix)
        os.environ['TRUST_PROXY'] = '0'
        assert not isinstance(create_app(test_config=cfg).wsgi_app, ProxyFix)
    finally:
        if prev is None:
            os.environ.pop('TRUST_PROXY', None)
        else:
            os.environ['TRUST_PROXY'] = prev
