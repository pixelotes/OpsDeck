"""The offboarding checklist is derived from what the person holds."""
from datetime import date

from src.extensions import db
from src.models import BusinessService, License, Risk, Subscription, User
from src.models.credentials import Credential
from src.models.onboarding import OffboardingProcess, ProcessTemplate
from src.services.offboarding_service import build_offboarding_checklist


def _people():
    leaver = User(name='Leaver', email='leaver@test.com', role='user')
    successor = User(name='Successor', email='next@test.com', role='user')
    db.session.add_all([leaver, successor])
    db.session.flush()
    return leaver, successor


def _holdings(leaver):
    db.session.add_all([
        License(name='Slack Pro', user_id=leaver.id),
        Subscription(name='Figma', user_id=leaver.id, subscription_type='SaaS', cost=10,
                     renewal_date=date.today(), renewal_period_type='Monthly'),
        Risk(risk_description='Laptop leaves the building with customer data on it and nobody notices for a week',
             owner_id=leaver.id, inherent_impact=3, inherent_likelihood=3,
             residual_impact=3, residual_likelihood=3),
        BusinessService(name='Payroll', owner_id=leaver.id),
        Credential(name='Root key', type='SSH Key', owner_id=leaver.id, owner_type='User'),
        ProcessTemplate(name='Exit Interview', process_type='offboarding', is_active=True),
        ProcessTemplate(name='Old task', process_type='offboarding', is_active=False),
        ProcessTemplate(name='Welcome mail', process_type='onboarding', is_active=True),
    ])
    db.session.flush()


def _process(leaver):
    process = OffboardingProcess(user_id=leaver.id, departure_date=date.today())
    db.session.add(process)
    db.session.flush()
    return process


def test_checklist_covers_everything_the_person_holds(app, init_database):
    with app.app_context():
        leaver, _ = _people()
        _holdings(leaver)
        checklist = build_offboarding_checklist(_process(leaver), leaver)
        db.session.commit()

        by_type = {item.item_type: item.description for item in checklist.items}
        assert by_type['License'] == '🔑 Revoke License: Slack Pro'
        assert by_type['Subscription'] == '🔄 Cancel/Transfer Subscription: Figma'
        assert by_type['Risk'].startswith('⚠️ TRANSFER RISK: Laptop leaves')
        assert by_type['Risk'].endswith('..')                     # cut at the preview length
        assert by_type['ServiceOwnership'] == '⚠️ TRANSFER SERVICE: Payroll (User is Owner)'
        assert by_type['Credential'] == '🔑 REASSIGN CREDENTIAL: Root key (SSH Key)'
        assert by_type['StaticTask'] == 'Exit Interview'          # active, offboarding only
        assert not any(item.is_completed for item in checklist.items)
        assert checklist.transferred_to is None


def test_naming_a_successor_transfers_ownership_and_ticks_those_items(app, init_database):
    with app.app_context():
        leaver, successor = _people()
        _holdings(leaver)
        checklist = build_offboarding_checklist(_process(leaver), leaver, transfer_to=successor)
        db.session.commit()

        done = {item.item_type for item in checklist.items if item.is_completed}
        assert done == {'Risk', 'ServiceOwnership', 'Credential'}
        assert Risk.query.one().owner_id == successor.id
        assert BusinessService.query.one().owner_id == successor.id
        assert Credential.query.one().owner_id == successor.id
        # Things that are picked up or revoked, not owned, stay open.
        assert not next(i for i in checklist.items if i.item_type == 'License').is_completed


def test_route_uses_the_service(auth_client, app, init_database):
    with app.app_context():
        leaver, successor = _people()
        _holdings(leaver)
        db.session.commit()
        leaver_id, successor_id = leaver.id, successor.id
    response = auth_client.post('/onboarding/offboarding/new', data={
        'user_id': leaver_id, 'departure_date': date.today().isoformat(), 'transfer_to_id': successor_id,
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'auto-transferred to Successor' in response.data
    with app.app_context():
        process = OffboardingProcess.query.filter_by(user_id=leaver_id).one()
        assert len(process.items) == 6
