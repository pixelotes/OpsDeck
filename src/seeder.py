import random
from datetime import date, timedelta, datetime
from faker import Faker
from .models import (
    db, Supplier, Contact, User, Location, PaymentMethod, Tag, Budget, Purchase,
    Asset, Peripheral, Service, CostHistory, Risk, SecurityIncident,
    PostIncidentReview, IncidentTimelineEvent, MaintenanceLog, DisposalRecord,
    BCDRPlan, BCDRTestLog, Course, CourseAssignment, Group, Policy, PolicyVersion, Opportunity
)
from . import create_app

fake = Faker()

def seed_data():
    """Seeds the database with a comprehensive set of demo data."""
    app = create_app()
    with app.app_context():
        if Supplier.query.first():
            print("Database already contains data. Aborting seed.")
            return

        print("Seeding database with extensive demo data...")

        # 1. Create Core Entities
        print("Creating core entities...")
        suppliers = [
            Supplier(name='Adobe', email='sales@adobe.com', phone='800-833-6687', compliance_status='Compliant', gdpr_dpa_signed=date(2023, 5, 15)),
            Supplier(name='Microsoft', email='support@microsoft.com', phone='800-642-7676', compliance_status='Compliant', gdpr_dpa_signed=date(2023, 6, 1)),
            Supplier(name='Dell Technologies', email='sales@dell.com', phone='877-275-3355', compliance_status='Pending'),
            Supplier(name='Slack (Salesforce)', email='feedback@slack.com', phone='415-579-9122', compliance_status='Compliant', gdpr_dpa_signed=date(2024, 1, 10)),
            Supplier(name='Atlassian', email='sales@atlassian.com', phone='800-804-5281', compliance_status='Non-Compliant'),
            Supplier(name='Zoom', email='info@zoom.us', phone='888-799-9666'),
            Supplier(name='Apple', email='business@apple.com', phone='800-854-3680'),
            Supplier(name='Logitech', email='support@logi.com', phone='646-454-3200'),
            Supplier(name='Amazon Web Services', email='aws-sales@amazon.com', compliance_status='Compliant'),
            Supplier(name='Namecheap', email='support@namecheap.com'),
            Supplier(name='Figma', email='sales@figma.com'),
            Supplier(name='Herman Miller', email='info@hermanmiller.com'),
            Supplier(name='Okta', email='info@okta.com'),
            Supplier(name='Palo Alto Networks', email='sales@paloaltonetworks.com')
        ]
        db.session.add_all(suppliers)
        db.session.commit()

        locations = [
            Location(name='Headquarters - NYC'), 
            Location(name='London Office'), 
            Location(name='San Francisco Hub'), 
            Location(name='Tokyo Office'),
            Location(name='Sydney Office'),
            Location(name='Remote (Home Office)')
        ]
        payment_methods = [
            PaymentMethod(name='Corp AMEX - 1005', method_type='Credit Card', details='Ends in 1005'),
            PaymentMethod(name='IT Dept Visa - 4554', method_type='Credit Card', details='Ends in 4554'),
            PaymentMethod(name='Bank Transfer (ACH)', method_type='Bank Transfer')
        ]
        tags = [Tag(name='SaaS'), Tag(name='Hardware'), Tag(name='Marketing'), Tag(name='Development'), Tag(name='Office Supply'), Tag(name='Cloud Infrastructure'), Tag(name='Design'), Tag(name='Security')]
        
        db.session.add_all(locations)
        db.session.add_all(payment_methods)
        db.session.add_all(tags)
        db.session.commit()

        # 2. Create People, Groups
        print("Creating people and groups...")
        users = [
            User(name='Alice Johnson', email='alice.j@example.com', department='Engineering', job_title='Lead Developer'),
            User(name='Bob Williams', email='bob.w@example.com', department='Marketing', job_title='Marketing Director'),
            User(name='Charlie Brown', email='charlie.b@example.com', department='Engineering', job_title='Frontend Developer'),
            User(name='Diana Prince', email='diana.p@example.com', department='Design', job_title='UX/UI Designer'),
            User(name='Ethan Hunt', email='ethan.h@example.com', department='Sales', job_title='Account Executive'),
            User(name='Fiona Glenanne', email='fiona.g@example.com', department='Engineering', job_title='Backend Developer'),
            User(name='George Costanza', email='george.c@example.com', department='Sales', job_title='Sales Manager'),
            User(name='Heidi Klum', email='heidi.k@example.com', department='Design', job_title='Lead Designer'),
        ]
        db.session.add_all(users)
        db.session.commit()

        group_engineering = Group(name="Engineering", description="All members of the engineering team.")
        group_engineering.users.extend([users[0], users[2], users[5]])
        
        group_sales = Group(name="Sales", description="The global sales team.")
        group_sales.users.extend([users[4], users[6]])

        group_design = Group(name="Design", description="The product and brand design team.")
        group_design.users.extend([users[3], users[7]])
        
        db.session.add_all([group_engineering, group_sales, group_design])
        
        db.session.commit()

        # 3. Create Budgets and Purchases (without cost)
        print("Creating budgets and purchases...")
        budgets = [
            Budget(name='IT Hardware 2025', category='IT', amount=75000, currency='EUR', period='Yearly'),
            Budget(name='Software & SaaS 2025', category='Software', amount=150000, currency='EUR', period='Yearly'),
        ]
        db.session.add_all(budgets)

        purchase1 = Purchase(description='Annual Adobe Creative Cloud Subscription', purchase_date=date(2024, 11, 1), supplier=suppliers[0], payment_method=payment_methods[0], budget=budgets[1])
        purchase2 = Purchase(description='New Developer Laptops Q4', purchase_date=date(2024, 10, 15), supplier=suppliers[2], payment_method=payment_methods[1], budget=budgets[0])
        purchase3 = Purchase(description='Jira & Confluence Cloud Annual', purchase_date=date(2025, 1, 5), supplier=suppliers[4], payment_method=payment_methods[2], budget=budgets[1])
        purchase4 = Purchase(description='New Macbooks for Design Team', purchase_date=date(2025, 2, 20), supplier=suppliers[6], payment_method=payment_methods[0], budget=budgets[0])
        purchase5 = Purchase(description='Firewall Upgrade for NYC Office', purchase_date=date(2025, 4, 1), supplier=suppliers[13], budget=budgets[0])
        
        db.session.add_all([purchase1, purchase2, purchase3, purchase4, purchase5])
        db.session.commit()
        
        # 4. Create Assets and Peripherals (with cost)
        print("Creating assets and peripherals...")
        assets = [
            Asset(name='DEV-LT-001', brand='Dell', model='XPS 15', serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[0], location=locations[0], supplier=suppliers[2], cost=2500, currency='EUR', warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DEV-LT-002', brand='Dell', model='XPS 15', serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[2], location=locations[0], supplier=suppliers[2], cost=2500, currency='EUR', warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DSN-LT-001', brand='Apple', model='MacBook Pro 16"', serial_number=fake.uuid4(), status='In Use', purchase=purchase4, user=users[3], location=locations[1], supplier=suppliers[6], cost=3200, currency='EUR', warranty_length=24, purchase_date=purchase4.purchase_date),
            Asset(name='DSN-LT-002', brand='Apple', model='MacBook Pro 16"', serial_number=fake.uuid4(), status='In Use', purchase=purchase4, user=users[7], location=locations[1], supplier=suppliers[6], cost=3200, currency='EUR', warranty_length=24, purchase_date=purchase4.purchase_date),
            Asset(name='SALES-LT-001', brand='Microsoft', model='Surface Laptop 5', serial_number=fake.uuid4(), status='In Storage', location=locations[0], supplier=suppliers[1], cost=1800, currency='USD', warranty_length=24, purchase_date=date(2024, 5, 5)),
            Asset(name='EOL-LT-001', brand='Apple', model='MacBook Pro 13"', serial_number=fake.uuid4(), status='Awaiting Disposal', location=locations[0], cost=1500, currency='USD', purchase_date=date(2021, 5, 5)),
            Asset(name='FW-NYC-01', brand='Palo Alto', model='PA-440', serial_number=fake.uuid4(), status='In Use', purchase=purchase5, location=locations[0], supplier=suppliers[13], cost=4000, currency='USD', warranty_length=60, purchase_date=purchase5.purchase_date)
        ]
        db.session.add_all(assets)
        db.session.commit()

        peripherals = [
            Peripheral(name='Keyboard-001', type='Keyboard', brand='Logitech', cost=100, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[7]),
            Peripheral(name='Mouse-001', type='Mouse', brand='Logitech', cost=80, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[7]),
            Peripheral(name='Monitor-001', type='Monitor', brand='Dell', cost=450, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[2]),
            Peripheral(name='Keyboard-003', type='Keyboard', brand='Apple', cost=150, currency='EUR', asset=assets[2], user=users[3]),
            Peripheral(name='Mouse-003', type='Mouse', brand='Apple', cost=90, currency='EUR', asset=assets[2], user=users[3]),
        ]
        db.session.add_all(peripherals)
        db.session.commit()
        
        # 5. Create Services and Opportunities
        print("Creating services and opportunities...")
        services_data = [
            {'name': 'Adobe Creative Cloud', 'type': 'Software', 'renewal': date(2025, 11, 1), 'cost': 15000, 'supplier': suppliers[0]},
            {'name': 'Microsoft 365 E5', 'type': 'SaaS', 'renewal': date(2026, 1, 1), 'cost': 35000, 'supplier': suppliers[1]},
            {'name': 'Okta Identity Provider', 'type': 'Security', 'renewal': date(2026, 6, 1), 'cost': 12000, 'supplier': suppliers[12]},
        ]
        for data in services_data:
            service = Service(name=data['name'], service_type=data['type'], renewal_date=data['renewal'], cost=data['cost'], supplier=data['supplier'], renewal_period_type='yearly')
            db.session.add(service)
        
        opportunities = [
            Opportunity(name="Company-wide SSO solution", status="Evaluating", potential_value=20000, supplier=suppliers[12]),
            Opportunity(name="Next-gen firewall refresh", status="Negotiating", potential_value=50000, supplier=suppliers[13], estimated_close_date=date(2025, 12, 1))
        ]
        db.session.add_all(opportunities)
        db.session.commit()
        
        # 6. Create Policies and Courses
        print("Creating policies and courses...")
        policy = Policy(title="Acceptable Use Policy", category="IT Security", description="Defines the acceptable use of company IT resources.")
        policy_v1 = PolicyVersion(
            policy=policy,
            version_number="1.0",
            content="## 1. Introduction\nThis policy outlines the acceptable use of company equipment and network resources...",
            status="Active",
            effective_date=date(2024, 1, 1)
        )
        policy_v1.groups_to_acknowledge.append(group_engineering)
        db.session.add_all([policy, policy_v1])

        course = Course(title="Cybersecurity Awareness Training 2025", description="Annual training for all employees on security best practices.", link="http://example.com/training")
        db.session.add(course)
        db.session.commit()

        assignment = CourseAssignment(course_id=course.id, user_id=users[1].id, due_date=date.today() + timedelta(days=30))
        db.session.add(assignment)
        
        # 7. Create Compliance & Governance Entities
        print("Creating compliance and governance entities...")
        risks = [
            Risk(risk_description="Unauthorized access to cloud infrastructure due to weak passwords", status="Assessed", likelihood="Medium", impact="High", risk_owner="Alice Johnson", iso_27001_control="A.5.15"),
            Risk(risk_description="Data loss due to hardware failure of primary database server", status="In Treatment", likelihood="Low", impact="Significant", mitigation_plan="Implement daily backups to a secondary location.", iso_27001_control="A.12.3.1"),
            Risk(risk_description="Malware infection on end-user devices", status="Identified", likelihood="High", impact="Moderate", iso_27001_control="A.8.7"),
            Risk(risk_description="Third-party supplier fails to meet security obligations", status="Assessed", likelihood="Medium", impact="High", iso_27001_control="A.15.2.1"),
            Risk(risk_description="Sensitive data leakage via email", status="Identified", likelihood="Medium", impact="Significant", iso_27001_control="A.8.2.3"),
            Risk(risk_description="Lack of regular access control reviews", status="In Treatment", likelihood="Medium", impact="Moderate", iso_27001_control="A.5.18"),
        ]
        db.session.add_all(risks)

        incident = SecurityIncident(title="Phishing Email Reported by Bob Williams", description="User Bob Williams reported a suspicious email with a link to a fake login page.", severity="SEV-2", impact="Minor", owner=users[0], reported_by=users[1])
        incident.affected_users.append(users[1])
        db.session.add(incident)
        
        bcdr_plan = BCDRPlan(name="Primary Database Failure Plan", description="Steps to restore the main application database from backups.")
        bcdr_plan.services.append(Service.query.first())
        db.session.add(bcdr_plan)
        db.session.commit()
        
        bcdr_test = BCDRTestLog(plan_id=bcdr_plan.id, status="Passed", notes="Successfully restored backup to a staging environment in under 30 minutes.")
        db.session.add(bcdr_test)
        
        # 8. Create Lifecycle Events
        print("Creating lifecycle events (maintenance, disposal)...")
        maintenance_log = MaintenanceLog(event_type="Repair", description="Replaced faulty RAM module.", status="Completed", asset=assets[0], assigned_to=users[0])
        db.session.add(maintenance_log)
        
        erasure_log = MaintenanceLog(event_type="Data Erasure", description="NIST 800-88 3-pass wipe performed.", status="Completed", asset=assets[5], assigned_to=users[0])
        db.session.add(erasure_log)

        disposal = DisposalRecord(disposal_method="Recycled", disposal_partner="eWaste Inc.", asset=assets[5])
        db.session.add(disposal)

        db.session.commit()
        print("Database seeding complete!")