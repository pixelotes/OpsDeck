import pytest
from src.models import User, Supplier, Contact, Asset, Peripheral, Location, Software, Subscription, Budget, Risk
from src.extensions import db


@pytest.fixture
def csv_dir(tmp_path):
    """Creates a temporary directory for CSV files."""
    return tmp_path


def _invoke(app, type_key, csv_file):
    return app.test_cli_runner().invoke(args=['data-import', type_key, str(csv_file)])


def test_import_users_basic(app, csv_dir):
    csv_file = csv_dir / "users.csv"
    csv_file.write_text("name,email\nAlice Johnson,alice@example.com\nBob Smith,bob@example.com\n")
    with app.app_context():
        initial_count = User.query.count()

    result = _invoke(app, 'users', csv_file)

    assert result.exit_code == 0
    assert "created 2" in result.output
    assert "alice@example.com" in result.output
    assert "bob@example.com" in result.output

    with app.app_context():
        assert User.query.count() == initial_count + 2
        alice = User.query.filter_by(email='alice@example.com').first()
        assert alice is not None
        assert alice.name == 'Alice Johnson'
        assert alice.role == 'user'
        assert alice.password_hash is not None


def test_import_users_skip_duplicates(app, csv_dir):
    with app.app_context():
        existing_user = User(name='Existing User', email='existing@example.com', role='user')
        existing_user.set_password('password123')
        db.session.add(existing_user)
        db.session.commit()

    csv_file = csv_dir / "users.csv"
    csv_file.write_text("name,email\nExisting User,existing@example.com\nNew User,new@example.com\n")

    result = _invoke(app, 'users', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output
    assert "skipped 1" in result.output


def test_import_users_file_not_found(app):
    result = app.test_cli_runner().invoke(args=['data-import', 'users', 'nonexistent.csv'])
    assert result.exit_code == 0
    assert "Error: File 'nonexistent.csv' not found" in result.output


def test_import_users_password_generation(app, csv_dir):
    csv_file = csv_dir / "users.csv"
    csv_file.write_text("name,email\nUser1,user1@test.com\nUser2,user2@test.com\n")

    result = _invoke(app, 'users', csv_file)
    assert result.exit_code == 0

    passwords = []
    for line in result.output.split('\n'):
        if 'user1@test.com' in line or 'user2@test.com' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                passwords.append(parts[-1].strip())

    assert len(passwords) == 2
    assert passwords[0] != passwords[1]
    assert all(len(p) >= 12 for p in passwords)


def test_import_suppliers_basic(app, csv_dir):
    csv_file = csv_dir / "suppliers.csv"
    csv_file.write_text(
        "name,email,phone,address,compliance_status\n"
        "Acme Corp,contact@acme.com,555-0199,123 Main St,Approved\n"
        "Tech Inc,sales@tech.com,555-0200,456 Oak Ave,Pending\n"
    )

    result = _invoke(app, 'suppliers', csv_file)

    assert result.exit_code == 0
    assert "created 2" in result.output

    with app.app_context():
        acme = Supplier.query.filter_by(name='Acme Corp').first()
        assert acme is not None
        assert acme.email == 'contact@acme.com'
        assert acme.phone == '555-0199'
        assert acme.compliance_status == 'Approved'


def test_import_suppliers_with_website(app, csv_dir):
    csv_file = csv_dir / "suppliers_website.csv"
    csv_file.write_text(
        "name,email,website,compliance_status\nWeb Corp,web@corp.com,https://webcorp.com,Approved\n"
    )

    result = _invoke(app, 'suppliers', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        supplier = Supplier.query.filter_by(name='Web Corp').first()
        assert supplier is not None
        assert supplier.website == 'https://webcorp.com'


def test_import_suppliers_with_semicolon(app, csv_dir):
    csv_file = csv_dir / "suppliers_semicolon.csv"
    csv_file.write_text("name;email;phone;compliance_status\nSemi Corp;semi@corp.com;555-5555;Approved\n")

    result = _invoke(app, 'suppliers', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        supplier = Supplier.query.filter_by(name='Semi Corp').first()
        assert supplier is not None
        assert supplier.email == 'semi@corp.com'


def test_import_suppliers_skip_duplicates(app, csv_dir):
    with app.app_context():
        db.session.add(Supplier(name='Existing Corp', email='test@existing.com'))
        db.session.commit()

    csv_file = csv_dir / "suppliers.csv"
    csv_file.write_text(
        "name,email,phone,compliance_status\n"
        "Existing Corp,duplicate@test.com,555-9999,Approved\n"
        "New Corp,new@corp.com,555-1111,Pending\n"
    )

    result = _invoke(app, 'suppliers', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output
    assert "skipped 1" in result.output


def test_import_contacts_basic(app, csv_dir):
    with app.app_context():
        db.session.add(Supplier(name='Test Supplier', email='supplier@test.com'))
        db.session.commit()

    csv_file = csv_dir / "contacts.csv"
    csv_file.write_text(
        "name,supplier_name,email,phone,role\nJohn Doe,Test Supplier,john@test.com,555-1234,Account Manager\n"
    )

    result = _invoke(app, 'contacts', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        contact = Contact.query.filter_by(email='john@test.com').first()
        assert contact is not None
        assert contact.name == 'John Doe'
        assert contact.role == 'Account Manager'
        assert contact.supplier.name == 'Test Supplier'


def test_import_contacts_auto_create_supplier(app, csv_dir):
    csv_file = csv_dir / "contacts.csv"
    csv_file.write_text("name,supplier_name,email,role\nJane Smith,New Supplier,jane@new.com,Sales Lead\n")

    result = _invoke(app, 'contacts', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        supplier = Supplier.query.filter_by(name='New Supplier').first()
        assert supplier is not None
        assert supplier.compliance_status == 'Pending'


def test_import_contacts_missing_supplier_name(app, csv_dir):
    csv_file = csv_dir / "contacts.csv"
    csv_file.write_text("name,supplier_name,email\nInvalid Contact,,invalid@test.com\n")

    result = _invoke(app, 'contacts', csv_file)

    assert result.exit_code == 0
    assert "errors 1" in result.output
    assert "Missing supplier_name" in result.output


def test_import_assets_basic(app, csv_dir):
    csv_file = csv_dir / "assets.csv"
    csv_file.write_text(
        "name,model,brand,serial_number,location_name,status,cost,purchase_date,warranty_length\n"
        "MacBook Pro,MBP16,Apple,C02XYZ123,HQ Office,In Use,2499.00,2023-01-15,24\n"
    )

    result = _invoke(app, 'assets', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        asset = Asset.query.filter_by(serial_number='C02XYZ123').first()
        assert asset is not None
        assert asset.name == 'MacBook Pro'
        assert asset.brand.name == 'Apple'
        assert asset.model.name == 'MBP16'
        assert abs(asset.cost - 2499.00) < 0.01
        assert asset.warranty_length == 24
        assert asset.location.name == 'HQ Office'


def test_import_assets_requires_serial(app, csv_dir):
    """serial_number is now required (matches the GUI)."""
    csv_file = csv_dir / "assets.csv"
    csv_file.write_text("name,serial_number,location_name,status,cost\nNo Serial Asset,,New Location,In Stock,100.00\n")

    result = _invoke(app, 'assets', csv_file)

    assert result.exit_code == 0
    assert "errors 1" in result.output
    assert "Missing serial_number" in result.output
    with app.app_context():
        assert Asset.query.filter_by(name='No Serial Asset').first() is None


def test_import_assets_auto_create_location(app, csv_dir):
    csv_file = csv_dir / "assets.csv"
    csv_file.write_text(
        "name,serial_number,location_name,status,cost\nTest Asset,SN-LOC-1,New Location,In Stock,100.00\n"
    )

    result = _invoke(app, 'assets', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        assert Location.query.filter_by(name='New Location').first() is not None


def test_import_assets_invalid_date(app, csv_dir):
    csv_file = csv_dir / "assets.csv"
    csv_file.write_text("name,serial_number,purchase_date,cost\nTest Asset,SN-DATE-1,invalid-date,100.00\n")

    result = _invoke(app, 'assets', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output

    with app.app_context():
        asset = Asset.query.filter_by(name='Test Asset').first()
        assert asset is not None
        assert asset.purchase_date is None


def test_import_assets_skip_duplicates(app, csv_dir):
    with app.app_context():
        db.session.add(Asset(name='Existing Asset', serial_number='SN123', status='In Use', cost=100.0))
        db.session.commit()

    csv_file = csv_dir / "assets.csv"
    csv_file.write_text("name,serial_number,cost\nExisting Asset,SN123,500.00\nNew Asset,SN456,200.00\n")

    result = _invoke(app, 'assets', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output
    assert "skipped 1" in result.output
    assert "serial number already exists" in result.output

    with app.app_context():
        assert abs(Asset.query.filter_by(serial_number='SN123').first().cost - 100.0) < 0.01  # not updated
        assert Asset.query.filter_by(serial_number='SN456').first() is not None


def test_import_peripherals_basic(app, csv_dir):
    csv_file = csv_dir / "peripherals.csv"
    csv_file.write_text(
        "name,type,brand,serial_number,status\n"
        "Dell Monitor 27,Monitor,Dell,CN-0X123,In Use\n"
        "Logitech Mouse,Mouse,Logitech,SN998877,In Stock\n"
    )

    result = _invoke(app, 'peripherals', csv_file)

    assert result.exit_code == 0
    assert "created 2" in result.output

    with app.app_context():
        monitor = Peripheral.query.filter_by(serial_number='CN-0X123').first()
        assert monitor is not None
        assert monitor.name == 'Dell Monitor 27'
        assert monitor.type == 'Monitor'
        assert monitor.brand.name == 'Dell'


def test_import_peripherals_default_values(app, csv_dir):
    csv_file = csv_dir / "peripherals.csv"
    csv_file.write_text("name,serial_number\nGeneric Peripheral,GP-1\n")

    result = _invoke(app, 'peripherals', csv_file)

    assert result.exit_code == 0

    with app.app_context():
        peripheral = Peripheral.query.filter_by(name='Generic Peripheral').first()
        assert peripheral is not None
        assert peripheral.type == 'Accessory'  # default
        assert peripheral.status == 'In Use'   # default


def test_import_software_basic(app, csv_dir):
    with app.app_context():
        db.session.add(Supplier(name='Adobe', email='support@adobe.com'))
        user = User(name='IT Manager', email='it@example.com', role='admin')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

    csv_file = csv_dir / "software.csv"
    csv_file.write_text(
        "name,category,description,supplier_name,owner_email\n"
        "Adobe Creative Cloud,Design,Creative Suite,Adobe,it@example.com\n"
        "Slack,Communication,Chat app,Unknown Supplier,unknown@example.com\n"
    )

    result = _invoke(app, 'software', csv_file)

    assert result.exit_code == 0
    assert "created 2" in result.output

    with app.app_context():
        adobe = Software.query.filter_by(name='Adobe Creative Cloud').first()
        assert adobe is not None
        assert adobe.supplier.name == 'Adobe'
        assert adobe.owner.email == 'it@example.com'

        slack = Software.query.filter_by(name='Slack').first()
        assert slack is not None
        assert slack.supplier_id is None
        assert slack.owner_id is None


def test_import_subscriptions_basic(app, csv_dir):
    with app.app_context():
        db.session.add(Supplier(name='Microsoft', email='ms@example.com'))
        db.session.add(Software(name='Office 365', category='Productivity'))
        db.session.add(Budget(name='IT Budget 2024', amount=10000.0))
        user = User(name='Jane Doe', email='jane@example.com', role='user')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()

    csv_file = csv_dir / "subscriptions.csv"
    csv_file.write_text(
        "name,type,cost,supplier_name,renewal_date,period_type,software_name,budget_name,assigned_user_email,auto_renew\n"
        "M365 Business,SaaS,150.00,Microsoft,2025-01-01,monthly,Office 365,IT Budget 2024,jane@example.com,yes\n"
        "Invalid Sub,SaaS,100.00,Missing Supplier,2025-01-01,yearly,,,,no\n"
    )

    result = _invoke(app, 'subscriptions', csv_file)

    assert result.exit_code == 0
    assert "created 1" in result.output
    assert "skipped 1" in result.output

    with app.app_context():
        sub = Subscription.query.filter_by(name='M365 Business').first()
        assert sub is not None
        assert abs(sub.cost - 150.00) < 0.01
        assert sub.supplier.name == 'Microsoft'
        assert sub.software.name == 'Office 365'
        assert sub.budget.name == 'IT Budget 2024'
        assert sub.user.email == 'jane@example.com'
        assert sub.auto_renew is True


def test_import_risks_basic(app, csv_dir):
    csv_file = csv_dir / "risks.csv"
    csv_file.write_text(
        "name,likelihood,impact,description,category\n"
        "Data Breach,4,5,Unauthorized access to sensitive data,\"Confidentiality, Legal\"\n"
        "Server Outage,3,4,Data center power loss,Availability\n"
    )

    result = _invoke(app, 'risks', csv_file)

    assert result.exit_code == 0
    assert "created 2" in result.output

    with app.app_context():
        breach = Risk.query.filter_by(risk_description='Data Breach').first()
        assert breach is not None
        assert breach.inherent_likelihood == 4
        assert breach.inherent_impact == 5
        assert breach.residual_likelihood == 4
        assert breach.residual_impact == 5
        assert breach.extended_description == 'Unauthorized access to sensitive data'
        cats = [c.category for c in breach.categories]
        assert 'Confidentiality' in cats
        assert 'Legal' in cats

        outage = Risk.query.filter_by(risk_description='Server Outage').first()
        assert outage is not None
        assert outage.categories.first().category == 'Availability'


def test_import_risks_validation(app, csv_dir):
    with app.app_context():
        initial_count = Risk.query.count()

    csv_file = csv_dir / "risks.csv"
    csv_file.write_text("name,likelihood,impact\n,5,5\nValid Risk,5,5\n")

    result = _invoke(app, 'risks', csv_file)

    assert result.exit_code == 0
    with app.app_context():
        assert Risk.query.count() == initial_count + 1
        assert Risk.query.filter_by(risk_description='Valid Risk').first() is not None


def test_cli_has_command_per_importer(app):
    """The CLI exposes the same set of types as the admin Import screen."""
    from src.services.import_service import IMPORTERS
    runner = app.test_cli_runner()
    help_out = runner.invoke(args=['data-import', '--help']).output
    for key in IMPORTERS:
        assert key in help_out
