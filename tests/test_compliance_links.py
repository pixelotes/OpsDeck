import pytest
from src.models import Asset, Policy, Supplier, Framework, FrameworkControl, ComplianceLink
from src import db

def test_compliance_link_asset(app):
    with app.app_context():
        # Setup
        fw = Framework(name='ISO 27001', description='InfoSec', link='http://iso.org')
        db.session.add(fw)
        db.session.commit()
        
        control = FrameworkControl(framework_id=fw.id, control_id='A.1', name='Access Control', description='Limit access')
        db.session.add(control)
        db.session.commit()
        
        asset = Asset(name='Server 1', status='In Use')
        db.session.add(asset)
        db.session.commit()
        
        # Link
        link = ComplianceLink(
            framework_control_id=control.id,
            linkable_id=asset.id,
            linkable_type='Asset',
            description='Restricted access via firewall'
        )
        db.session.add(link)
        db.session.commit()
        
        # Verify
        assert asset.compliance_links.count() == 1
        assert asset.compliance_links.first().description == 'Restricted access via firewall'
        assert asset.compliance_links.first().framework_control.control_id == 'A.1'

def test_compliance_link_policy(app):
    with app.app_context():
        # Setup
        fw = Framework.query.filter_by(name='ISO 27001').first()
        if not fw:
            fw = Framework(name='ISO 27001', description='InfoSec', link='http://iso.org')
            db.session.add(fw)
            db.session.commit()
            
        control = FrameworkControl.query.filter_by(control_id='A.1').first()
        if not control:
            control = FrameworkControl(framework_id=fw.id, control_id='A.1', name='Access Control', description='Limit access')
            db.session.add(control)
            db.session.commit()
            
        policy = Policy(title='Access Policy', category='Security')
        db.session.add(policy)
        db.session.commit()
        
        # Link
        link = ComplianceLink(
            framework_control_id=control.id,
            linkable_id=policy.id,
            linkable_type='Policy',
            description='Defines access rules'
        )
        db.session.add(link)
        db.session.commit()
        
        # Verify
        assert policy.compliance_links.count() == 1
        assert policy.compliance_links.first().description == 'Defines access rules'

def test_compliance_link_supplier(app):
    with app.app_context():
        # Setup
        fw = Framework.query.filter_by(name='ISO 27001').first()
        if not fw:
            fw = Framework(name='ISO 27001', description='InfoSec', link='http://iso.org')
            db.session.add(fw)
            db.session.commit()
            
        control = FrameworkControl.query.filter_by(control_id='A.1').first()
        if not control:
            control = FrameworkControl(framework_id=fw.id, control_id='A.1', name='Access Control', description='Limit access')
            db.session.add(control)
            db.session.commit()
            
        supplier = Supplier(name='Cloud Provider')
        db.session.add(supplier)
        db.session.commit()
        
        # Link
        link = ComplianceLink(
            framework_control_id=control.id,
            linkable_id=supplier.id,
            linkable_type='Supplier',
            description='SOC 2 Type II report'
        )
        db.session.add(link)
        db.session.commit()
        
        # Verify
        assert supplier.compliance_links.count() == 1
        assert supplier.compliance_links.first().description == 'SOC 2 Type II report'
