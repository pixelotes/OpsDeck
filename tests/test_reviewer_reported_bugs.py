"""Regression tests for bugs reported while the documentation was rewritten.

Each test pins one fix: disposal edit/create forms, credential service targets,
credential transfer without an owner, the audits defense-pack error path and
write-gated buttons, adding risks to an empty assessment, the health dashboard's
incident filters and the personal dashboard's credential list.
"""
import io
from contextlib import contextmanager
from datetime import timedelta

from flask import template_rendered

from src.extensions import db
from src.models import (Asset, DisposalRecord, Supplier, User, Module, Permission,
                        AccessLevel, Attachment, Risk, RiskAssessment)
from src.models.audits import ComplianceAudit
from src.models.credentials import Credential, CredentialSecret
from src.models.security import SecurityIncident
from src.models.services import BusinessService
from src.utils.timezone_helper import now, today


@contextmanager
def captured_templates(app):
    recorded = []

    def record(sender, template, context, **extra):
        recorded.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield recorded
    finally:
        template_rendered.disconnect(record, app)


def _context_for(recorded, name):
    return next(ctx for tpl, ctx in recorded if tpl.name == name)


def _user(name, email, role='user'):
    u = User(name=name, email=email, role=role)
    u.set_password('password')
    db.session.add(u)
    db.session.flush()
    return u


def _admin_id():
    return User.query.filter_by(email='admin@test.com').first().id


# --- disposal -------------------------------------------------------------------

def _disposed_asset_with_partner():
    partner = Supplier(name='Green Recycling')
    other = Supplier(name='Other Vendor')
    asset = Asset(name='Old Laptop', status='Disposed', is_archived=True)
    db.session.add_all([partner, other, asset])
    db.session.flush()
    record = DisposalRecord(asset_id=asset.id, disposal_date=today(),
                            disposal_method='Recycled', disposal_partner_id=partner.id)
    db.session.add(record)
    db.session.commit()
    return record.id, partner.id


def test_disposal_edit_form_lists_suppliers_with_partner_selected(auth_client, app):
    with app.app_context():
        record_id, partner_id = _disposed_asset_with_partner()

    resp = auth_client.get(f'/disposal/{record_id}/edit')
    assert resp.status_code == 200
    assert f'<option value="{partner_id}" selected>Green Recycling</option>'.encode() in resp.data
    assert b'Other Vendor' in resp.data


