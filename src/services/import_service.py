"""Reusable bulk CSV import service (shared by the admin UI and the CLI).

A registry declares, per importable type, its columns, a sample row for the
downloadable template, and a per-row handler. ``process()`` parses CSV text,
classifies every row as create/skip/error and — when ``commit=True`` —
persists (auto-creating dependencies like locations/brands/suppliers, mirroring
the ``flask data-import`` commands which now delegate here).

Adding a new importable type = add one entry to ``IMPORTERS`` (+ its handler).
"""
import csv
import io
from datetime import datetime

from ..extensions import db
from ..models import (
    User, Supplier, Contact, Asset, AssetAssignment, Peripheral,
    PeripheralAssignment, Location, Software, Subscription, Budget,
    Risk, RiskCategory,
)
from ..models.assets import Brand, AssetModel
from ..utils.helpers import generate_secure_password, get_csv_reader
from src.utils.timezone_helper import today, now

MAX_ROWS = 5000
_REMOTE_LOCATIONS = {'remote', 'work from home', 'wfh', 'virtual'}


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _read_rows(csv_text):
    reader = get_csv_reader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError('The CSV file has no header row.')
    fieldnames = [(f or '').strip() for f in reader.fieldnames]
    rows = []
    for raw in reader:
        rows.append({(k or '').strip(): (v.strip() if isinstance(v, str) else v)
                     for k, v in raw.items()})
    return fieldnames, rows


