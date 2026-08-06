"""
Polymorphic compliance links between a framework control and other entities.

These tests used to take only the `app` fixture, so the database was never reset
between them and all three shared one framework. Two of them looked the framework
up before creating it and tolerated that; the first created it unconditionally and
therefore only worked while it happened to run first. Randomised ordering made it
fail. Each test now starts from a clean database via init_database and builds what
it needs outright.
"""
from src import db
from src.models import (Asset, Policy, Supplier, Framework, FrameworkControl,
                        ComplianceLink)


def _control(name='ISO 27001', control_id='A.1'):
    """A framework with one control, committed and ready to link against."""
    framework = Framework(name=name, description='InfoSec', link='http://iso.org')
    db.session.add(framework)
    db.session.commit()

    control = FrameworkControl(framework_id=framework.id, control_id=control_id,
                               name='Access Control', description='Limit access')
    db.session.add(control)
    db.session.commit()
    return control


def test_compliance_link_asset(app, init_database):
    with app.app_context():
        control = _control()

        asset = Asset(name='Server 1', status='In Use')
        db.session.add(asset)
        db.session.commit()

        db.session.add(ComplianceLink(
            framework_control_id=control.id,
            linkable_id=asset.id,
            linkable_type='Asset',
            description='Restricted access via firewall'
        ))
        db.session.commit()

        assert asset.compliance_links.count() == 1
        assert asset.compliance_links.first().description == 'Restricted access via firewall'
        assert asset.compliance_links.first().framework_control.control_id == 'A.1'


def test_compliance_link_policy(app, init_database):
    with app.app_context():
        control = _control()

        policy = Policy(title='Access Policy', category='Security')
        db.session.add(policy)
        db.session.commit()

        db.session.add(ComplianceLink(
            framework_control_id=control.id,
            linkable_id=policy.id,
            linkable_type='Policy',
            description='Defines access rules'
        ))
        db.session.commit()

        assert policy.compliance_links.count() == 1
        assert policy.compliance_links.first().description == 'Defines access rules'


def test_compliance_link_supplier(app, init_database):
    with app.app_context():
        control = _control()

        supplier = Supplier(name='Cloud Provider')
        db.session.add(supplier)
        db.session.commit()

        db.session.add(ComplianceLink(
            framework_control_id=control.id,
            linkable_id=supplier.id,
            linkable_type='Supplier',
            description='SOC 2 Type II report'
        ))
        db.session.commit()

        assert supplier.compliance_links.count() == 1
        assert supplier.compliance_links.first().description == 'SOC 2 Type II report'


def test_one_control_links_to_several_entity_types(app, init_database):
    """The point of the polymorphic table: one control, different kinds of evidence."""
    with app.app_context():
        control = _control()

        asset = Asset(name='Server 1', status='In Use')
        supplier = Supplier(name='Cloud Provider')
        db.session.add_all([asset, supplier])
        db.session.commit()

        db.session.add_all([
            ComplianceLink(framework_control_id=control.id, linkable_id=asset.id,
                           linkable_type='Asset', description='Firewall'),
            ComplianceLink(framework_control_id=control.id, linkable_id=supplier.id,
                           linkable_type='Supplier', description='SOC 2'),
        ])
        db.session.commit()

        assert asset.compliance_links.count() == 1
        assert supplier.compliance_links.count() == 1
        assert ComplianceLink.query.filter_by(framework_control_id=control.id).count() == 2
