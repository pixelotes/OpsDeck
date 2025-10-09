import random
from datetime import date, timedelta
from faker import Faker
from .models import db, Supplier, Contact, User, Location, PaymentMethod, Tag, Budget, Purchase, Asset, Peripheral, Service, CostHistory
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
        print("Creating core entities (Suppliers, Locations, Payment Methods, Tags)...")
        suppliers = [
            Supplier(name='Adobe', email='sales@adobe.com', phone='800-833-6687'),
            Supplier(name='Microsoft', email='support@microsoft.com', phone='800-642-7676'),
            Supplier(name='Dell Technologies', email='sales@dell.com', phone='877-275-3355'),
            Supplier(name='Slack (Salesforce)', email='feedback@slack.com', phone='415-579-9122'),
            Supplier(name='Atlassian', email='sales@atlassian.com', phone='800-804-5281'),
            Supplier(name='Zoom', email='info@zoom.us', phone='888-799-9666'),
            Supplier(name='Apple', email='business@apple.com', phone='800-854-3680'),
            Supplier(name='Logitech', email='support@logi.com', phone='646-454-3200'),
            Supplier(name='Amazon Web Services', email='aws-sales@amazon.com'),
            Supplier(name='Namecheap', email='support@namecheap.com'),
            Supplier(name='Figma', email='sales@figma.com'),
            Supplier(name='Herman Miller', email='info@hermanmiller.com')
        ]
        db.session.add_all(suppliers)
        db.session.commit()

        locations = [Location(name='Headquarters - NYC'), Location(name='London Office'), Location(name='San Francisco Hub'), Location(name='Remote (Home Office)')]
        payment_methods = [
            PaymentMethod(name='Corp AMEX - 1005', method_type='Credit Card', details='Ends in 1005'),
            PaymentMethod(name='IT Dept Visa - 4554', method_type='Credit Card', details='Ends in 4554'),
            PaymentMethod(name='Bank Transfer (ACH)', method_type='Bank Transfer')
        ]
        tags = [Tag(name='SaaS'), Tag(name='Hardware'), Tag(name='Marketing'), Tag(name='Development'), Tag(name='Office Supply'), Tag(name='Cloud Infrastructure'), Tag(name='Design')]
        
        db.session.add_all(locations)
        db.session.add_all(payment_methods)
        db.session.add_all(tags)
        db.session.commit()

        # 2. Create People (Users & Contacts)
        print("Creating users and contacts...")
        users = [
            User(name='Alice Johnson', email='alice.j@example.com', department='Engineering', job_title='Lead Developer'),
            User(name='Bob Williams', email='bob.w@example.com', department='Marketing', job_title='Marketing Director'),
            User(name='Charlie Brown', email='charlie.b@example.com', department='Engineering', job_title='Frontend Developer'),
            User(name='Diana Prince', email='diana.p@example.com', department='Design', job_title='UX/UI Designer'),
            User(name='Ethan Hunt', email='ethan.h@example.com', department='Sales', job_title='Account Executive'),
        ]
        db.session.add_all(users)
        
        contacts = [
            Contact(name='John Smith', email='john.s@adobe.com', role='Account Manager', supplier=suppliers[0]),
            Contact(name='Jane Doe', email='jane.d@microsoft.com', role='Support Specialist', supplier=suppliers[1]),
            Contact(name='Peter Jones', email='peter.j@atlassian.com', role='Billing', supplier=suppliers[4]),
            Contact(name='Susan Storm', email='susan.s@aws.com', role='Cloud Specialist', supplier=suppliers[8]),
        ]
        db.session.add_all(contacts)
        db.session.commit()

        # 3. Create Budgets and Purchases
        print("Creating budgets and purchases...")
        budgets = [
            Budget(name='IT Hardware 2025', category='IT', amount=75000, currency='EUR', period='Yearly'),
            Budget(name='Software & SaaS 2025', category='Software', amount=150000, currency='EUR', period='Yearly'),
            Budget(name='Office Furniture 2025', category='Facilities', amount=20000, currency='USD', period='Yearly'),
        ]
        db.session.add_all(budgets)

        purchase1 = Purchase(description='Annual Adobe Creative Cloud Subscription', purchase_date=date(2024, 11, 1), cost=15000, currency='EUR', supplier=suppliers[0], payment_method=payment_methods[0], budget=budgets[1])
        purchase2 = Purchase(description='New Developer Laptops Q4', purchase_date=date(2024, 10, 15), cost=12500, currency='EUR', supplier=suppliers[2], payment_method=payment_methods[1], budget=budgets[0])
        purchase3 = Purchase(description='Jira & Confluence Cloud Annual', purchase_date=date(2025, 1, 5), cost=25000, currency='USD', supplier=suppliers[4], payment_method=payment_methods[2], budget=budgets[1])
        purchase4 = Purchase(description='New Macbooks for Design Team', purchase_date=date(2025, 2, 20), cost=8000, currency='EUR', supplier=suppliers[6], payment_method=payment_methods[0], budget=budgets[0])
        purchase5 = Purchase(description='Ergonomic Chairs for Engineering', purchase_date=date(2025, 3, 10), cost=5000, currency='USD', supplier=suppliers[11], payment_method=payment_methods[1], budget=budgets[2])
        db.session.add_all([purchase1, purchase2, purchase3, purchase4, purchase5])
        db.session.commit()
        
        # 4. Create Assets and Peripherals
        print("Creating assets and peripherals...")
        assets = [
            Asset(name='DEV-LT-001', brand='Dell', model='XPS 15', serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[0], location=locations[0], supplier=suppliers[2], price=2500, warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DEV-LT-002', brand='Dell', model='XPS 15', serial_number=fake.uuid4(), status='In Use', purchase=purchase2, user=users[2], location=locations[0], supplier=suppliers[2], price=2500, warranty_length=36, purchase_date=purchase2.purchase_date),
            Asset(name='DSN-LT-001', brand='Apple', model='MacBook Pro 16"', serial_number=fake.uuid4(), status='In Use', purchase=purchase4, user=users[3], location=locations[1], supplier=suppliers[6], price=3200, warranty_length=24, purchase_date=purchase4.purchase_date),
            Asset(name='SALES-LT-001', brand='Microsoft', model='Surface Laptop 5', serial_number=fake.uuid4(), status='In Storage', location=locations[0], supplier=suppliers[1], price=1800, warranty_length=24, purchase_date=date(2024, 5, 5)),
            Asset(name='CONF-TV-NYC', brand='Samsung', model='The Frame 75"', serial_number=fake.uuid4(), status='In Use', location=locations[0]),
            Asset(name='PHONE-001', brand='Apple', model='iPhone 15 Pro', serial_number=fake.uuid4(), status='In Use', user=users[1], location=locations[2]),
            Asset(name='TABLET-001', brand='Apple', model='iPad Pro 11"', serial_number=fake.uuid4(), status='In Use', user=users[3], location=locations[1]),
            Asset(name='OFFICE-CHAIR-01', brand='Herman Miller', model='Aeron', serial_number=fake.uuid4(), status='In Use', purchase=purchase5, user=users[0], location=locations[0]),
            Asset(name='OFFICE-CHAIR-02', brand='Herman Miller', model='Aeron', serial_number=fake.uuid4(), status='In Use', purchase=purchase5, user=users[2], location=locations[0]),
        ]
        db.session.add_all(assets)
        db.session.commit()

        peripherals = [
            Peripheral(name='Keyboard-001', type='Keyboard', brand='Logitech', serial_number=fake.uuid4(), asset=assets[0], user=users[0], purchase_date=assets[0].purchase_date, warranty_length=24, supplier=suppliers[7]),
            Peripheral(name='Mouse-001', type='Mouse', brand='Logitech', serial_number=fake.uuid4(), asset=assets[0], user=users[0], purchase_date=assets[0].purchase_date, warranty_length=24, supplier=suppliers[7]),
            Peripheral(name='Monitor-001', type='Monitor', brand='Dell', serial_number=fake.uuid4(), asset=assets[0], user=users[0], purchase_date=assets[0].purchase_date, warranty_length=36, supplier=suppliers[2]),
            Peripheral(name='Keyboard-002', type='Keyboard', brand='Logitech', serial_number=fake.uuid4(), asset=assets[1], user=users[2]),
            Peripheral(name='Mouse-002', type='Mouse', brand='Logitech', serial_number=fake.uuid4(), asset=assets[1], user=users[2]),
            Peripheral(name='Monitor-002', type='Monitor', brand='Dell', serial_number=fake.uuid4(), asset=assets[1], user=users[2]),
            Peripheral(name='Webcam-CONF-NYC', type='Webcam', brand='Logitech', serial_number=fake.uuid4(), asset=assets[4], purchase_date=date(2024, 1, 1), warranty_length=12),
            Peripheral(name='Apple Pencil', type='Stylus', brand='Apple', serial_number=fake.uuid4(), asset=assets[6], user=users[3]),
        ]
        db.session.add_all(peripherals)
        db.session.commit()
        
        # 5. Create Services
        print("Creating services and their cost history...")
        services_data = [
            {'name': 'Adobe Creative Cloud', 'type': 'Software', 'renewal': date(2025, 11, 1), 'period': 'yearly', 'cost': 15000, 'currency': 'EUR', 'supplier': suppliers[0], 'tags': [tags[0], tags[6]], 'auto_renew': True},
            {'name': 'Microsoft 365 E5', 'type': 'SaaS', 'renewal': date(2026, 1, 1), 'period': 'yearly', 'cost': 35000, 'currency': 'USD', 'supplier': suppliers[1], 'tags': [tags[0]], 'auto_renew': True},
            {'name': 'Slack Business+', 'type': 'SaaS', 'renewal': date.today() + timedelta(days=20), 'period': 'monthly', 'cost': 1200, 'currency': 'EUR', 'supplier': suppliers[3], 'tags': [tags[0]], 'auto_renew': True},
            {'name': 'Jira & Confluence Cloud', 'type': 'SaaS', 'renewal': date(2026, 1, 5), 'period': 'yearly', 'cost': 25000, 'currency': 'USD', 'supplier': suppliers[4], 'tags': [tags[0], tags[3]], 'auto_renew': True},
            {'name': 'Zoom Business', 'type': 'SaaS', 'renewal': date.today() + timedelta(days=45), 'period': 'yearly', 'cost': 2000, 'currency': 'EUR', 'supplier': suppliers[5], 'tags': [tags[0]], 'auto_renew': False},
            {'name': 'AWS Hosting', 'type': 'Cloud', 'renewal': date(date.today().year, date.today().month, 1), 'period': 'monthly', 'cost': 500, 'currency': 'USD', 'supplier': suppliers[8], 'tags': [tags[5], tags[3]], 'auto_renew': True},
            {'name': 'Figma Organization Plan', 'type': 'SaaS', 'renewal': date(2026, 3, 1), 'period': 'yearly', 'cost': 8000, 'currency': 'USD', 'supplier': suppliers[10], 'tags': [tags[0], tags[6]], 'auto_renew': True},
            {'name': 'companydomain.com', 'type': 'Domain', 'renewal': date(2027, 8, 15), 'period': 'yearly', 'cost': 15, 'currency': 'USD', 'supplier': suppliers[9], 'tags': [], 'auto_renew': True},
        ]
        
        for data in services_data:
            service = Service(
                name=data['name'], service_type=data['type'], renewal_date=data['renewal'],
                renewal_period_type=data['period'], cost=data['cost'], currency=data['currency'],
                supplier=data['supplier'],
                auto_renew=data.get('auto_renew', False) # Get the value, default to False
            )
            service.tags.extend(data['tags'])
            db.session.add(service)
            db.session.commit()

            history_past = CostHistory(service=service, cost=data['cost'] * random.uniform(0.8, 0.95), currency=data['currency'], changed_date=data['renewal'] - timedelta(days=365))
            history_current = CostHistory(service=service, cost=data['cost'], currency=data['currency'], changed_date=data['renewal'])
            db.session.add_all([history_past, history_current])

        db.session.commit()
        print("Database seeding complete!")