def test_disposal_edit_with_certificate_attaches_file_and_keeps_partner(auth_client, app):
    with app.app_context():
        record_id, partner_id = _disposed_asset_with_partner()

    resp = auth_client.post(f'/disposal/{record_id}/edit', data={
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Recycled',
        'disposal_partner_id': str(partner_id),
        'notes': 'cert added',
        'reason': 'Received certificate',
        'certificate': (io.BytesIO(b'%PDF-1.4'), 'certificate.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/disposal/{record_id}')

    with app.app_context():
        record = db.session.get(DisposalRecord, record_id)
        assert record.disposal_partner_id == partner_id
        atts = Attachment.query.filter_by(linkable_type='DisposalRecord',
                                          linkable_id=record_id).all()
        assert [a.filename for a in atts] == ['certificate.pdf']


def test_record_disposal_form_defaults_date_to_today(auth_client, app):
    with app.app_context():
        asset = Asset(name='Laptop', status='In Use')
        db.session.add(asset)
        db.session.commit()
        asset_id = asset.id

    resp = auth_client.get(f'/disposal/record?asset_id={asset_id}')
    assert resp.status_code == 200
    assert f'value="{today().strftime("%Y-%m-%d")}"'.encode() in resp.data
    assert b"value=\"now\"" not in resp.data


def test_record_disposal_with_certificate(auth_client, app):
    with app.app_context():
        asset = Asset(name='Laptop', status='In Use')
        db.session.add(asset)
        db.session.commit()
        asset_id = asset.id

    resp = auth_client.post(f'/disposal/record?asset_id={asset_id}', data={
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Destroyed',
        'certificate': (io.BytesIO(b'%PDF-1.4'), 'destruction.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302

    with app.app_context():
        record = DisposalRecord.query.filter_by(asset_id=asset_id).one()
        assert len(record.attachments) == 1


# --- credentials ----------------------------------------------------------------

def test_credential_service_target_links_the_service(auth_client, app):
    with app.app_context():
        svc = BusinessService(name='Billing API', owner_id=_admin_id())
        db.session.add(svc)
        db.session.commit()
        svc_id, admin_id = svc.id, _admin_id()

    resp = auth_client.post('/credentials/new', data={
        'name': 'Billing key', 'type': 'API Key', 'owner_id': admin_id,
        'secret_value': 'abcd1234efgh', 'target_type': 'service', 'target_id': svc_id,
    })
    assert resp.status_code == 302

    with app.app_context():
        cred = Credential.query.filter_by(name='Billing key').one()
        assert [s.id for s in cred.services] == [svc_id]
        assert cred.service_id == svc_id
        cred_id = cred.id

    # Switching the target away unlinks the service shown in the form.
    resp = auth_client.post(f'/credentials/{cred_id}/edit', data={
        'name': 'Billing key', 'type': 'API Key', 'owner_id': admin_id,
        'target_type': '', 'target_id': '',
    })
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Credential, cred_id).services == []


def test_credential_edit_keeps_other_service_links(auth_client, app):
    with app.app_context():
        admin_id = _admin_id()
        a = BusinessService(name='A', owner_id=admin_id)
        b = BusinessService(name='B', owner_id=admin_id)
        c = BusinessService(name='C', owner_id=admin_id)
        cred = Credential(name='Shared', type='API Key', owner_id=admin_id, owner_type='User')
        cred.services = [a, b]
        db.session.add_all([a, b, c, cred])
        db.session.commit()
        cred_id, a_id, b_id, c_id = cred.id, a.id, b.id, c.id

    auth_client.post(f'/credentials/{cred_id}/edit', data={
        'name': 'Shared', 'type': 'API Key', 'owner_id': admin_id,
        'target_type': 'service', 'target_id': c_id,
    })
    with app.app_context():
        ids = {s.id for s in db.session.get(Credential, cred_id).services}
        # The form showed A (the first link); it was replaced by C, B stays.
        assert ids == {b_id, c_id}
        assert a_id not in ids


# --- onboarding: credential transfer ---------------------------------------------

def test_transfer_credential_without_new_owner_keeps_owner(auth_client, app):
    with app.app_context():
        owner = _user('Departing', 'dep@test.com')
        cred = Credential(name='Key', type='API Key', owner_id=owner.id, owner_type='User')
        db.session.add(cred)
        db.session.commit()
        cred_id, owner_id = cred.id, owner.id

    resp = auth_client.post(f'/onboarding/transfer/credential/{cred_id}',
                            data={'new_owner_id': ''}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Choose the user who should take over this credential.' in resp.data
    with app.app_context():
        assert db.session.get(Credential, cred_id).owner_id == owner_id


def test_transfer_credential_to_new_owner(auth_client, app):
    with app.app_context():
        owner = _user('Departing', 'dep@test.com')
        new = _user('Newbie', 'new@test.com')
        cred = Credential(name='Key', type='API Key', owner_id=owner.id, owner_type='User')
        db.session.add(cred)
        db.session.commit()
        cred_id, new_id = cred.id, new.id

    auth_client.post(f'/onboarding/transfer/credential/{cred_id}', data={'new_owner_id': new_id})
    with app.app_context():
        assert db.session.get(Credential, cred_id).owner_id == new_id


# --- audits ---------------------------------------------------------------------

def test_defense_pack_error_redirects_to_audit(auth_client, app, monkeypatch):
    with app.app_context():
        audit = ComplianceAudit(name='SOC 2')
        db.session.add(audit)
        db.session.commit()
        audit_id = audit.id

    def boom(_id):
        raise RuntimeError('disk full')

    monkeypatch.setattr('src.services.audit_export_service.export_audit_pack', boom)
    resp = auth_client.post(f'/security/audits/{audit_id}/export-pack')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith(f'/security/audits/{audit_id}')


def test_locked_audit_hides_unlock_from_read_only_user(client, app):
    with app.app_context():
        module = Module.query.filter_by(slug='compliance').first()
        if not module:
            module = Module(name='Compliance', slug='compliance')
            db.session.add(module)
            db.session.flush()
        user = _user('Reader', 'reader@test.com')
        db.session.add(Permission(module_id=module.id, user_id=user.id,
                                  access_level=AccessLevel.READ_ONLY))
        audit = ComplianceAudit(name='Locked audit', locked_at=now())
        db.session.add(audit)
        db.session.commit()
        audit_id = audit.id

    client.post('/login', data={'email': 'reader@test.com', 'password': 'password'})
    resp = client.get(f'/security/audits/{audit_id}')
    assert resp.status_code == 200
    assert f'/security/audits/{audit_id}/unlock'.encode() not in resp.data


def test_locked_audit_shows_unlock_to_admin(auth_client, app):
    with app.app_context():
        audit = ComplianceAudit(name='Locked audit', locked_at=now())
        db.session.add(audit)
        db.session.commit()
        audit_id = audit.id

    resp = auth_client.get(f'/security/audits/{audit_id}')
    assert f'/security/audits/{audit_id}/unlock'.encode() in resp.data


# --- risk assessments -------------------------------------------------------------

def test_add_risk_to_empty_assessment(auth_client, app):
    with app.app_context():
        risk = Risk(risk_description='Laptop theft', status='Identified',
                    inherent_impact=3, inherent_likelihood=3,
                    residual_impact=2, residual_likelihood=2, owner_id=_admin_id())
        db.session.add(risk)
        db.session.commit()
        risk_id = risk.id

    auth_client.post('/risk-assessments/new', data={'name': 'Q4', 'include_risks': 'no'})
    with app.app_context():
        assessment_id = RiskAssessment.query.filter_by(name='Q4').one().id

    page = auth_client.get(f'/risk-assessments/{assessment_id}')
    assert b'Add an open risk' in page.data

    auth_client.post(f'/risk-assessments/{assessment_id}/items/add', data={'risk_id': risk_id})
    # Adding the same risk twice is refused.
    auth_client.post(f'/risk-assessments/{assessment_id}/items/add', data={'risk_id': risk_id})

    with app.app_context():
        assessment = db.session.get(RiskAssessment, assessment_id)
        assert [i.original_risk_id for i in assessment.items] == [risk_id]
        assert assessment.total_residual_risk == 4


def test_new_assessment_label_spelling(auth_client):
    resp = auth_client.get('/risk-assessments/new')
    assert b'Snapshot All Open Risks' in resp.data
    assert b'Snaphot' not in resp.data


# --- dashboards -------------------------------------------------------------------

def test_health_dashboard_counts_contained_and_sev0_incidents(auth_client, app):
    with app.app_context():
        db.session.add_all([
            SecurityIncident(title='Ransomware', description='x', status='Contained',
                             severity='SEV-0'),
            SecurityIncident(title='Old', description='x', status='Resolved',
                             severity='SEV-0'),
        ])
        db.session.commit()

    with captured_templates(app) as recorded:
        resp = auth_client.get('/org-health')
    assert resp.status_code == 200
    ctx = _context_for(recorded, 'organizational_health.html')
    assert ctx['global_status'] == 'critical'
    titles = [i['title'] for i in ctx['critical_items'] if i['type'] == 'security']
    assert titles == ['Ransomware']


def test_my_dashboard_lists_only_my_expiring_credentials(auth_client, app):
    with app.app_context():
        admin_id = _admin_id()
        other = _user('Other', 'other@test.com')
        for name, owner_id in (('Mine', admin_id), ('Theirs', other.id)):
            cred = Credential(name=name, type='API Key', owner_id=owner_id, owner_type='User')
            db.session.add(cred)
            db.session.flush()
            secret = CredentialSecret(credential_id=cred.id, is_active=True,
                                      expires_at=now() + timedelta(days=5))
            secret.set_secret('abcdefgh1234')
            db.session.add(secret)
        db.session.commit()

    with captured_templates(app) as recorded:
        resp = auth_client.get('/my-dashboard')
    assert resp.status_code == 200
    ctx = _context_for(recorded, 'my_dashboard.html')
    titles = [t['title'] for t in ctx['prioritized_tasks'] if t['title'].startswith('Update credential')]
    assert titles == ['Update credential: Mine']
    assert ' de ' not in ctx['current_date_pretty']
