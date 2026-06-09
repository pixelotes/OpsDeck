from datetime import date, timedelta, datetime
from faker import Faker
from .models import (
    db, Supplier, User, Location, PaymentMethod, Tag, Budget, Purchase,
    Asset, Peripheral, Subscription, Risk, SecurityIncident,
    MaintenanceLog, DisposalRecord, AssetAssignment,
    BCDRPlan, BCDRTestLog, Course, CourseAssignment, Group, Policy, PolicyVersion, Opportunity,
    Documentation, Link, Software, License, Framework, FrameworkControl, ComplianceLink, ComplianceRule,
    BusinessService, ServiceComponent, ComplianceAudit, Contact, RiskAssessment,
    EmailTemplate, NotificationEvent, Change, Request,
    SecurityActivity, ActivityExecution,
    OnboardingPack, PackItem, ProcessTemplate,
    OnboardingProcess, OffboardingProcess, ProcessItem, PackCommunication
)
from .models.assets import Brand, AssetModel
from .models.hiring import HiringStage, Candidate
from . import create_app
from src.utils.timezone_helper import now, today


fake = Faker()

def seed_data(app=None):
    """Seeds the database with a comprehensive set of demo data."""
    if app is None:
        app = create_app()
    with app.app_context():
        if Supplier.query.first():
            print("Database already contains data. Aborting seed.")
            return

        print("Seeding database with extensive demo data...")

        # Seed Hiring Stages First
        print("Creating hiring stages...")
        hiring_stages = [
            HiringStage(name='Applied', order=1),
            HiringStage(name='Screening', order=2),
            HiringStage(name='Interview', order=3),
            HiringStage(name='Offer', order=4),
            HiringStage(name='Hired', order=5, is_hired_stage=True),
            HiringStage(name='Rejected', order=6)
        ]
        db.session.add_all(hiring_stages)
        db.session.commit()

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
            Supplier(name='Amazon Web Subscriptions', email='aws-sales@amazon.com', compliance_status='Compliant'),
            Supplier(name='Namecheap', email='support@namecheap.com'),
            Supplier(name='Figma', email='sales@figma.com'),
            Supplier(name='Herman Miller', email='info@hermanmiller.com'),
            Supplier(name='Okta', email='info@okta.com'),
            Supplier(name='Palo Alto Networks', email='sales@paloaltonetworks.com')
        ]
        db.session.add_all(suppliers)
        db.session.commit()
        
        # Add Contacts
        print("Creating contacts...")
        contacts = [
            Contact(name='John Adobe', email='john@adobe.com', phone='555-0101', role='Account Manager', supplier=suppliers[0]),
            Contact(name='Jane Microsoft', email='jane@microsoft.com', phone='555-0102', role='Sales Rep', supplier=suppliers[1]),
            Contact(name='Bob Dell', email='bob@dell.com', phone='555-0103', role='Support Lead', supplier=suppliers[2]),
            Contact(name='Alice Slack', email='alice@slack.com', phone='555-0104', role='CSM', supplier=suppliers[3])
        ]
        db.session.add_all(contacts)
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
        
        # Activity Category Tags (for Security Activities)
        activity_category_tags = [
            Tag(name='Identity'),
            Tag(name='Awareness'),
            Tag(name='Vulnerability Mgmt'),
            Tag(name='Network'),
            Tag(name='BCDR'),
            Tag(name='GRC')
        ]
        tags.extend(activity_category_tags)
        
        db.session.add_all(locations)
        db.session.add_all(payment_methods)
        db.session.add_all(tags)
        db.session.commit()

        # 2. Create People, Groups
        print("Creating people and groups...")
        users = [
            # Executive / Leadership
            User(name='Alice Johnson', email='alice.j@example.com', department='Engineering', job_title='VP of Engineering'),
            User(name='Bob Williams', email='bob.w@example.com', department='Sales', job_title='VP of Sales'),
            
            # Management
            User(name='Charlie Brown', email='charlie.b@example.com', department='Engineering', job_title='Engineering Manager'),
            User(name='George Costanza', email='george.c@example.com', department='Sales', job_title='Sales Manager'),
            
            # Individual Contributors - Engineering
            User(name='Fiona Glenanne', email='fiona.g@example.com', department='Engineering', job_title='Senior Backend Developer'),
            User(name='Diana Prince', email='diana.p@example.com', department='Design', job_title='Senior Product Designer'),
            User(name='Heidi Klum', email='heidi.k@example.com', department='Design', job_title='UX Researcher'),
            
            # Individual Contributors - Sales
            User(name='Ethan Hunt', email='ethan.h@example.com', department='Sales', job_title='Account Executive'),
            
            # New Hires (for Onboarding/Buddy scenarios)
            User(name='Ian Malcolm', email='ian.m@example.com', department='Engineering', job_title='Junior DevOps Engineer'),
            User(name='Julia Roberts', email='julia.r@example.com', department='Sales', job_title='Sales  Development Rep')
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
        # Ensure all related objects are in the session to avoid autoflush warnings
        db.session.add_all(users)
        db.session.add_all(locations)
        db.session.add_all(suppliers)

        # Brands + Models
        brand_map = {name: Brand(name=name) for name in ('Dell', 'Apple', 'Microsoft', 'Palo Alto', 'Logitech')}
        db.session.add_all(brand_map.values())
        db.session.commit()
        model_map = {}
        for brand_name, model_name in [
            ('Dell', 'XPS 15'),
            ('Apple', 'MacBook Pro 16"'),
            ('Apple', 'MacBook Pro 13"'),
            ('Microsoft', 'Surface Laptop 5'),
            ('Palo Alto', 'PA-440'),
        ]:
            m = AssetModel(name=model_name, brand=brand_map[brand_name])
            model_map[(brand_name, model_name)] = m
        db.session.add_all(model_map.values())
        db.session.commit()

        assets = [
            Asset(name='DEV-LT-001', brand=brand_map['Dell'], model=model_map[('Dell', 'XPS 15')], serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[0], location=locations[0], supplier=suppliers[2], cost=2500, currency='EUR', warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DEV-LT-002', brand=brand_map['Dell'], model=model_map[('Dell', 'XPS 15')], serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[2], location=locations[0], supplier=suppliers[2], cost=2500, currency='EUR', warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DSN-LT-001', brand=brand_map['Apple'], model=model_map[('Apple', 'MacBook Pro 16"')], serial_number=fake.uuid4(), status='In Use', purchase=purchase4, user=users[3], location=locations[1], supplier=suppliers[6], cost=3200, currency='EUR', warranty_length=24, purchase_date=purchase4.purchase_date),
            Asset(name='DSN-LT-002', brand=brand_map['Apple'], model=model_map[('Apple', 'MacBook Pro 16"')], serial_number=fake.uuid4(), status='In Use', purchase=purchase4, user=users[7], location=locations[1], supplier=suppliers[6], cost=3200, currency='EUR', warranty_length=24, purchase_date=purchase4.purchase_date),
            Asset(name='SALES-LT-001', brand=brand_map['Microsoft'], model=model_map[('Microsoft', 'Surface Laptop 5')], serial_number=fake.uuid4(), status='In Storage', location=locations[0], supplier=suppliers[1], cost=1800, currency='USD', warranty_length=24, purchase_date=date(2024, 5, 5)),
            Asset(name='EOL-LT-001', brand=brand_map['Apple'], model=model_map[('Apple', 'MacBook Pro 13"')], serial_number=fake.uuid4(), status='Awaiting Disposal', location=locations[0], cost=1500, currency='USD', purchase_date=date(2021, 5, 5)),
            Asset(name='FW-NYC-01', brand=brand_map['Palo Alto'], model=model_map[('Palo Alto', 'PA-440')], serial_number=fake.uuid4(), status='In Use', purchase=purchase5, location=locations[0], supplier=suppliers[13], cost=4000, currency='USD', warranty_length=60, purchase_date=purchase5.purchase_date)
        ]
        db.session.add_all(assets)
        db.session.commit()

        peripherals = [
            Peripheral(name='Keyboard-001', type='Keyboard', brand=brand_map['Logitech'], cost=100, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[7]),
            Peripheral(name='Mouse-001', type='Mouse', brand=brand_map['Logitech'], cost=80, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[7]),
            Peripheral(name='Monitor-001', type='Monitor', brand=brand_map['Dell'], cost=450, currency='EUR', serial_number=fake.uuid4(), asset=assets[0], user=users[0], supplier=suppliers[2]),
            Peripheral(name='Keyboard-003', type='Keyboard', brand=brand_map['Apple'], cost=150, currency='EUR', asset=assets[2], user=users[3]),
            Peripheral(name='Mouse-003', type='Mouse', brand=brand_map['Apple'], cost=90, currency='EUR', asset=assets[2], user=users[3]),
        ]
        db.session.add_all(peripherals)
        db.session.commit()
        
        # 5. Create Subscriptions and Opportunities
        print("Creating subscriptions and opportunities...")
        subscriptions_data = [
            {'name': 'Adobe Creative Cloud', 'type': 'Software', 'renewal': date(2025, 11, 1), 'cost': 15000, 'supplier': suppliers[0]},
            {'name': 'Microsoft 365 E5', 'type': 'SaaS', 'renewal': date(2026, 1, 1), 'cost': 35000, 'supplier': suppliers[1]},
            {'name': 'Okta Identity Provider', 'type': 'Security', 'renewal': date(2026, 6, 1), 'cost': 12000, 'supplier': suppliers[12]},
        ]
        for data in subscriptions_data:
            subscription = Subscription(name=data['name'], subscription_type=data['type'], renewal_date=data['renewal'], cost=data['cost'], supplier=data['supplier'], renewal_period_type='yearly')
            db.session.add(subscription)
        
        # Create Requirements
        from src.models.crm import Requirement, RequirementAction, OpportunityTask
        requirements_data = [
            {
                'name': 'Need a comprehensive backup solution',
                'requirement_type': 'Software',
                'priority': 'High',
                'status': 'Researching',
                'description': 'Current backup solution is outdated. Need cloud-based backup with 3-2-1 strategy support.',
                'estimated_budget': 15000,
                'needed_by': date(2026, 6, 1)
            },
            {
                'name': 'Replace aging network equipment',
                'requirement_type': 'Hardware',
                'priority': 'Critical',
                'status': 'Evaluating',
                'description': 'Core switches are EOL. Need replacement for 3 core switches and 15 access switches.',
                'estimated_budget': 75000,
                'needed_by': date(2026, 4, 1)
            },
            {
                'name': 'Implement SIEM solution',
                'requirement_type': 'Security',
                'priority': 'Medium',
                'status': 'New',
                'description': 'Required for compliance. Need centralized logging and security monitoring.',
                'estimated_budget': 30000,
                'needed_by': date(2026, 8, 1)
            }
        ]
        requirements = []
        for data in requirements_data:
            req = Requirement(**data)
            db.session.add(req)
            requirements.append(req)
        db.session.commit()

        # Add some actions to requirements
        actions = [
            RequirementAction(requirement=requirements[0], action_type='Research', description='Evaluated Veeam, Commvault, and Druva. Druva looks promising for cloud-first approach.'),
            RequirementAction(requirement=requirements[0], action_type='Meeting', description='Demo scheduled with Druva for next week.'),
            RequirementAction(requirement=requirements[1], action_type='Note', description='Current switches: Cisco 3750X (2015). Warranty expired 2020.'),
        ]
        db.session.add_all(actions)
        db.session.commit()

        # Create Evaluations (Opportunities) - some linked to requirements
        opportunities = [
            Opportunity(name="Company-wide SSO solution", status="Evaluating", potential_value=20000, supplier=suppliers[12]),
            Opportunity(name="Next-gen firewall refresh", status="Negotiating", potential_value=50000, supplier=suppliers[13], estimated_close_date=date(2025, 12, 1)),
            Opportunity(name="Evaluation: Druva Cloud Backup", status="PoC", potential_value=15000, supplier=suppliers[0], requirement_id=requirements[0].id, estimated_close_date=date(2026, 3, 15)),
        ]
        db.session.add_all(opportunities)
        db.session.commit()

        # Add some tasks to evaluations
        tasks = [
            OpportunityTask(opportunity=opportunities[0], description='Request pricing for 500 users', due_date=date(2026, 2, 20)),
            OpportunityTask(opportunity=opportunities[0], description='Schedule technical deep-dive', due_date=date(2026, 2, 25)),
            OpportunityTask(opportunity=opportunities[2], description='Complete 30-day PoC', due_date=date(2026, 3, 10), is_completed=True),
            OpportunityTask(opportunity=opportunities[2], description='Present results to management', due_date=date(2026, 3, 15)),
        ]
        db.session.add_all(tasks)
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

        assignment = CourseAssignment(course_id=course.id, user_id=users[1].id, due_date=today() + timedelta(days=30))
        db.session.add(assignment)
        
        # 7. Create Compliance & Governance Entities
        print("Creating compliance and governance entities...")
        risks = [
            Risk(
                risk_description="Unauthorized access to cloud infrastructure", 
                extended_description="Attackers or unauthorized users could gain access to cloud resources (AWS, Azure, GCP) due to weak passwords, stolen credentials, or lack of multi-factor authentication. This could result in data breaches, service disruption, and significant financial/reputational damage.",
                status="Assessed", 
                inherent_likelihood=4, inherent_impact=5, 
                residual_likelihood=2, residual_impact=5,
                treatment_strategy="Mitigate",
                owner=users[0], # Alice
                next_review_date=today() + timedelta(days=90),
                mitigation_plan="Enforce MFA and rotate keys quarterly."
            ),
            Risk(
                risk_description="Data loss from database hardware failure", 
                extended_description="The primary database server could experience a hardware failure (disk crash, power supply failure, etc.) leading to loss of critical business data. Without proper backups, this could cause significant operational disruption and potential regulatory non-compliance.",
                status="In Treatment", 
                inherent_likelihood=2, inherent_impact=4, 
                residual_likelihood=1, residual_impact=4,
                treatment_strategy="Mitigate",
                owner=users[5], # Fiona
                next_review_date=today() + timedelta(days=30),
                mitigation_plan="Implement daily backups to a secondary location."
            ),
            Risk(
                risk_description="Malware infection on endpoints", 
                extended_description="End-user devices (laptops, workstations) could become infected with malware through phishing emails, malicious downloads, or drive-by downloads. Malware could lead to data theft, ransomware attacks, or lateral movement within the network.",
                status="Identified", 
                inherent_likelihood=5, inherent_impact=3, 
                residual_likelihood=3, residual_impact=3,
                treatment_strategy="Mitigate",
                owner=users[0], # Alice
                next_review_date=today() + timedelta(days=60),
                mitigation_plan="Deploy EDR solution."
            ),
            Risk(
                risk_description="Third-party supplier security failure", 
                extended_description="Critical suppliers (SaaS vendors, cloud providers) may fail to meet security obligations, experience data breaches, or become unavailable. This creates supply chain risk that could impact our operations and expose our data.",
                status="Assessed", 
                inherent_likelihood=3, inherent_impact=5, 
                residual_likelihood=2, residual_impact=4,
                treatment_strategy="Transfer",
                owner=users[6], # George (Sales/Vendor Mgmt)
                next_review_date=today() + timedelta(days=180),
                mitigation_plan="Include strict SLAs and penalties in contracts."
            ),
            Risk(
                risk_description="Data leakage via email", 
                extended_description="Employees could accidentally or intentionally send sensitive data (customer PII, financial data, trade secrets) via email to unauthorized recipients. This could violate GDPR, contractual obligations, and cause reputational damage.",
                status="Identified", 
                inherent_likelihood=4, inherent_impact=4, 
                residual_likelihood=3, residual_impact=4,
                treatment_strategy="Mitigate",
                owner=users[1], # Bob
                next_review_date=today() + timedelta(days=45),
                mitigation_plan="Implement DLP rules for email."
            ),
            Risk(
                risk_description="Inadequate access control reviews", 
                extended_description="User access rights may accumulate over time (privilege creep) or remain active for terminated employees. Without regular reviews, this creates excessive permissions and potential for unauthorized access to sensitive systems and data.",
                status="In Treatment", 
                inherent_likelihood=3, inherent_impact=3, 
                residual_likelihood=1, residual_impact=3,
                treatment_strategy="Mitigate",
                owner=users[0], # Alice
                next_review_date=today() + timedelta(days=90),
                mitigation_plan="Quarterly access reviews."
            ),
            # New Risks for Dashboard Variety
            Risk(
                risk_description="Legacy system vulnerabilities", 
                extended_description="Legacy systems that are no longer supported may contain known vulnerabilities that cannot be patched. These systems are attractive targets for attackers and may be difficult to monitor.",
                status="Accepted", 
                inherent_likelihood=2, inherent_impact=3, 
                residual_likelihood=2, residual_impact=3,
                treatment_strategy="Accept",
                owner=users[0], # Alice
                next_review_date=today() + timedelta(days=180),
                mitigation_plan="System is air-gapped; risk accepted until decommissioning in 2026."
            ),
            Risk(
                risk_description="Insider threat from employees", 
                extended_description="Disgruntled, negligent, or compromised employees could misuse their authorized access to steal data, sabotage systems, or facilitate external attacks. Insider threats are difficult to detect and can cause significant damage.",
                status="Assessed", 
                inherent_likelihood=2, inherent_impact=5, 
                residual_likelihood=1, residual_impact=5,
                treatment_strategy="Mitigate",
                owner=users[2], # Charlie
                next_review_date=today() + timedelta(days=120),
                mitigation_plan="Background checks and least privilege access."
            ),
            Risk(
                risk_description="DDoS attack on public website", 
                extended_description="Our public-facing website and APIs could be targeted by distributed denial-of-service attacks, making services unavailable to legitimate users. This impacts revenue, customer trust, and operational efficiency.",
                status="Mitigated", 
                inherent_likelihood=4, inherent_impact=4, 
                residual_likelihood=1, residual_impact=2,
                treatment_strategy="Transfer",
                owner=users[5], # Fiona
                next_review_date=today() + timedelta(days=365),
                mitigation_plan="Use Cloudflare DDoS protection."
            ),
            Risk(
                risk_description="GDPR regulatory non-compliance", 
                extended_description="Failure to comply with GDPR requirements for processing EU citizen data could result in significant fines (up to 4% of global revenue), legal action, and reputational damage. This includes consent management, data subject rights, and breach notification.",
                status="Assessed", 
                inherent_likelihood=3, inherent_impact=5, 
                residual_likelihood=2, residual_impact=5,
                treatment_strategy="Avoid",
                owner=users[1], # Bob
                next_review_date=today() + timedelta(days=60),
                mitigation_plan="Do not process data of EU citizens until compliant."
            ),
             Risk(
                risk_description="API key exposure in code repositories", 
                extended_description="API keys, database credentials, or other secrets may be accidentally committed to source code repositories (public or private). Exposed credentials can be harvested by attackers and used to access systems, exfiltrate data, or incur costs.",
                status="Assessed", 
                inherent_likelihood=5, inherent_impact=5, 
                residual_likelihood=5, residual_impact=5,
                treatment_strategy="Mitigate",
                owner=users[0], # Alice
                next_review_date=today() + timedelta(days=1),
                mitigation_plan="Immediate rotation and secrets management implementation."
            )
        ]
        db.session.add_all(risks)

        incident = SecurityIncident(title="Phishing Email Reported by Bob Williams", description="User Bob Williams reported a suspicious email with a link to a fake login page.", severity="SEV-2", impact="Minor", owner=users[0], reported_by=users[1])
        incident.affected_users.append(users[1])
        db.session.add(incident)
        
        bcdr_plan = BCDRPlan(name="Primary Database Failure Plan", description="Steps to restore the main application database from backups.")
        bcdr_plan.subscriptions.append(Subscription.query.first())
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

        ewaste_supplier = Supplier(name="eWaste Inc.", email="contact@ewasteinc.com", compliance_status="Compliant")
        db.session.add(ewaste_supplier)
        db.session.flush()
        disposal = DisposalRecord(disposal_method="Recycled", disposal_partner=ewaste_supplier, asset=assets[5])
        db.session.add(disposal)

        # More Maintenances for Asset 0
        m_log2 = MaintenanceLog(event_type="Planned Maintenance", description="Annual hardware diagnostic check.", status="Completed", asset=assets[0], assigned_to=users[8], event_date=date(2024, 12, 10))
        m_log3 = MaintenanceLog(event_type="Upgrade", description="RAM upgrade to 32GB.", status="Completed", asset=assets[0], assigned_to=users[0], event_date=date(2025, 1, 15))
        db.session.add_all([m_log2, m_log3])
        
        # More Erasures (for Asset 5 - EOL-LT-001)
        # It already has one. Let's add one to another asset that is retired? 
        # Or just another log type for Asset 5.
        erasure_log_2 = MaintenanceLog(event_type="Data Erasure", description="Drive physical destruction.", status="Completed", asset=assets[5], assigned_to=users[0], event_date=date(2025, 1, 5))
        db.session.add(erasure_log_2)
        
        # Asset History (Assignments)
        # Asset 0 (DEV-LT-001) is currently assigned to users[0] (Alice).
        # Let's say it was previously checked out to users[4] (Fiona).
        assignment_hist = AssetAssignment(
            asset_id=assets[0].id,
            user_id=users[4].id,
            checked_out_date=datetime(2024, 1, 15, 9, 0, 0),
            checked_in_date=datetime(2024, 11, 20, 17, 0, 0),
            notes="Temporary loaner while waiting for new laptop."
        )
        # Current assignment is implicit in the Asset model user_id, but the separate table tracks history.
        # Let's add a current open assignment record for consistency if the app uses it?
        # The app uses asset.assignments for history.
        assignment_curr = AssetAssignment(
            asset_id=assets[0].id,
            user_id=users[0].id,
            checked_out_date=datetime(2024, 11, 21, 9, 0, 0),
            notes="Primary device."
        )
        db.session.add_all([assignment_hist, assignment_curr])

        db.session.commit()

        # 9. Create Documentation, Links, Software, Licenses
        print("Creating documentation, links, software, and licenses...")
        
        docs = [
            Documentation(name="Employee Handbook 2025", description="General company policies and guidelines.", external_link="https://docs.example.com/handbook", owner_id=users[1].id, owner_type='User'),
            Documentation(name="IT Security Policy", description="Comprehensive security policy for all staff.", external_link="https://docs.example.com/security", owner_id=users[0].id, owner_type='User'),
            Documentation(name="Onboarding Guide", description="Guide for new hires.", external_link="https://docs.example.com/onboarding", owner_id=users[7].id, owner_type='User')
        ]
        db.session.add_all(docs)

        links = [
            Link(name="Jira", url="https://jira.example.com", description="Issue tracking", owner_id=group_engineering.id, owner_type='Group'),
            Link(name="Confluence", url="https://confluence.example.com", description="Knowledge base", owner_id=group_engineering.id, owner_type='Group'),
            Link(name="Figma", url="https://figma.com/files/team/example", description="Design files", owner_id=group_design.id, owner_type='Group'),
            Link(name="Salesforce", url="https://salesforce.com", description="CRM", owner_id=group_sales.id, owner_type='Group')
        ]
        db.session.add_all(links)

        software_list = [
            Software(name="Visual Studio Code 1.85", description="Code editor by Microsoft", category="Development"),
            Software(name="Slack 4.36", description="Communication tool by Slack Technologies", category="Communication"),
            Software(name="Zoom 5.17", description="Video conferencing by Zoom Video Communications", category="Communication"),
            Software(name="Adobe Photoshop 2024", description="Image editing by Adobe", category="Design")
        ]
        db.session.add_all(software_list)
        db.session.commit() # Commit to get IDs

        licenses = [
            License(name="VS Code Enterprise", license_key="FREE-LICENSE", expiry_date=date(2099, 12, 31), software_id=software_list[0].id, user_id=users[0].id),
            License(name="Slack Business Plus", license_key="SLACK-KEY-123", expiry_date=date(2025, 1, 10), software_id=software_list[1].id, user_id=users[1].id),
            License(name="Adobe Creative Cloud All Apps", license_key="ADOBE-KEY-456", expiry_date=date(2025, 11, 1), software_id=software_list[3].id, user_id=users[3].id)
        ]
        db.session.add_all(licenses)
        db.session.commit()

        # 10. Create Fake Framework & Compliance Links
        print("Creating fake framework and compliance links...")
        
        fake_framework = Framework(name="Galactic Security Standard (GSS)", description="Standard for security across the galaxy.", is_active=True, is_custom=True)
        db.session.add(fake_framework)
        db.session.commit()

        fake_controls = [
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.1.1", name="Planetary Defense", description="Ensure planetary shields are active."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.1.2", name="Droid Security", description="Prevent unauthorized droid hacking."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.2.1", name="Hologram Encryption", description="Encrypt all holographic communications."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.3.1", name="Warp Drive Safety", description="Regular maintenance of warp cores."),
            # Stress test items
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.4.1", name="Turbo Encabulator", description="Legacy hardware interface for retrograde capacitance."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.4.2", name="Recursive Logic", description="Infinite loop testing and stack overflow prevention."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.5.1", name="Null Pointer", description="Void reference handling and exception management."),
            FrameworkControl(framework_id=fake_framework.id, control_id="GSS.5.2", name="Secret Cow Level", description="Easter egg implementation and hidden feature access.")
        ]
        db.session.add_all(fake_controls)
        db.session.commit()
        
        # Automation Rules
        print("Creating automation rules...")
        # Rule 1: Maintenance required every 90 days for Warp Drive Safety
        rule1 = ComplianceRule(
            framework_control_id=fake_controls[3].id, # GSS.3.1
            name="Quarterly Maintenance Check",
            target_model="MaintenanceLog",
            criteria='{"event_type": "Planned Maintenance"}',
            frequency_days=90,
            grace_period_days=14,
            enabled=True
        )
        
        # Rule 2: Droid Security - Check for specific software
        rule2 = ComplianceRule(
            framework_control_id=fake_controls[1].id, # GSS.1.2
            name="Anti-Hack Software Check",
            target_model="Software",
            criteria='{"category": "Security"}', # Just an example
            frequency_days=30, 
            enabled=True
        )
        db.session.add_all([rule1, rule2])
        db.session.commit()

        # Link controls to assets/docs
        compliance_links = [
            ComplianceLink(framework_control_id=fake_controls[0].id, linkable_id=assets[6].id, linkable_type='Asset', description="Firewall protects the planetary network."),
            ComplianceLink(framework_control_id=fake_controls[1].id, linkable_id=docs[1].id, linkable_type='Documentation', description="Policy outlines droid security protocols."),
            ComplianceLink(framework_control_id=fake_controls[2].id, linkable_id=software_list[1].id, linkable_type='Software', description="Slack used for encrypted comms (close enough)."),
            ComplianceLink(framework_control_id=fake_controls[3].id, linkable_id=maintenance_log.id, linkable_type='MaintenanceLog', description="Regular maintenance performed on core systems.")
        ]
        db.session.add_all(compliance_links)
        
        # 11. User Hierarchy (Managers)
        # 11. User Hierarchy (Managers & Buddies)
        print("Assigning managers and buddies...")
        
        # Mapping for clarity:
        # Alice (VP Eng) -> manages Charlie (Eng Mgr)
        # Charlie (Eng Mgr) -> manages Fiona, Ian, Diana, Heidi (Design sits under Eng for this demo)
        # Bob (VP Sales) -> manages George (Sales Mgr)
        # George (Sales Mgr) -> manages Ethan, Julia

        # Set Managers
        users[2].manager = users[0]  # Charlie -> Alice
        users[4].manager = users[0]  # Fiona -> Charlie (Wait, Index 4 is Fiona in new list? Let's check indices)
        # Re-fetching to be safe or using variable names would be better, but utilizing list indices for now based on above order:
        # 0: Alice, 1: Bob, 2: Charlie, 3: George, 4: Fiona, 5: Diana, 6: Heidi, 7: Ethan, 8: Ian, 9: Julia

        # Engineering Tree
        users[2].manager = users[0] # Charlie manages under Alice
        users[4].manager = users[2] # Fiona manages under Charlie
        users[5].manager = users[2] # Diana manages under Charlie
        users[6].manager = users[2] # Heidi manages under Charlie
        users[8].manager = users[2] # Ian manages under Charlie

        # Sales Tree
        users[3].manager = users[1] # George manages under Bob
        users[7].manager = users[3] # Ethan manages under George
        users[9].manager = users[3] # Julia manages under George

        # Buddies (Mentors)
        # Fiona mentors Ian (New Hire Eng)
        users[8].buddy = users[4]
        # Ethan mentors Julia (New Hire Sales)
        users[9].buddy = users[7]

        db.session.commit()

        # 12. Business Services
        # 12. Business Services
        print("Creating business services...")
        services = [
            BusinessService(name="E-Commerce Platform", description="Main customer facing store.", owner=users[2], criticality="Tier 1 - Critical", status="Operational"),
            BusinessService(name="Inventory System", description="Warehouse management and stock control.", owner=users[4], criticality="Tier 1 - Critical", status="Operational"),
            BusinessService(name="Payment Gateway", description="External payment processing integration.", owner=users[2], criticality="Tier 1 - Critical", status="Operational"),
            BusinessService(name="Internal HR Portal", description="Employee self-service and records.", owner=users[0], criticality="Tier 3 - Standard", status="Operational"),
            BusinessService(name="Customer Support Portal", description="Ticket management for end-users.", owner=users[6], criticality="Tier 2 - High", status="Operational"),
            BusinessService(name="Data Warehouse", description="Centralized analytics and reporting data.", owner=users[4], criticality="Tier 2 - High", status="Operational"),
            BusinessService(name="Identity Provider (IdP)", description="Centralized authentication (SSO).", owner=users[0], criticality="Tier 1 - Critical", status="Operational"),
            BusinessService(name="Logistics API", description="Integration with shipping providers.", owner=users[4], criticality="Tier 2 - High", status="Pipeline")
        ]
        db.session.add_all(services)
        db.session.commit()

        # Dependencies
        # Architecture:
        # E-Commerce -> Depends on: Inventory, Payment Gateway, Identity Provider
        services[0].upstream_dependencies.append(services[1]) # Inventory
        services[0].upstream_dependencies.append(services[2]) # Payment
        services[0].upstream_dependencies.append(services[6]) # IdP

        # Customer Support -> Depends on: Identity Provider, Inventory (to check order status)
        services[4].upstream_dependencies.append(services[6]) # IdP
        services[4].upstream_dependencies.append(services[1]) # Inventory

        # Data Warehouse -> Depends on: E-Commerce (source), Inventory (source)
        services[5].upstream_dependencies.append(services[0])
        services[5].upstream_dependencies.append(services[1])

        # Logistics API -> Depends on: Inventory
        services[7].upstream_dependencies.append(services[1])

        db.session.commit()

        # Service Components (Infrastructure)
        print("Linking service components...")
        # Link Firewall (Asset 6) to Payment Gateway (Service 2)
        comp_fw = ServiceComponent(
            service_id=services[2].id,
            component_type='Asset',
            component_id=assets[6].id,
            notes="Primary firewall for payment processing segment."
        )
        # Link Okta Subscription (Subscription 2) to IdP Service (Service 6)
        # Note: subscriptions_data[2] was Okta. It was added to session but we didn't keep the object ref in a list.
        # We need to fetch it or query it.
        okta_sub = Subscription.query.filter_by(name='Okta Identity Provider').first()
        if okta_sub:
            comp_okta = ServiceComponent(
                service_id=services[6].id,
                component_type='Subscription',
                component_id=okta_sub.id,
                notes="Underlying subscription for the IdP service."
            )
            db.session.add(comp_okta)
            
        db.session.add(comp_fw)
        db.session.commit()

        # 12b. Changes
        print("Creating changes...")
        change1 = Change(
            title="Upgrade Payment Gateway Firewall Firmware",
            change_type="Standard",
            priority="High",
            status="Completed",
            requester=users[0],
            assignee=users[8], # Ian
            description="Routine firmware upgrade to patch vulnerability CVE-2024-XXXX.",
            implementation_plan="1. Backup config.\n2. Upload firmware.\n3. Reboot.",
            service=services[2], # Payment Gateway
            asset=assets[6], # FW-NYC-01
            executed_at=datetime(2025, 1, 10, 23, 0, 0),
            closed_at=datetime(2025, 1, 11, 1, 0, 0)
        )
        change2 = Change(
            title="Migrate E-Commerce DB to New Server",
            change_type="Normal",
            priority="Critical",
            status="In Progress",
            requester=users[2], # Charlie
            assignee=users[4], # Fiona
            description="Migration to improve IOPS performance.",
            implementation_plan="Detailed steps...",
            service=services[0], # E-Commerce
            requires_approval=True,
            approved_by=users[0],
            approved_at=now()
        )
        
        db.session.add_all([change1, change2])
        db.session.commit()

        # 12c. Service Requests
        print("Creating service requests...")
        req_pending = Request(
            title="New laptop for marketing hire",
            request_type="Hardware",
            priority="High",
            status="Pending",
            description="New starter joining the marketing team next week needs a laptop.",
            justification="Onboarding deadline; equipment must be ready before day one.",
            requester=users[3],
            tags=[tags[1]],  # Hardware
        )
        req_triage = Request(
            title="VPN access for remote contractor",
            request_type="Access",
            priority="Medium",
            status="Triage",
            description="Contractor needs VPN access to the staging environment.",
            justification="Required to deliver the Q3 integration work remotely.",
            requester=users[2],  # Charlie
            assignee=users[8],   # Ian
            service=services[0],
            triaged_at=now() - timedelta(days=1),
            triaged_by=users[8],
            tags=[tags[7]],  # Security
        )
        req_inprogress = Request(
            title="Install Adobe Photoshop on design workstation",
            request_type="Software",
            priority="Medium",
            status="In Progress",
            description="Design team requested Photoshop for the new campaign assets.",
            justification="Approved software for the design function.",
            requester=users[4],  # Fiona
            assignee=users[8],   # Ian
            software=software_list[3],  # Adobe Photoshop
            triaged_at=now() - timedelta(days=3),
            triaged_by=users[8],
            started_at=now() - timedelta(days=2),
            tags=[tags[6]],  # Design
        )
        req_completed = Request(
            title="Reset MFA for locked-out user",
            request_type="Access",
            priority="Critical",
            status="Completed",
            description="User locked out after losing their MFA device.",
            justification="User unable to access critical systems.",
            requester=users[5],
            assignee=users[8],   # Ian
            triaged_at=now() - timedelta(days=5),
            triaged_by=users[8],
            started_at=now() - timedelta(days=5),
            completed_at=now() - timedelta(days=4),
            resolution_notes="MFA reset and re-enrolled on the user's new device. Verified login.",
        )
        req_closed = Request(
            title="Request office monitor",
            request_type="Hardware",
            priority="Low",
            status="Closed",
            description="Second monitor for the finance desk.",
            justification="Improve productivity for spreadsheet-heavy work.",
            requester=users[6],
            assignee=users[8],   # Ian
            triaged_at=now() - timedelta(days=20),
            triaged_by=users[8],
            started_at=now() - timedelta(days=18),
            completed_at=now() - timedelta(days=15),
            closed_at=now() - timedelta(days=14),
            resolution_notes="Monitor delivered and set up at the finance desk.",
            tags=[tags[1]],  # Hardware
        )
        req_cancelled = Request(
            title="Access to legacy CRM",
            request_type="Access",
            priority="Low",
            status="Cancelled",
            description="Access request to the legacy CRM system.",
            justification="Was needed for a data export task.",
            requester=users[7],
            triaged_at=now() - timedelta(days=8),
            triaged_by=users[8],
            closed_at=now() - timedelta(days=7),
        )

        db.session.add_all([
            req_pending, req_triage, req_inprogress,
            req_completed, req_closed, req_cancelled
        ])
        db.session.commit()

        # 13. Compliance Audit (Defense Room)
        print("Creating compliance audit...")
        # Create a snapshot audit for GSS
        audit = ComplianceAudit.create_snapshot(
            framework_id=fake_framework.id, 
            name="GSS Audit 2025", 
            auditor_contact_id=None, 
            internal_lead_id=users[2].id, # Charlie (Eng Mgr)
            copy_links=True # Populate evidence from live links
        )
        audit.status = "Prep"
        db.session.commit()

        # 13b. Compliance Drift Snapshots
        print("Creating compliance drift snapshots...")
        from .services.compliance_service import get_compliance_evaluator

        evaluator = get_compliance_evaluator()

        # Helper function to create a drift snapshot with modified data
        def create_drift_snapshot(days_ago, framework_id, status_overrides=None):
            """Create a historical drift snapshot with optional status overrides."""
            snapshot_time = now() - timedelta(days=days_ago)

            # Get current framework status
            framework_status = evaluator.get_framework_status(framework_id)

            if not framework_status:
                return None

            framework = db.session.get(Framework, framework_id)

            # Build snapshot data
            snapshot_data = {
                'timestamp': snapshot_time.isoformat(),
                'frameworks': {
                    framework_id: {
                        'name': framework.name,
                        'stats': framework_status['stats'].copy(),
                        'controls': {}
                    }
                }
            }

            # Apply status overrides if provided
            if status_overrides:
                for status, count in status_overrides.items():
                    if status in snapshot_data['frameworks'][framework_id]['stats']:
                        snapshot_data['frameworks'][framework_id]['stats'][status] = count

            # Store individual control statuses
            control_idx = 0
            for control in framework_status['controls']:
                # Apply status override if we're modifying specific controls
                control_status = control['status']
                if status_overrides and control_idx < len(status_overrides.get('_control_overrides', [])):
                    control_status = status_overrides['_control_overrides'][control_idx]

                snapshot_data['frameworks'][framework_id]['controls'][control['id']] = {
                    'control_id': control['control_id'],
                    'name': control['name'],
                    'status': control_status,
                    'rules_count': control['rules_count'],
                    'oldest_evidence_date': control['oldest_evidence_date'].isoformat()
                    if control['oldest_evidence_date'] else None
                }
                control_idx += 1

            # Create ComplianceAudit record
            drift_snapshot = ComplianceAudit(
                audit_type='drift_snapshot',
                snapshot_data=snapshot_data,
                created_at=snapshot_time
            )

            return drift_snapshot

        # Create snapshots at different time points to show drift
        snapshots = []

        # Snapshot 1: 30 days ago - Good compliance (better than current)
        snapshot1 = create_drift_snapshot(
            days_ago=30,
            framework_id=fake_framework.id,
            status_overrides={
                'compliant': 8,
                'manual': 2,
                'warning': 1,
                'non_compliant': 0,
                'uncovered': 1,
                '_control_overrides': ['compliant'] * 12  # Override first 12 controls to compliant
            }
        )
        if snapshot1:
            snapshots.append(snapshot1)

        # Snapshot 2: 15 days ago - Drift detected (regression)
        snapshot2 = create_drift_snapshot(
            days_ago=15,
            framework_id=fake_framework.id,
            status_overrides={
                'compliant': 6,
                'manual': 2,
                'warning': 3,
                'non_compliant': 1,
                'uncovered': 2,
                '_control_overrides': ['compliant', 'compliant', 'warning', 'compliant', 'non_compliant', 'warning']
            }
        )
        if snapshot2:
            snapshots.append(snapshot2)

        # Snapshot 3: 7 days ago - Partial recovery
        snapshot3 = create_drift_snapshot(
            days_ago=7,
            framework_id=fake_framework.id,
            status_overrides={
                'compliant': 7,
                'manual': 2,
                'warning': 2,
                'non_compliant': 0,
                'uncovered': 1,
                '_control_overrides': ['compliant', 'compliant', 'manual', 'compliant', 'warning', 'compliant']
            }
        )
        if snapshot3:
            snapshots.append(snapshot3)

        # Snapshot 4: 1 day ago - Current-ish state
        snapshot4 = create_drift_snapshot(
            days_ago=1,
            framework_id=fake_framework.id
        )
        if snapshot4:
            snapshots.append(snapshot4)

        db.session.add_all(snapshots)
        db.session.commit()
        print(f"  Created {len(snapshots)} drift snapshots")

        # 14. Historical Risk Assessments with Items
        print("Creating historical risk assessments with items...")
        from .models import RiskAssessmentItem, RiskAssessmentEvidence
        from datetime import datetime as dt
        
        # Q3 2024 Assessment - Higher initial residual scores
        q3_assessment = RiskAssessment(
            name="Q3 2024 Security Assessment",
            status="Locked",
            created_at=dt(2024, 9, 30),
            locked_at=dt(2024, 10, 1)
        )
        db.session.add(q3_assessment)
        db.session.flush()  # Get ID
        
        # Create items for Q3 - snapshot of risks at that time (higher residual)
        q3_items_data = [
            # (risk_index, inherent_i, inherent_l, residual_i, residual_l, notes)
            (0, 5, 4, 5, 3, "Initial controls in place but MFA adoption only at 60%."),
            (1, 4, 2, 4, 2, "Backup system operational but recovery time untested."),
            (2, 3, 5, 3, 4, "EDR deployment in progress, 50% coverage."),
            (3, 5, 3, 4, 3, "Supplier assessments pending for 2 vendors."),
            (4, 4, 4, 4, 4, "DLP solution not yet deployed."),
            (5, 3, 3, 3, 2, "Manual access reviews ongoing.")
        ]
        
        for risk_idx, inh_i, inh_l, res_i, res_l, notes in q3_items_data:
            risk = risks[risk_idx]
            item = RiskAssessmentItem(
                assessment_id=q3_assessment.id,
                original_risk_id=risk.id,
                risk_description=risk.risk_description,
                threat_type_name=risk.threat_type.name if risk.threat_type else None,
                category_list=",".join([c.category for c in risk.categories]) if risk.categories else "",
                inherent_impact=inh_i,
                inherent_likelihood=inh_l,
                residual_impact=res_i,
                residual_likelihood=res_l,
                treatment_strategy=risk.treatment_strategy,
                mitigation_notes=notes
            )
            db.session.add(item)
        
        q3_assessment.calculate_total_risk()
        
        # Q4 2024 Assessment - Lower residual scores (improvement!)
        q4_assessment = RiskAssessment(
            name="Q4 2024 Security Assessment",
            status="Locked",
            created_at=dt(2024, 12, 31),
            locked_at=dt(2025, 1, 2)
        )
        db.session.add(q4_assessment)
        db.session.flush()
        
        # Create items for Q4 - shows improvement from controls
        q4_items_data = [
            # (risk_index, inherent_i, inherent_l, residual_i, residual_l, notes)
            (0, 5, 4, 5, 2, "MFA enforced company-wide. Key rotation automated."),
            (1, 4, 2, 4, 1, "Disaster recovery test successful. RTO < 30 min achieved."),
            (2, 3, 5, 3, 3, "EDR deployed to 95% of endpoints."),
            (3, 5, 3, 4, 2, "All critical vendors assessed. DPAs signed."),
            (4, 4, 4, 4, 3, "DLP rules deployed for email. Monitoring active."),
            (5, 3, 3, 3, 1, "Automated quarterly access reviews implemented."),
            (8, 4, 4, 2, 1, "Cloudflare fully operational. DDoS mitigated."),  # DDoS risk
        ]
        
        for risk_idx, inh_i, inh_l, res_i, res_l, notes in q4_items_data:
            risk = risks[risk_idx]
            item = RiskAssessmentItem(
                assessment_id=q4_assessment.id,
                original_risk_id=risk.id,
                risk_description=risk.risk_description,
                threat_type_name=risk.threat_type.name if risk.threat_type else None,
                category_list=",".join([c.category for c in risk.categories]) if risk.categories else "",
                inherent_impact=inh_i,
                inherent_likelihood=inh_l,
                residual_impact=res_i,
                residual_likelihood=res_l,
                treatment_strategy=risk.treatment_strategy,
                mitigation_notes=notes
            )
            db.session.add(item)
            db.session.flush()
            
            # Add evidence links to some items (policies, docs)
            if risk_idx == 0:  # MFA risk - link to security policy
                ev = RiskAssessmentEvidence(item_id=item.id, linkable_type='Policy', linkable_id=policy.id, notes='MFA mandated in policy')
                db.session.add(ev)
            if risk_idx == 1:  # Backup risk - link to BCDR plan
                ev = RiskAssessmentEvidence(item_id=item.id, linkable_type='BCDRPlan', linkable_id=bcdr_plan.id, notes='DR plan tested successfully')
                db.session.add(ev)
        
        q4_assessment.calculate_total_risk()
        db.session.commit()

        # 15. Notification System - Email Templates and Events
        # MOVED TO PROD SEEDER (src/seeder_prod.py)
        print("Skipping notification templates (moved to prod seeder)...")

        # 16. Create Standard Security Activities
        print("Creating standard security activities...")
        
        # Retrieve activity category tags by name
        tag_identity = Tag.query.filter_by(name='Identity').first()
        tag_awareness = Tag.query.filter_by(name='Awareness').first()
        tag_vuln = Tag.query.filter_by(name='Vulnerability Mgmt').first()
        tag_network = Tag.query.filter_by(name='Network').first()
        tag_bcdr = Tag.query.filter_by(name='BCDR').first()
        tag_grc = Tag.query.filter_by(name='GRC').first()
        
        security_activities = [
            # Identity & Access
            SecurityActivity(
                name="Quarterly User Access Review",
                description="Revisión trimestral de cuentas de usuario, privilegios y accesos a sistemas críticos.",
                frequency="Quarterly",
                owner_id=users[0].id,  # Alice (VP of Engineering)
                owner_type='User'
            ),
            
            # Awareness & Training
            SecurityActivity(
                name="Phishing Simulation Campaign",
                description="Envío de correos simulados de phishing para evaluar la concienciación de los empleados.",
                frequency="Monthly",
                owner_id=users[0].id,
                owner_type='User'
            ),
            SecurityActivity(
                name="Security Newsletter",
                description="Boletín mensual con actualizaciones de seguridad y mejores prácticas.",
                frequency="Monthly",
                owner_id=users[0].id,
                owner_type='User'
            ),
            
            # Vulnerability Management
            SecurityActivity(
                name="Annual Penetration Test",
                description="Test de intrusión externo realizado por un proveedor certificado.",
                frequency="Yearly",
                owner_id=users[0].id,
                owner_type='User'
            ),
            SecurityActivity(
                name="External Vulnerability Scan",
                description="Escaneo automatizado de vulnerabilidades en activos expuestos a internet.",
                frequency="Weekly",
                owner_id=users[0].id,
                owner_type='User'
            ),
            
            # Infrastructure & Operations
            SecurityActivity(
                name="Firewall Rules Review",
                description="Revisión de reglas de firewall para eliminar accesos obsoletos o inseguros.",
                frequency="Semiannual",
                owner_id=users[2].id,  # Charlie (Engineering Manager)
                owner_type='User'
            ),
            SecurityActivity(
                name="Backup Restoration Test",
                description="Prueba aleatoria de restauración de backups para verificar integridad de datos.",
                frequency="Quarterly",
                owner_id=users[4].id,  # Fiona (Senior Backend Developer)
                owner_type='User'
            ),
            
            # Governance
            SecurityActivity(
                name="Vendor Risk Assessment Review",
                description="Reevaluación de riesgos de proveedores críticos.",
                frequency="Yearly",
                owner_id=users[1].id,  # Bob (VP of Sales)
                owner_type='User'
            )
        ]
        
        db.session.add_all(security_activities)
        db.session.commit()
        
        # Assign category tags to activities
        security_activities[0].tags.append(tag_identity)  # Quarterly User Access Review
        security_activities[1].tags.append(tag_awareness)  # Phishing Simulation
        security_activities[2].tags.append(tag_awareness)  # Security Newsletter
        security_activities[3].tags.append(tag_vuln)       # Annual Penetration Test
        security_activities[4].tags.append(tag_vuln)       # External Vulnerability Scan
        security_activities[5].tags.append(tag_network)    # Firewall Rules Review
        security_activities[6].tags.append(tag_bcdr)       # Backup Restoration Test
        security_activities[7].tags.append(tag_grc)        # Vendor Risk Assessment Review
        
        db.session.commit()
        
        # Create historical executions for "Quarterly User Access Review" (80 days ago)
        # This allows testing of overdue/expired alerts
        past_execution_date = today() - timedelta(days=80)
        
        activity_executions = [
            ActivityExecution(
                activity_id=security_activities[0].id,  # Quarterly User Access Review
                executor_id=users[0].id,  # Alice
                execution_date=past_execution_date,
                status='success',
                outcome_notes='Revisión completada. Se revocaron 5 accesos obsoletos de empleados que dejaron la empresa.'
            ),
            ActivityExecution(
                activity_id=security_activities[0].id,  # Quarterly User Access Review
                executor_id=users[2].id,  # Charlie
                execution_date=past_execution_date - timedelta(days=90),  # ~170 days ago
                status='success',
                outcome_notes='Revisión de Q3. Se identificaron 3 cuentas con privilegios excesivos y se corrigieron.'
            )
        ]
        
        db.session.add_all(activity_executions)
        db.session.commit()

        # Create Some Demo Candidates for Hiring Pipeline
        print("Creating demo candidates...")
        demo_candidates = [
            Candidate(name='Sarah Johnson', email='sarah.johnson@example.com', phone='+1-555-0101', 
                     position='Senior DevOps Engineer', expected_salary=95000, currency='USD',
                     stage=hiring_stages[0], resume_link='https://example.com/resumes/sarah', 
                     notes='Excellent AWS experience, 8 years in the field'),
            Candidate(name='Michael Chen', email='michael.chen@example.com', phone='+1-555-0102',
                     position='Product Designer', expected_salary=75000, currency='EUR',
                     stage=hiring_stages[1], resume_link='https://example.com/resumes/michael',
                     notes='Strong portfolio, Figma expert'),
            Candidate(name='Emily Rodriguez', email='emily.r@example.com', phone='+1-555-0103',
                     position='Full Stack Developer', expected_salary=85000, currency='USD',
                     stage=hiring_stages[2], notes='Technical interview scheduled for next week'),
            Candidate(name='James Williams', email='james.w@example.com', phone='+1-555-0104',
                     position='Sales Executive', expected_salary=70000, currency='EUR',
                     stage=hiring_stages[3], notes='Strong closer, great references'),
            Candidate(name='Lisa Anderson', email='lisa.a@example.com',
                     position='Junior Developer', expected_salary=50000, currency='EUR',
                     stage=hiring_stages[5], notes='Not a good cultural fit')
        ]
        db.session.add_all(demo_candidates)
        db.session.commit()

        # ------------------------------------------------------------------
        # HR: role profiles, global checklist, email templates, processes
        # ------------------------------------------------------------------
        print("Creating HR role profiles, checklists, templates and processes...")

        def _sw(name_fragment):
            """Look up seeded software by partial name (for pack provisioning)."""
            return Software.query.filter(Software.name.ilike(f"%{name_fragment}%")).first()

        # --- Role profiles (Onboarding Packs) with differentiated tasks ---
        pack_dev = OnboardingPack(name='Development', description='Role profile for software engineers and developers.')
        pack_design = OnboardingPack(name='Design', description='Role profile for product and brand designers.')
        pack_finance = OnboardingPack(name='Financial', description='Role profile for finance and accounting roles.')
        db.session.add_all([pack_dev, pack_design, pack_finance])
        db.session.flush()

        vscode = _sw('Visual Studio Code')
        photoshop = _sw('Adobe Photoshop')

        pack_items = [
            # Development
            PackItem(pack_id=pack_dev.id, item_type='Hardware', description='Provision developer laptop (16GB+ RAM)'),
            PackItem(pack_id=pack_dev.id, item_type='Software', description='Install IDE / code editor',
                     software_id=vscode.id if vscode else None),
            PackItem(pack_id=pack_dev.id, item_type='Task', description='Grant access to Git repositories and CI/CD'),
            PackItem(pack_id=pack_dev.id, item_type='Task', description='Add to on-call rotation and incident tooling'),
            # Design
            PackItem(pack_id=pack_design.id, item_type='Hardware', description='Provision design workstation + calibrated monitor'),
            PackItem(pack_id=pack_design.id, item_type='Software', description='Install Adobe Creative Suite',
                     software_id=photoshop.id if photoshop else None),
            PackItem(pack_id=pack_design.id, item_type='Task', description='Grant access to Figma and design system library'),
            PackItem(pack_id=pack_design.id, item_type='Task', description='Share brand asset repository and guidelines'),
            # Financial
            PackItem(pack_id=pack_finance.id, item_type='Hardware', description='Provision standard laptop with dual monitors'),
            PackItem(pack_id=pack_finance.id, item_type='Task', description='Grant access to ERP / accounting system'),
            PackItem(pack_id=pack_finance.id, item_type='Task', description='Configure expense approval workflow'),
            PackItem(pack_id=pack_finance.id, item_type='Task', description='Sign financial controls and SoD acknowledgment'),
        ]
        db.session.add_all(pack_items)

        # --- Global checklist common to all departments (ProcessTemplate) ---
        global_templates = [
            # Onboarding
            ProcessTemplate(name='Sign NDA and employment contract', process_type='onboarding'),
            ProcessTemplate(name='Complete HR paperwork and tax forms', process_type='onboarding'),
            ProcessTemplate(name='Security & compliance induction training', process_type='onboarding'),
            ProcessTemplate(name='Add to company directory and org chart', process_type='onboarding'),
            # Offboarding
            ProcessTemplate(name='Conduct exit interview', process_type='offboarding'),
            ProcessTemplate(name='Revoke building and badge access', process_type='offboarding'),
            ProcessTemplate(name='Collect all company equipment', process_type='offboarding'),
            ProcessTemplate(name='Remove from payroll and benefits', process_type='offboarding'),
        ]
        db.session.add_all(global_templates)

        # --- Custom email templates (Jinja2; vars from communications_context) ---
        tpl_welcome = EmailTemplate(
            name='New Hire Welcome',
            subject='Welcome aboard, {{ new_hire_name }}! 🎉',
            category='onboarding', is_active=True, is_system=False,
            body_html="""
<p>Hi {{ new_hire_name }},</p>
<p>We're thrilled to welcome you to the team! Your first day is <strong>{{ start_date }}</strong>.</p>
<p>To help you hit the ground running:</p>
<ul>
    <li>Your laptop and accounts will be ready on day one.</li>
    <li>{% if buddy %}Your onboarding buddy, <strong>{{ buddy.name }}</strong>, will reach out to say hello.{% else %}A buddy will be assigned to help you settle in.{% endif %}</li>
    <li>{% if manager %}You'll have a 1:1 with your manager, <strong>{{ manager.name }}</strong>, during your first week.{% endif %}</li>
</ul>
<p>If you have any questions before you start, just reply to this email.</p>
<p>See you soon!<br>The People Team</p>
""".strip()
        )
        tpl_buddy = EmailTemplate(
            name='Buddy Heads-Up (New Hire Starts Tomorrow)',
            subject='Heads up: {{ new_hire_name }} starts tomorrow',
            category='onboarding', is_active=True, is_system=False,
            body_html="""
<p>Hi {% if buddy %}{{ buddy.name }}{% else %}there{% endif %},</p>
<p>A quick reminder that you're the onboarding buddy for <strong>{{ new_hire_name }}</strong>,
who joins us tomorrow ({{ start_date }}).</p>
<p>Please remember to:</p>
<ul>
    <li>Say hello and introduce yourself on their first morning.</li>
    <li>Schedule a welcome coffee in their first few days.</li>
    <li>Be their go-to person for the small questions during week one.</li>
</ul>
<p>Thanks for helping make their start a great one!<br>The People Team</p>
""".strip()
        )
        tpl_offboarding = EmailTemplate(
            name='Offboarding Next Steps',
            subject='Your departure: next steps and important dates',
            category='offboarding', is_active=True, is_system=False,
            body_html="""
<p>Hi {% if user %}{{ user.name }}{% else %}there{% endif %},</p>
<p>As your last day with us ({{ departure_date }}) approaches, here's a summary of the next steps
to wrap things up smoothly:</p>
<ul>
    <li>Return all company equipment (laptop, peripherals, access badge) by your last day.</li>
    <li>Your corporate accounts will be deactivated at the end of {{ departure_date }}.</li>
    <li>{% if manager %}Your manager, <strong>{{ manager.name }}</strong>, will schedule a short exit interview.{% else %}HR will reach out to schedule a short exit interview.{% endif %}</li>
    <li>Final payroll and benefits details will be sent to your personal email.</li>
</ul>
<p>Thank you for everything you've contributed. We wish you all the best in your next chapter!</p>
<p>Warm regards,<br>The People Team</p>
""".strip()
        )
        db.session.add_all([tpl_welcome, tpl_buddy, tpl_offboarding])
        db.session.flush()

        # Wire the onboarding templates into every role profile
        for pack in (pack_dev, pack_design, pack_finance):
            db.session.add_all([
                PackCommunication(pack_id=pack.id, template_id=tpl_welcome.id, offset_days=0, recipient_type='target_user'),
                PackCommunication(pack_id=pack.id, template_id=tpl_buddy.id, offset_days=-1, recipient_type='buddy'),
            ])
        db.session.commit()

        # --- A few onboarding/offboarding processes in different states ---
        onboarding_global = [t for t in global_templates if t.process_type == 'onboarding']
        offboarding_global = [t for t in global_templates if t.process_type == 'offboarding']

        manager_eng = users[2]    # Charlie Brown (Engineering Manager)
        manager_sales = users[3]  # George Costanza (Sales Manager)
        buddy_dev = users[4]      # Fiona Glenanne
        buddy_design = users[5]   # Diana Prince

        def _make_onboarding_items(proc, pack, completed_upto):
            """Mirror the checklist the onboarding route would generate."""
            items = [ProcessItem(onboarding_process_id=proc.id,
                                 description="👤 Create user account (Automated)", item_type='CreateUser')]
            items += [ProcessItem(onboarding_process_id=proc.id, description=t.name, item_type='StaticTask')
                      for t in onboarding_global]
            items += [ProcessItem(onboarding_process_id=proc.id, description=pi.description,
                                  item_type=pi.item_type, linked_object_id=pi.software_id) for pi in pack.items]
            if proc.assigned_manager_id:
                mgr = db.session.get(User, proc.assigned_manager_id)
                items.append(ProcessItem(onboarding_process_id=proc.id, item_type='SocialTask',
                                         description=f"📅 Schedule 1:1 meeting with {mgr.name} (Manager)",
                                         linked_object_id=mgr.id))
            if proc.assigned_buddy_id:
                bd = db.session.get(User, proc.assigned_buddy_id)
                items.append(ProcessItem(onboarding_process_id=proc.id, item_type='SocialTask',
                                         description=f"☕ Schedule welcome coffee with buddy: {bd.name}",
                                         linked_object_id=bd.id))
            for idx, it in enumerate(items):
                if completed_upto == -1 or idx < completed_upto:
                    it.is_completed = True
            return items

        def _make_offboarding_items(proc, completed_upto):
            items = [ProcessItem(offboarding_process_id=proc.id, description=t.name, item_type='StaticTask')
                     for t in offboarding_global]
            items.append(ProcessItem(offboarding_process_id=proc.id,
                                     description="Return company laptop", item_type='StaticTask'))
            items.append(ProcessItem(offboarding_process_id=proc.id,
                                     description="Disable all corporate accounts", item_type='RevokeAccess'))
            for idx, it in enumerate(items):
                if completed_upto == -1 or idx < completed_upto:
                    it.is_completed = True
            return items

        # 1) Onboarding in progress (Provisioning), starts in a few days
        onb_inprogress = OnboardingProcess(
            new_hire_name='Marcus Lee',
            target_email='marcus.lee@example.com',
            personal_email='marcus.lee.personal@gmail.com',
            start_date=today() + timedelta(days=5),
            status='Provisioning',
            pack_id=pack_dev.id,
            assigned_manager_id=manager_eng.id,
            assigned_buddy_id=buddy_dev.id,
            notes='Backfill for the platform team.'
        )
        # 2) Onboarding completed (started in the past), linked to a real user
        onb_completed = OnboardingProcess(
            new_hire_name=users[8].name,  # Ian Malcolm
            user_id=users[8].id,
            target_email=users[8].email,
            start_date=today() - timedelta(days=20),
            status='Completed',
            pack_id=pack_design.id,
            assigned_manager_id=users[0].id,  # Alice Johnson
            assigned_buddy_id=buddy_design.id
        )
        db.session.add_all([onb_inprogress, onb_completed])
        db.session.flush()
        db.session.add_all(_make_onboarding_items(onb_inprogress, pack_dev, completed_upto=4))
        db.session.add_all(_make_onboarding_items(onb_completed, pack_design, completed_upto=-1))

        # 3) Offboarding in progress, departing soon
        off_inprogress = OffboardingProcess(
            user_id=users[7].id,       # Ethan Hunt
            manager_id=manager_sales.id,
            departure_date=today() + timedelta(days=10),
            status='In Progress',
            notes='Voluntary departure; equipment return pending.'
        )
        # 4) Offboarding completed (departed in the past)
        off_completed = OffboardingProcess(
            user_id=users[6].id,       # Heidi Klum
            manager_id=users[0].id,    # Alice Johnson
            departure_date=today() - timedelta(days=15),
            status='Completed'
        )
        db.session.add_all([off_inprogress, off_completed])
        db.session.flush()
        db.session.add_all(_make_offboarding_items(off_inprogress, completed_upto=2))
        db.session.add_all(_make_offboarding_items(off_completed, completed_upto=-1))
        db.session.commit()

        print("Database seeded successfully!")