def _parse_date(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _user_id_by_name(name):
    name = (name or '').strip()
    if not name:
        return None
    user = User.query.filter_by(name=name).first()
    return user.id if user else None


def _resolve_location_id(ctx, name):
    """Get-or-create a Location by name (None for blank/remote). Caches per run."""
    name = (name or '').strip()
    if not name or name.lower() in _REMOTE_LOCATIONS:
        return None
    cache = ctx.setdefault('_loc', {})
    if name in cache:
        return cache[name]
    loc = Location.query.filter_by(name=name).first()
    if not loc:
        loc = Location(name=name)
        db.session.add(loc)
        db.session.flush()
    cache[name] = loc.id
    return loc.id


def _resolve_brand(ctx, name):
    name = (name or '').strip()
    if not name:
        return None
    cache = ctx.setdefault('_brand', {})
    if name in cache:
        return cache[name]
    brand = Brand.query.filter_by(name=name).first()
    if not brand:
        brand = Brand(name=name)
        db.session.add(brand)
        db.session.flush()
    cache[name] = brand
    return brand


def _resolve_model(ctx, brand, name):
    name = (name or '').strip()
    if not name or brand is None:
        return None
    cache = ctx.setdefault('_model', {})
    key = (brand.id, name)
    if key in cache:
        return cache[key]
    model = AssetModel.query.filter_by(name=name, brand_id=brand.id).first()
    if not model:
        model = AssetModel(name=name, brand_id=brand.id)
        db.session.add(model)
        db.session.flush()
    cache[key] = model
    return model


# --------------------------------------------------------------------------- #
# Per-type handlers: (row, ctx, persist) -> (status, message, note)
#   status in {'create','skip','error'}; note is an optional dict (e.g. password)
# --------------------------------------------------------------------------- #
def _users_init(_rows):
    return {'existing': {e.lower() for (e,) in db.session.query(User.email).all() if e},
            'seen': set()}


def _users_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    email = (row.get('email') or '').strip()
    if not name or not email:
        return 'error', 'Missing name or email', None
    key = email.lower()
    if key in ctx['existing'] or key in ctx['seen']:
        return 'skip', 'A user with this email already exists', None
    ctx['seen'].add(key)
    note = None
    if persist:
        password = generate_secure_password()
        user = User(name=name, email=email, role='user')  # role forced for safety
        user.set_password(password)
        db.session.add(user)
        note = {'name': name, 'email': email, 'password': password}
    return 'create', 'Created' if persist else 'Will be created', note


def _suppliers_init(_rows):
    return {'existing': {n for (n,) in db.session.query(Supplier.name).all() if n}, 'seen': set()}


def _suppliers_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    if name in ctx['existing'] or name in ctx['seen']:
        return 'skip', 'A supplier with this name already exists', None
    ctx['seen'].add(name)
    if persist:
        db.session.add(Supplier(
            name=name,
            email=row.get('email') or None,
            phone=row.get('phone') or None,
            address=row.get('address') or None,
            website=row.get('website') or None,
            compliance_status=(row.get('compliance_status') or 'Pending'),
        ))
    return 'create', 'Created' if persist else 'Will be created', None


def _contacts_init(_rows):
    return {'suppliers': {n for (n,) in db.session.query(Supplier.name).all() if n}}


def _contacts_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    sup_name = (row.get('supplier_name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    if not sup_name:
        return 'error', 'Missing supplier_name', None
    if persist:
        supplier = Supplier.query.filter_by(name=sup_name).first()
        if not supplier:
            supplier = Supplier(name=sup_name, compliance_status='Pending')
            db.session.add(supplier)
            db.session.flush()
        db.session.add(Contact(
            name=name,
            email=row.get('email') or None,
            phone=row.get('phone') or None,
            role=row.get('role') or None,
            supplier_id=supplier.id,
        ))
    message = 'Created' if persist else 'Will be created'
    if not persist and sup_name not in ctx['suppliers']:
        message += f" (supplier '{sup_name}' will be created)"
    return 'create', message, None


def _assets_init(_rows):
    return {'serials': {s for (s,) in db.session.query(Asset.serial_number).all() if s},
            'seen_serials': set()}


def _assets_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    serial = (row.get('serial_number') or '').strip()
    if serial and (serial in ctx['serials'] or serial in ctx['seen_serials']):
        return 'skip', 'An asset with this serial number already exists', None
    if serial:
        ctx['seen_serials'].add(serial)
    if persist:
        user_id = _user_id_by_name(row.get('assigned_user'))
        location_id = _resolve_location_id(ctx, row.get('location_name'))
        brand = _resolve_brand(ctx, row.get('brand'))
        model = _resolve_model(ctx, brand, row.get('model'))
        asset = Asset(
            name=name,
            brand_id=brand.id if brand else None,
            model_id=model.id if model else None,
            serial_number=serial or None,
            status=(row.get('status') or 'In Use'),
            location_id=location_id,
            user_id=user_id,
            purchase_date=_parse_date(row.get('purchase_date')),
            cost=float(row['cost']) if row.get('cost') else 0.0,
            warranty_length=int(row['warranty_length']) if row.get('warranty_length') else 0,
        )
        db.session.add(asset)
        db.session.flush()
        if user_id:
            db.session.add(AssetAssignment(asset_id=asset.id, user_id=user_id,
                                           checked_out_date=now(), notes='Imported via CSV'))
    return 'create', 'Created' if persist else 'Will be created', None


def _peripherals_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    if persist:
        user_id = _user_id_by_name(row.get('assigned_user'))
        location_id = _resolve_location_id(ctx, row.get('location_name'))
        brand = _resolve_brand(ctx, row.get('brand'))
        peripheral = Peripheral(
            name=name,
            type=(row.get('type') or 'Accessory'),
            brand_id=brand.id if brand else None,
            serial_number=row.get('serial_number') or None,
            status=(row.get('status') or 'In Use'),
            user_id=user_id,
            location_id=location_id,
        )
        db.session.add(peripheral)
        db.session.flush()
        if user_id:
            db.session.add(PeripheralAssignment(peripheral_id=peripheral.id, user_id=user_id,
                                                checked_out_date=now(), notes='Imported via CSV'))
    return 'create', 'Created' if persist else 'Will be created', None


def _software_init(_rows):
    return {'existing': {n for (n,) in db.session.query(Software.name).all() if n}, 'seen': set()}


def _software_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    if name in ctx['existing'] or name in ctx['seen']:
        return 'skip', 'Software with this name already exists', None
    ctx['seen'].add(name)
    if persist:
        supplier_id = None
        sup_name = (row.get('supplier_name') or '').strip()
        if sup_name:
            supplier = Supplier.query.filter_by(name=sup_name).first()
            supplier_id = supplier.id if supplier else None
        owner_id, owner_type = None, None
        owner_email = (row.get('owner_email') or '').strip()
        if owner_email:
            owner = User.query.filter_by(email=owner_email).first()
            if owner:
                owner_id, owner_type = owner.id, 'user'
        db.session.add(Software(
            name=name,
            category=row.get('category') or None,
            description=row.get('description') or None,
            supplier_id=supplier_id,
            owner_id=owner_id,
            owner_type=owner_type,
            iso_27001_control_references=row.get('iso_27001_controls') or None,
        ))
    return 'create', 'Created' if persist else 'Will be created', None


def _subscriptions_init(_rows):
    return {'suppliers': {n for (n,) in db.session.query(Supplier.name).all() if n}}


def _subscriptions_handle(row, ctx, persist):
    sup_name = (row.get('supplier_name') or '').strip()
    if not sup_name:
        return 'error', 'Missing supplier_name', None
    if sup_name not in ctx['suppliers']:
        return 'skip', f"Supplier '{sup_name}' not found (create it first)", None
    if persist:
        supplier = Supplier.query.filter_by(name=sup_name).first()
        software_id = None
        soft_name = (row.get('software_name') or '').strip()
        if soft_name:
            soft = Software.query.filter_by(name=soft_name).first()
            software_id = soft.id if soft else None
        budget_id = None
        bud_name = (row.get('budget_name') or '').strip()
        if bud_name:
            bud = Budget.query.filter_by(name=bud_name).first()
            budget_id = bud.id if bud else None
        user_id = None
        u_email = (row.get('assigned_user_email') or '').strip()
        if u_email:
            user = User.query.filter_by(email=u_email).first()
            user_id = user.id if user else None
        db.session.add(Subscription(
            name=row.get('name') or None,
            subscription_type=(row.get('type') or 'SaaS'),
            description=row.get('description') or None,
            cost=float(row['cost']) if row.get('cost') else 0.0,
            currency=(row.get('currency') or 'EUR'),
            renewal_date=_parse_date(row.get('renewal_date')) or today(),
            renewal_period_type=(row.get('period_type') or 'yearly'),
            renewal_period_value=int(row['period_value']) if row.get('period_value') else 1,
            auto_renew=(row.get('auto_renew') or '').lower() in {'yes', 'y', 'true', '1'},
            supplier_id=supplier.id,
            software_id=software_id,
            budget_id=budget_id,
            user_id=user_id,
        ))
    return 'create', 'Created' if persist else 'Will be created', None


def _risks_handle(row, _ctx, persist):
    name = (row.get('name') or '').strip()
    if not name:
        return 'error', 'Missing name', None
    try:
        likelihood = int(row['likelihood']) if row.get('likelihood') else 1
        impact = int(row['impact']) if row.get('impact') else 1
    except ValueError:
        likelihood, impact = 1, 1
    if persist:
        risk = Risk(
            risk_description=name,
            inherent_likelihood=likelihood,
            inherent_impact=impact,
            residual_likelihood=likelihood,
            residual_impact=impact,
            extended_description=row.get('description') or None,
        )
        db.session.add(risk)
        db.session.flush()
        for raw_cat in (row.get('category') or '').split(','):
            cat = raw_cat.strip()
            if cat:
                db.session.add(RiskCategory(risk_id=risk.id, category=cat))
    return 'create', 'Created' if persist else 'Will be created', None


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
IMPORTERS = {
    'users': {
        'label': 'Users',
        'description': 'Create user accounts. New users get the "user" role and a generated password (shown once).',
        'required': ['name', 'email'],
        'optional': [],
        'sample': [{'name': 'Jane Doe', 'email': 'jane.doe@example.com'},
                   {'name': 'John Smith', 'email': 'john.smith@example.com'}],
        'note_label': 'Generated passwords',
        'init': _users_init,
        'handle': _users_handle,
    },
    'suppliers': {
        'label': 'Suppliers',
        'description': 'Create suppliers/vendors. Skips names that already exist.',
        'required': ['name'],
        'optional': ['email', 'phone', 'address', 'website', 'compliance_status'],
        'sample': [{'name': 'Acme Corp', 'email': 'sales@acme.com', 'phone': '+1 555 0100',
                    'address': '1 Main St', 'website': 'https://acme.com', 'compliance_status': 'Approved'}],
        'init': _suppliers_init,
        'handle': _suppliers_handle,
    },
    'contacts': {
        'label': 'Contacts',
        'description': 'Create supplier contacts. The supplier is matched by name (created if missing).',
        'required': ['name', 'supplier_name'],
        'optional': ['email', 'phone', 'role'],
        'sample': [{'name': 'Jane Roe', 'supplier_name': 'Acme Corp', 'email': 'jane@acme.com',
                    'phone': '+1 555 0101', 'role': 'Account Manager'}],
        'init': _contacts_init,
        'handle': _contacts_handle,
    },
    'assets': {
        'label': 'Assets',
        'description': ('Create hardware assets. Brand/model/location are matched by name and created if '
                        'missing; assigned_user (by name) creates a checkout. Skips existing serial numbers.'),
        'required': ['name'],
        'optional': ['brand', 'model', 'serial_number', 'status', 'location_name',
                     'assigned_user', 'purchase_date', 'cost', 'warranty_length'],
        'sample': [{'name': 'Laptop 001', 'brand': 'Dell', 'model': 'XPS 13', 'serial_number': 'SN-001',
                    'status': 'In Use', 'location_name': 'HQ', 'assigned_user': 'Alice Johnson',
                    'purchase_date': '2025-01-15', 'cost': '1200', 'warranty_length': '36'}],
        'init': _assets_init,
        'handle': _assets_handle,
    },
    'peripherals': {
        'label': 'Peripherals',
        'description': 'Create peripherals. Brand/location matched by name (created if missing); assigned_user creates a checkout.',
        'required': ['name'],
        'optional': ['type', 'brand', 'serial_number', 'status', 'location_name', 'assigned_user'],
        'sample': [{'name': 'Keyboard 001', 'type': 'Keyboard', 'brand': 'Logitech', 'serial_number': 'KB-001',
                    'status': 'In Use', 'location_name': 'HQ', 'assigned_user': 'Alice Johnson'}],
        'handle': _peripherals_handle,
    },
    'software': {
        'label': 'Software',
        'description': 'Create software entries. Skips names that already exist; supplier/owner matched by name/email if present.',
        'required': ['name'],
        'optional': ['category', 'description', 'supplier_name', 'owner_email', 'iso_27001_controls'],
        'sample': [{'name': 'Figma', 'category': 'Design', 'description': 'UI design tool',
                    'supplier_name': 'Figma Inc', 'owner_email': 'diana.p@example.com', 'iso_27001_controls': 'A.8.1'}],
        'init': _software_init,
        'handle': _software_handle,
    },
    'subscriptions': {
        'label': 'Subscriptions',
        'description': ('Create subscriptions. supplier_name is required and must already exist. '
                        'software/budget/assigned_user are linked by name/email if present.'),
        'required': ['supplier_name'],
        'optional': ['name', 'type', 'cost', 'currency', 'renewal_date', 'period_type', 'period_value',
                     'software_name', 'budget_name', 'assigned_user_email', 'auto_renew', 'description'],
        'sample': [{'supplier_name': 'Adobe', 'name': 'Creative Cloud', 'type': 'SaaS', 'cost': '600',
                    'currency': 'EUR', 'renewal_date': '2026-01-01', 'period_type': 'yearly', 'period_value': '1',
                    'software_name': '', 'budget_name': 'Software & SaaS 2025',
                    'assigned_user_email': 'alice.j@example.com', 'auto_renew': 'yes', 'description': 'Design suite'}],
        'init': _subscriptions_init,
        'handle': _subscriptions_handle,
    },
    'risks': {
        'label': 'Risks',
        'description': 'Create risks. likelihood/impact are 1-5 (default 1). category is a comma-separated list.',
        'required': ['name'],
        'optional': ['likelihood', 'impact', 'description', 'category'],
        'sample': [{'name': 'Data breach', 'likelihood': '3', 'impact': '5',
                    'description': 'Unauthorized access to PII', 'category': 'Security,Compliance'}],
        'handle': _risks_handle,
    },
}


def get_importer(type_key):
    cfg = IMPORTERS.get(type_key)
    if not cfg:
        raise ValueError(f'Unknown import type: {type_key}')
    return cfg


def template_csv(type_key):
    """CSV text for the downloadable template (header + sample rows)."""
    cfg = get_importer(type_key)
    cols = cfg['required'] + cfg.get('optional', [])
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols)
    writer.writeheader()
    for sample in cfg.get('sample', []):
        writer.writerow({c: sample.get(c, '') for c in cols})
    return out.getvalue()


def process(type_key, csv_text, commit=False):
    """Parse + classify (and optionally persist) CSV rows for ``type_key``.

    Returns: {columns, results[{index, display, status, message}],
              counts{create,skip,error}, notes[...], note_label}.
    Raises ValueError for structural problems (bad header, too many rows).
    """
    cfg = get_importer(type_key)
    columns = cfg['required'] + cfg.get('optional', [])
    fieldnames, rows = _read_rows(csv_text)

    missing = [c for c in cfg['required'] if c not in fieldnames]
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found: {', '.join(fieldnames) or '(none)'}."
        )
    if len(rows) > MAX_ROWS:
        raise ValueError(f'Too many rows ({len(rows)}); the maximum is {MAX_ROWS} per import.')

    ctx = cfg['init'](rows) if cfg.get('init') else {}
    results, notes = [], []
    counts = {'create': 0, 'skip': 0, 'error': 0}

    for i, row in enumerate(rows, start=1):
        try:
            status, message, note = cfg['handle'](row, ctx, commit)
        except Exception as exc:  # never let one bad row abort the whole import
            status, message, note = 'error', f'Error: {exc}', None
        counts[status] += 1
        results.append({
            'index': i,
            'display': {c: (row.get(c) or '') for c in columns},
            'status': status,
            'message': message,
        })
        if note:
            notes.append(note)

    if commit:
        db.session.commit()

    return {
        'columns': columns,
        'results': results,
        'counts': counts,
        'notes': notes,
        'note_label': cfg.get('note_label'),
    }
