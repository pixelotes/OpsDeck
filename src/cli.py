import click
import csv
import os
import secrets
from .utils.helpers import generate_secure_password, get_csv_reader
from datetime import datetime
from .extensions import db
# Import all necessary models
from .models import User, Asset, Peripheral, Location, Supplier, Contact, Software, Subscription, Budget, Risk, RiskCategory, AssetAssignment, PeripheralAssignment
from .models.assets import Brand, AssetModel
from src.utils.timezone_helper import now


def validate_columns(reader, required_columns):
    """Checks if required columns exist in the CSV."""
    if not reader.fieldnames:
        print("❌ Error: The CSV file is empty or has no headers.")
        return False
    
    missing = [col for col in required_columns if col not in reader.fieldnames]
    if missing:
        print(f"❌ Error: Missing required columns: {', '.join(missing)}")
        print(f"ℹ️  Found columns: {', '.join(reader.fieldnames)}")
        return False
    return True


def register_commands(app):
    
    @app.cli.group()
    def data_import():
        """Commands to bulk import data from CSV files."""
        pass

    # --- 1. IMPORT USERS (SECURE MODE) ---
    @data_import.command('users')
    @click.argument('filename')
    def import_users(filename):
        """Imports users from CSV. Columns: name, email"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        from .services.import_service import process
        with open(filename, 'r', encoding='utf-8-sig') as f:
            csv_text = f.read()

        try:
            result = process('users', csv_text, commit=True)
        except ValueError as e:
            print(f"❌ Error: {e}")
            return

        if result['notes']:
            print(f"{'USER':<30} | {'EMAIL':<30} | {'GENERATED PASSWORD'}")
            print("-" * 85)
            for note in result['notes']:
                print(f"{note['name']:<30} | {note['email']:<30} | {note['password']}")
            print("-" * 85)
        c = result['counts']
        print(f"✅ Process finished. Users created: {c['create']}. "
              f"Skipped (already existed): {c['skip']}. Errors: {c['error']}.")

    # --- 2. IMPORT SUPPLIERS ---
    @data_import.command('suppliers')
    @click.argument('filename')
    def import_suppliers(filename):
        """Imports suppliers. Columns: name, email, phone, address, website, compliance_status"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name']):
                return

            count = 0
            skipped = 0
            row_num = 0

            for row in reader:
                row_num += 1
                try:
                    name = row['name'].strip()
                    if not name:
                         print(f"⚠️ Row {row_num}: Skipped missing name.")
                         continue

                    if Supplier.query.filter_by(name=name).first():
                        skipped += 1
                        continue

                    supplier = Supplier(
                        name=name,
                        email=row.get('email'),
                        phone=row.get('phone'),
                        address=row.get('address'),
                        website=row.get('website'),
                        compliance_status=row.get('compliance_status', 'Pending')
                    )
                    db.session.add(supplier)
                    count += 1
                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")

            
            db.session.commit()
            print(f"✅ Suppliers created: {count}. Skipped (already existed): {skipped}.")

    # --- 3. IMPORT CONTACTS ---
    @data_import.command('contacts')
    @click.argument('filename')
    def import_contacts(filename):
        """Imports contacts. Columns: name, email, phone, role, supplier_name"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name', 'supplier_name']):
                return

            count = 0
            row_num = 0
            for row in reader:
                row_num += 1
                try:
                    # Find supplier by name
                    sup_name = row.get('supplier_name', '').strip()
                    if not sup_name:
                        print(f"⚠️ Skipping contact '{row['name']}': missing 'supplier_name'")
                        continue

                    supplier = Supplier.query.filter_by(name=sup_name).first()
                    if not supplier:
                        # Create stub supplier if it doesn't exist
                        supplier = Supplier(name=sup_name, compliance_status='Pending')
                        db.session.add(supplier)
                        db.session.commit() # Commit needed to get ID
                        print(f"🏢 Supplier created automatically: {sup_name}")

                    contact = Contact(
                        name=row['name'],
                        email=row.get('email'),
                        phone=row.get('phone'),
                        role=row.get('role'),
                        supplier_id=supplier.id
                    )
                    db.session.add(contact)
                    count += 1
                
                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")

            db.session.commit()
            print(f"✅ Contacts imported: {count}.")

    # --- 4. IMPORT ASSETS ---
    @data_import.command('assets')
    @click.argument('filename')
    def import_assets(filename):
        """Imports assets. Columns: name, model, brand, serial_number, location_name, status, cost, warranty_length"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name']):
                return

            count = 0
            skipped = 0
            row_num = 0
            for row in reader:
                row_num += 1
                try:
                    # Check for duplicates
                    serial = row.get('serial_number')

                    if serial and Asset.query.filter_by(serial_number=serial).first():
                        print(f"⚠️ Skipped existing asset: {row['name']} ({serial})")
                        skipped += 1
                        continue

                    # User Linking Logic
                    user_id = None
                    assigned_user_name = row.get('assigned_user', '').strip()
                    if assigned_user_name:
                        user_obj = User.query.filter_by(name=assigned_user_name).first()
                        if user_obj:
                            user_id = user_obj.id

                    # Location Logic
                    loc_name = row.get('location_name', '').strip() # Use .strip() for safety
                    location_id = None
                    
                    # Check for "Remote" or virtual locations
                    is_remote = False
                    if loc_name.lower() in ['remote', 'work from home', 'wfh', 'virtual']:
                        is_remote = True
                        # Do not create a location, rely on user link
                    
                    if loc_name and not is_remote:
                        loc = Location.query.filter_by(name=loc_name).first()
                        if not loc:
                            loc = Location(name=loc_name)
                            db.session.add(loc)
                            db.session.commit()
                            print(f"📍 Location created: {loc_name}")
                        location_id = loc.id

                    # Date Parsing Logic
                    p_date = None
                    if row.get('purchase_date'):
                        try:
                            p_date = datetime.strptime(row['purchase_date'], '%Y-%m-%d').date()
                        except ValueError:
                            pass

                    # Resolve/auto-create Brand and AssetModel
                    brand_name = (row.get('brand') or '').strip()
                    model_name = (row.get('model') or '').strip()
                    brand_obj = None
                    model_obj = None
                    if brand_name:
                        brand_obj = Brand.query.filter_by(name=brand_name).first()
                        if not brand_obj:
                            brand_obj = Brand(name=brand_name)
                            db.session.add(brand_obj)
                            db.session.flush()
                            print(f"🏷️  Brand created: {brand_name}")
                    if model_name and brand_obj is not None:
                        model_obj = AssetModel.query.filter_by(name=model_name, brand_id=brand_obj.id).first()
                        if not model_obj:
                            model_obj = AssetModel(name=model_name, brand_id=brand_obj.id)
                            db.session.add(model_obj)
                            db.session.flush()
                            print(f"🧩 Model created: {brand_name} / {model_name}")

                    asset = Asset(
                        name=row['name'],
                        brand_id=brand_obj.id if brand_obj else None,
                        model_id=model_obj.id if model_obj else None,
                        serial_number=row.get('serial_number'),
                        status=row.get('status', 'In Use'),
                        location_id=location_id,
                        user_id=user_id, # Link user
                        purchase_date=p_date,
                        cost=float(row['cost']) if row.get('cost') else 0.0,
                        warranty_length=int(row['warranty_length']) if row.get('warranty_length') else 0
                    )
                    db.session.add(asset)
                    db.session.flush() # Flush to get ID for assignment

                    # Create Assignment if user is linked
                    if user_id:
                        assignment = AssetAssignment(
                            asset_id=asset.id,
                            user_id=user_id,
                            checked_out_date=now(),
                            notes="Imported via CSV"
                        )
                        db.session.add(assignment)
                        
                    count += 1

                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")
            
            db.session.commit()
            print(f"✅ Assets imported: {count}. Skipped: {skipped}.")

    # --- 5. IMPORT PERIPHERALS ---
    @data_import.command('peripherals')
    @click.argument('filename')
    def import_peripherals(filename):
        """Imports peripherals. Columns: name, type, brand, serial_number, status"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name']):
                return

            count = 0
            row_num = 0
            for row in reader:
                row_num += 1
                try:
                    # User Linking Logic
                    user_id = None
                    assigned_user_name = row.get('assigned_user', '').strip()
                    if assigned_user_name:
                        user_obj = User.query.filter_by(name=assigned_user_name).first()
                        if user_obj:
                            user_id = user_obj.id

                    # Location Logic (Added for peripherals)
                    loc_name = row.get('location_name', '').strip()
                    location_id = None
                    
                    is_remote = False
                    if loc_name.lower() in ['remote', 'work from home', 'wfh', 'virtual']:
                        is_remote = True
                    
                    if loc_name and not is_remote:
                        loc = Location.query.filter_by(name=loc_name).first()
                        if not loc:
                            loc = Location(name=loc_name)
                            db.session.add(loc)
                            db.session.commit()
                            print(f"📍 Location created for peripheral: {loc_name}")
                        location_id = loc.id

                    # Resolve/auto-create Brand (peripherals have no model column in CSV)
                    brand_name = (row.get('brand') or '').strip()
                    brand_obj = None
                    if brand_name:
                        brand_obj = Brand.query.filter_by(name=brand_name).first()
                        if not brand_obj:
                            brand_obj = Brand(name=brand_name)
                            db.session.add(brand_obj)
                            db.session.flush()
                            print(f"🏷️  Brand created: {brand_name}")

                    peripheral = Peripheral(
                        name=row['name'],
                        type=row.get('type', 'Accessory'),
                        brand_id=brand_obj.id if brand_obj else None,
                        serial_number=row.get('serial_number'),
                        status=row.get('status', 'In Use'),
                        user_id=user_id, # Link user
                        location_id=location_id
                    )
                    db.session.add(peripheral)
                    db.session.flush() # Flush to get ID

                    # Create Assignment if user is linked
                    if user_id:
                        assignment = PeripheralAssignment(
                            peripheral_id=peripheral.id,
                            user_id=user_id,
                            checked_out_date=now(),
                            notes="Imported via CSV"
                        )
                        db.session.add(assignment)
                        
                    count += 1

                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")
            
            db.session.commit()
            print(f"✅ Peripherals imported: {count}.")

    # --- 6. IMPORT SOFTWARE ---
    @data_import.command('software')
    @click.argument('filename')
    def import_software(filename):
        """Imports software. Columns: name, category, description, supplier_name, owner_email, iso_27001_controls"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name']):
                return

            count = 0
            skipped = 0
            row_num = 0
            for row in reader:
                row_num += 1
                try:
                    name = row['name'].strip()
                    if Software.query.filter_by(name=name).first():
                        skipped += 1
                        continue

                    # Optional Supplier Linking
                    supplier_id = None
                    sup_name = row.get('supplier_name')
                    if sup_name:
                        supplier = Supplier.query.filter_by(name=sup_name.strip()).first()
                        if supplier:
                            supplier_id = supplier.id

                    # Optional Owner Linking (User)
                    owner_id, owner_type = None, None
                    owner_email = row.get('owner_email')
                    if owner_email:
                        user = User.query.filter_by(email=owner_email.strip()).first()
                        if user:
                            owner_id = user.id
                            owner_type = 'user'

                    software = Software(
                        name=name,
                        category=row.get('category'),
                        description=row.get('description'),
                        supplier_id=supplier_id,
                        owner_id=owner_id,
                        owner_type=owner_type,
                        iso_27001_control_references=row.get('iso_27001_controls')
                    )
                    db.session.add(software)
                    count += 1

                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")
            
            db.session.commit()
            print(f"✅ Software imported: {count}. Skipped (already existed): {skipped}.")

    # --- 7. IMPORT SUBSCRIPTIONS ---
    @data_import.command('subscriptions')
    @click.argument('filename')
    def import_subscriptions(filename):
        """Imports subscriptions. Columns: name, type, cost, supplier_name, renewal_date..."""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['supplier_name']):
                return

            count = 0
            skipped_missing_supplier = 0
            row_num = 0
            
            for row in reader:
                row_num += 1
                try:
                    # MANDATORY: Supplier
                    sup_name = row.get('supplier_name', '').strip()

                    if not sup_name:
                        skipped_missing_supplier += 1
                        continue
                        
                    supplier = Supplier.query.filter_by(name=sup_name).first()
                    if not supplier:
                        print(f"⚠️ Skipped '{row.get('name')}': Supplier '{sup_name}' not found.")
                        skipped_missing_supplier += 1
                        continue

                    # Optional Links
                    software_id = None
                    soft_name = row.get('software_name')
                    if soft_name:
                        soft = Software.query.filter_by(name=soft_name.strip()).first()
                        if soft: software_id = soft.id
                    
                    budget_id = None
                    bud_name = row.get('budget_name')
                    if bud_name:
                        bud = Budget.query.filter_by(name=bud_name.strip()).first()
                        if bud: budget_id = bud.id
                    
                    user_id = None
                    u_email = row.get('assigned_user_email')
                    if u_email:
                        u = User.query.filter_by(email=u_email.strip()).first()
                        if u: user_id = u.id

                    # Parsing
                    try:
                        r_date = datetime.strptime(row.get('renewal_date', ''), '%Y-%m-%d').date()
                    except ValueError:
                        r_date = datetime.today().date() # Fallback

                    auto_renew = row.get('auto_renew', '').lower() in ['yes', 'y', 'true', '1']
                    cost = float(row.get('cost')) if row.get('cost') else 0.0

                    sub = Subscription(
                        name=row.get('name'),
                        subscription_type=row.get('type', 'SaaS'),
                        description=row.get('description'),
                        cost=cost,
                        currency=row.get('currency', 'EUR'),
                        renewal_date=r_date,
                        renewal_period_type=row.get('period_type', 'yearly'),
                        renewal_period_value=int(row.get('period_value', 1)),
                        auto_renew=auto_renew,
                        supplier_id=supplier.id,
                        software_id=software_id,
                        budget_id=budget_id,
                        user_id=user_id
                    )
                    db.session.add(sub)
                    count += 1
                
                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")

            db.session.commit()
            print(f"✅ Subscriptions imported: {count}. Skipped (missing supplier): {skipped_missing_supplier}.")

    # --- 8. IMPORT RISKS ---
    @data_import.command('risks')
    @click.argument('filename')
    def import_risks(filename):
        """Imports risks. Columns: name, likelihood, impact, description, category"""
        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return

        with open(filename, 'r', encoding='utf-8') as f:
            reader = get_csv_reader(f)
            if not validate_columns(reader, ['name']):
                return

            count = 0
            row_num = 0
            
            for row in reader:
                row_num += 1
                try:
                    name = row.get('name', '').strip()

                    if not name:
                        continue  # Skip rows without a name

                    try:
                        likelihood = int(row.get('likelihood', 1))
                        impact = int(row.get('impact', 1))
                    except ValueError:
                        print(f"⚠️ Warning: Invalid score for risk '{name}'. Defaulting to 1.")
                        likelihood = 1
                        impact = 1

                    risk = Risk(
                        risk_description=name,
                        inherent_likelihood=likelihood,
                        inherent_impact=impact,
                        residual_likelihood=likelihood, # Default to inherent
                        residual_impact=impact,         # Default to inherent
                        extended_description=row.get('description')
                    )
                    db.session.add(risk)
                    db.session.flush() # Flush to get ID for categories

                    # Category Parsing
                    raw_cats = row.get('category', '')
                    if raw_cats:
                        for cat in raw_cats.split(','):
                            clean_cat = cat.strip()
                            if clean_cat:
                                db.session.add(RiskCategory(risk_id=risk.id, category=clean_cat))
                    
                    count += 1
                
                except Exception as e:
                    print(f"❌ Error on row {row_num}: {e}")

            db.session.commit()
            print(f"✅ Risks imported: {count}.")