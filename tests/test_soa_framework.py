"""
Tests for SOA (Statement of Applicability) at the Framework level.
Covers: model fields, SOA update endpoint, dashboard integration, and audit snapshot inheritance.
"""
from src.models import db
from src.models.security import Framework, FrameworkControl
from src.models.audits import ComplianceAudit
from src.models.auth import User


def test_framework_control_soa_defaults(auth_client, app):
    """
    Test 1: New FrameworkControl defaults to is_applicable=True, soa_justification=None.
    """
    with app.app_context():
        fw = Framework(name='SOA Default Test', is_custom=True, is_active=True)
        ctrl = FrameworkControl(control_id='S.1', name='Default Control')
        fw.framework_controls.append(ctrl)
        db.session.add(fw)
        db.session.commit()

        assert ctrl.is_applicable is True
        assert ctrl.soa_justification is None


def test_update_control_soa_mark_not_applicable(auth_client, app):
    """
    Test 2: POST /frameworks/control/<id>/soa marks a control as not applicable with justification.
    """
    with app.app_context():
        fw = Framework(name='SOA Update Test', is_custom=True, is_active=True)
        ctrl = FrameworkControl(control_id='S.2', name='Control to Exclude')
        fw.framework_controls.append(ctrl)
        db.session.add(fw)
        db.session.commit()
        ctrl_id = ctrl.id

    # Mark as NOT applicable (checkbox unchecked = not sent)
    response = auth_client.post(f'/frameworks/control/{ctrl_id}/soa', data={
        'soa_justification': 'Not relevant to our business'
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        ctrl = db.session.get(FrameworkControl, ctrl_id)
        assert ctrl.is_applicable is False
        assert ctrl.soa_justification == 'Not relevant to our business'


def test_update_control_soa_mark_applicable_again(auth_client, app):
    """
    Test 3: Re-marking a control as applicable clears the justification.
    """
    with app.app_context():
        fw = Framework(name='SOA Revert Test', is_custom=True, is_active=True)
        ctrl = FrameworkControl(
            control_id='S.3', name='Control to Revert',
            is_applicable=False, soa_justification='Was excluded'
        )
        fw.framework_controls.append(ctrl)
        db.session.add(fw)
        db.session.commit()
        ctrl_id = ctrl.id

    # Mark as applicable (checkbox sent as 'on')
    response = auth_client.post(f'/frameworks/control/{ctrl_id}/soa', data={
        'is_applicable': 'on',
        'soa_justification': 'This should be cleared'
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        ctrl = db.session.get(FrameworkControl, ctrl_id)
        assert ctrl.is_applicable is True
        assert ctrl.soa_justification is None


def test_dashboard_counts_na_separately(auth_client, app):
    """
    Test 4: ComplianceEvaluator.get_framework_status() counts N/A controls
    in 'not_applicable' stat, NOT in 'non_compliant' or 'uncovered'.
    """
    with app.app_context():
        from src.services.compliance_service import get_compliance_evaluator

        fw = Framework(name='SOA Dashboard Test', is_custom=True, is_active=True)
        ctrl_applicable = FrameworkControl(
            control_id='D.1', name='Applicable Control',
            is_applicable=True
        )
        ctrl_na = FrameworkControl(
            control_id='D.2', name='NA Control',
            is_applicable=False, soa_justification='Not in scope'
        )
        fw.framework_controls.extend([ctrl_applicable, ctrl_na])
        db.session.add(fw)
        db.session.commit()

        evaluator = get_compliance_evaluator()
        result = evaluator.get_framework_status(fw.id)

        assert result['stats']['total'] == 2
        assert result['stats']['not_applicable'] == 1
        assert result['stats']['non_compliant'] == 0
        # The applicable control with no rules/links should be 'uncovered'
        assert result['stats']['uncovered'] == 1

        # Verify control data
        na_ctrl = next(c for c in result['controls'] if c['control_id'] == 'D.2')
        assert na_ctrl['status'] == 'not_applicable'
        assert na_ctrl['coverage_type'] == 'not_applicable'
        assert na_ctrl['soa_justification'] == 'Not in scope'


def test_audit_snapshot_inherits_framework_soa(auth_client, app):
    """
    Test 5: create_snapshot() inherits is_applicable and soa_justification
    from FrameworkControl, and sets status='Not Applicable' for N/A controls.
    """
    with app.app_context():
        fw = Framework(name='SOA Inherit Test', is_custom=True, is_active=True)
        ctrl_ok = FrameworkControl(
            control_id='I.1', name='Applicable Control',
            is_applicable=True
        )
        ctrl_na = FrameworkControl(
            control_id='I.2', name='Excluded Control',
            is_applicable=False, soa_justification='Too small to apply'
        )
        fw.framework_controls.extend([ctrl_ok, ctrl_na])
        db.session.add(fw)
        db.session.commit()
        fw_id = fw.id

        lead = User.query.first()
        audit = ComplianceAudit.create_snapshot(
            framework_id=fw_id,
            name='SOA Inherit Audit',
            auditor_contact_id=None,
            internal_lead_id=lead.id,
            copy_links=False
        )

        items = {i.control_code: i for i in audit.audit_items}

        # Applicable control
        assert items['I.1'].is_applicable is True
        assert items['I.1'].justification is None
        assert items['I.1'].status == 'Pending'

        # N/A control
        assert items['I.2'].is_applicable is False
        assert items['I.2'].justification == 'Too small to apply'
        assert items['I.2'].status == 'Not Applicable'


def test_audit_clone_preserves_audit_soa_override(auth_client, app):
    """
    Test 6: clone() preserves the audit-level SOA override, NOT the framework SOA.
    This ensures that if an auditor changed applicability in a previous audit,
    the clone respects that decision.
    """
    with app.app_context():
        # Framework: control is applicable
        fw = Framework(name='SOA Clone Test', is_custom=True, is_active=True)
        ctrl = FrameworkControl(
            control_id='CL.1', name='Clone Control',
            is_applicable=True
        )
        fw.framework_controls.append(ctrl)
        db.session.add(fw)
        db.session.commit()
        fw_id = fw.id

        lead = User.query.first()

        # Create first audit — then override SOA at audit level
        audit1 = ComplianceAudit.create_snapshot(
            framework_id=fw_id,
            name='First Audit',
            auditor_contact_id=None,
            internal_lead_id=lead.id
        )
        item = audit1.audit_items.first()
        item.is_applicable = False
        item.justification = 'Auditor override: not relevant this cycle'
        item.status = 'Not Applicable'
        db.session.commit()
        audit1_id = audit1.id

        # Clone — should preserve the audit-level override
        from datetime import date
        audit2 = ComplianceAudit.clone(
            source_id=audit1_id,
            new_owner_id=lead.id,
            target_date=date(2027, 1, 1)
        )

        cloned_item = audit2.audit_items.first()
        assert cloned_item.is_applicable is False
        assert cloned_item.justification == 'Auditor override: not relevant this cycle'
        assert cloned_item.status == 'Not Applicable'
