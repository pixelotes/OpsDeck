from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from urllib.parse import urlparse
from ..models import db, Peripheral, Asset, Purchase, Supplier, User, PeripheralAssignment
from ..models.assets import Brand
from ..models.core import CustomFieldDefinition
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now


peripherals_bp = Blueprint('peripherals', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
PERIPHERALS = 'peripherals.peripherals'
PERIPHERAL_DETAIL = 'peripherals.peripheral_detail'
WRITE_REQUIRED = 'Write access required for this action.'

@peripherals_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def peripherals():
    peripherals = Peripheral.query.filter_by(is_archived=False).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    return render_template('peripherals/list.html', peripherals=peripherals, users=users)

@peripherals_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def peripheral_detail(id):
    peripheral = db.get_or_404(Peripheral, id)
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='Peripheral').all()
    return render_template('peripherals/detail.html', peripheral=peripheral, custom_field_definitions=custom_field_definitions)

@peripherals_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_peripheral():
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='Peripheral').all()
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(PERIPHERALS))
        serial_number = request.form.get('serial_number')
        serial_number = serial_number if serial_number and serial_number != 'None' else None
        peripheral = Peripheral(
            name=request.form['name'],
            type=request.form.get('type'),
            brand_id=int(request.form.get('brand_id')) if request.form.get('brand_id') else None,
            model_id=int(request.form.get('model_id')) if request.form.get('model_id') else None,
            serial_number=serial_number,
            status=request.form['status'],
            purchase_date=datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date() if request.form.get('purchase_date') else None,
            warranty_length=int(request.form.get('warranty_length')) if request.form.get('warranty_length') else None,
            cost=float(request.form.get('cost')) if request.form.get('cost') else None,
            currency=request.form.get('currency'),
            asset_id=request.form.get('asset_id') or None,
            purchase_id=request.form.get('purchase_id') or None,
            supplier_id=request.form.get('supplier_id') or None,
            user_id=request.form.get('user_id') or None
        )
        db.session.add(peripheral)
        db.session.commit()

        peripheral.save_custom_properties(request.form)
        db.session.commit()

        flash('Peripheral created successfully!', 'success')
        return redirect(url_for(PERIPHERALS))

    return render_template('peripherals/form.html',
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            brands=Brand.query.order_by(Brand.name).all(),
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all(),
                            custom_field_definitions=custom_field_definitions)

@peripherals_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_peripheral(id):
    peripheral = db.get_or_404(Peripheral, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(PERIPHERAL_DETAIL, id=id))
        # Enforce EoL Workflow
        new_status = request.form.get('status')
        if new_status in ['Disposed', 'Sold']:
            flash('To dispose of a peripheral, please use the "Record Disposal" action from its detail page. This ensures a proper audit trail.', 'warning')
            return redirect(url_for(PERIPHERAL_DETAIL, id=id))

        brand_id_form = request.form.get('brand_id')
        model_id_form = request.form.get('model_id')
        new_brand_id = int(brand_id_form) if brand_id_form else None
        new_model_id = int(model_id_form) if model_id_form else None

        # Check for validated purchase
        serial_number = request.form.get('serial_number')
        serial_number = serial_number if serial_number and serial_number != 'None' else None

        if peripheral.purchase and peripheral.purchase.validated_cost is not None:
            peripheral.name = request.form['name']
            peripheral.type = request.form.get('type')
            peripheral.brand_id = new_brand_id
            peripheral.model_id = new_model_id
            peripheral.serial_number = serial_number
            peripheral.status = new_status
            peripheral.user_id = request.form.get('user_id') or None
            peripheral.save_custom_properties(request.form)
            db.session.commit()
            flash('Peripheral updated. Cost cannot be changed because the associated purchase has been validated.', 'info')
            return redirect(url_for(PERIPHERAL_DETAIL, id=id))

        # Full update
        peripheral.name = request.form['name']
        peripheral.type = request.form.get('type')
        peripheral.brand_id = new_brand_id
        peripheral.model_id = new_model_id
        peripheral.serial_number = serial_number
        peripheral.status = new_status
        purchase_date_str = request.form.get('purchase_date')
        peripheral.purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date() if purchase_date_str else None
        peripheral.warranty_length = int(request.form.get('warranty_length')) if request.form.get('warranty_length') else None
        peripheral.cost = float(request.form.get('cost')) if request.form.get('cost') else None
        peripheral.currency = request.form.get('currency')
        peripheral.asset_id = request.form.get('asset_id') or None
        peripheral.purchase_id = request.form.get('purchase_id') or None
        peripheral.supplier_id = request.form.get('supplier_id') or None
        peripheral.user_id = request.form.get('user_id') or None
        
        peripheral.save_custom_properties(request.form)
        db.session.commit()
        flash('Peripheral updated successfully!', 'success')
        return redirect(url_for(PERIPHERAL_DETAIL, id=id))

    return render_template('peripherals/form.html',
                            peripheral=peripheral,
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            brands=Brand.query.order_by(Brand.name).all(),
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all(),
                            custom_field_definitions=CustomFieldDefinition.query.filter_by(entity_type='Peripheral').all())

@peripherals_bp.route('/<int:id>/checkout', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def checkout_peripheral(id):
    peripheral = db.get_or_404(Peripheral, id)
    if peripheral.user:
        flash('This peripheral is already checked out.', 'warning')
        return redirect(url_for(PERIPHERAL_DETAIL, id=id))

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(PERIPHERAL_DETAIL, id=id))
        user_id = request.form.get('user_id')
        notes = request.form.get('notes')
        
        if not user_id:
            flash('You must select a user.', 'danger')
            return redirect(url_for('peripherals.checkout_peripheral', id=id))
        
        user = db.session.get(User,user_id)
        if not user:
            flash('Selected user not found.', 'danger')
            return redirect(url_for('peripherals.checkout_peripheral', id=id))
        
        peripheral.user = user
        peripheral.status = 'In Use'  # Auto-update status on checkout
        assignment = PeripheralAssignment(peripheral_id=id, user_id=user_id, notes=notes)
        db.session.add(assignment)

        db.session.commit()
        flash(f'Peripheral "{peripheral.name}" has been checked out to {user.name}.', 'success')
        return redirect(url_for(PERIPHERAL_DETAIL, id=id))
        
    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('peripherals/checkout.html', peripheral=peripheral, users=users)

@peripherals_bp.route('/<int:id>/checkin', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def checkin_peripheral(id):
    peripheral = db.get_or_404(Peripheral, id)

    # Only redirect to a local relative path to avoid open redirects (Sonar).
    redirect_url = request.form.get('redirect_url', '')
    parsed_redirect_url = urlparse(redirect_url)
    safe_redirect_url = (
        redirect_url
        if redirect_url and not parsed_redirect_url.scheme and not parsed_redirect_url.netloc
        else url_for(PERIPHERAL_DETAIL, id=id)
    )
    
    if not peripheral.user:
        flash('This peripheral is already checked in.', 'warning')
        return redirect(safe_redirect_url)

    # REQUIRED: Select return location
    return_location_id = request.form.get('return_location_id')
    if not return_location_id:
        flash('You must select a location to return the peripheral to.', 'danger')
        return redirect(safe_redirect_url)
        
    from ..models import Location
    target_location = db.session.get(Location,return_location_id)
    if not target_location:
         flash('Selected location not found.', 'danger')
         return redirect(safe_redirect_url)

    assignment = PeripheralAssignment.query.filter_by(peripheral_id=id, checked_in_date=None).order_by(PeripheralAssignment.checked_out_date.desc()).first()
    
    if assignment:
        assignment.checked_in_date = now()

    flash(f'Peripheral "{peripheral.name}" has been checked in from {peripheral.user.name} to {target_location.name}.', 'success')
    peripheral.user = None
    peripheral.location_id = target_location.id # Update location
    peripheral.status = 'Available'  # Auto-update status on checkin
    
    # Auto-complete related offboarding item if exists
    from ..models.onboarding import ProcessItem
    offboarding_item = ProcessItem.query.filter_by(
        item_type='Peripheral', 
        linked_object_id=id, 
        is_completed=False
    ).first()
    if offboarding_item and offboarding_item.offboarding_process_id:
        offboarding_item.is_completed = True
    
    db.session.commit()
    return redirect(safe_redirect_url)


@peripherals_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_peripherals():
    """Displays a list of all archived peripherals."""
    archived = Peripheral.query.filter_by(is_archived=True).order_by(Peripheral.name).all()
    return render_template('peripherals/archived.html', peripherals=archived)


@peripherals_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_peripheral(id):
    """Sets a peripheral's status to archived."""
    peripheral = db.get_or_404(Peripheral, id)
    peripheral.is_archived = True
    db.session.commit()
    flash(f'Peripheral "{peripheral.name}" has been archived.', 'warning')
    return redirect(url_for(PERIPHERALS))


@peripherals_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_peripheral(id):
    """Restores an archived peripheral to active."""
    peripheral = db.get_or_404(Peripheral, id)
    peripheral.is_archived = False
    db.session.commit()
    flash(f'Peripheral "{peripheral.name}" has been restored.', 'success')
    return redirect(url_for('peripherals.archived_peripherals'))


@peripherals_bp.route('/<int:id>/history', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def peripheral_history(id):
    """Displays the full history for a peripheral as a visual timeline."""
    peripheral = db.get_or_404(Peripheral, id)
    
    # Build unified timeline from multiple sources
    timeline_events = []
    
    # 1. Purchase/Creation event
    if peripheral.purchase_date:
        timeline_events.append({
            'date': datetime.combine(peripheral.purchase_date, datetime.min.time()),
            'event_type': 'purchase',
            'icon': 'fa-shopping-cart',
            'color': 'success',
            'title': 'Peripheral Purchased',
            'description': f'Purchased for {peripheral.currency} {peripheral.cost:.2f}' if peripheral.cost else 'Purchase date recorded'
        })
    elif peripheral.created_at:
        timeline_events.append({
            'date': peripheral.created_at,
            'event_type': 'creation',
            'icon': 'fa-plus-circle',
            'color': 'success',
            'title': 'Peripheral Created',
            'description': 'Peripheral was added to the system'
        })
    
    # 2. Assignment events (checkout/checkin)
    for assignment in peripheral.assignments:
        user_name = assignment.user.name if assignment.user else 'Unknown User'
        
        # Checkout event
        timeline_events.append({
            'date': assignment.checked_out_date,
            'event_type': 'checkout',
            'icon': 'fa-sign-out-alt',
            'color': 'primary',
            'title': f'Checked Out to {user_name}',
            'description': assignment.notes or 'Assigned to employee'
        })
        
        # Checkin event (if returned)
        if assignment.checked_in_date:
            timeline_events.append({
                'date': assignment.checked_in_date,
                'event_type': 'checkin',
                'icon': 'fa-sign-in-alt',
                'color': 'warning',
                'title': f'Checked In from {user_name}',
                'description': 'Peripheral returned'
            })
    
    # 3. Maintenance events
    for log in peripheral.maintenance_logs:
        timeline_events.append({
            'date': datetime.combine(log.event_date, datetime.min.time()),
            'event_type': 'maintenance',
            'icon': 'fa-tools',
            'color': 'danger',
            'title': f'{log.event_type}',
            'description': log.description,
            'status': log.status
        })
    
    # Sort by date descending (newest first)
    timeline_events.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('peripherals/history.html', peripheral=peripheral, timeline_events=timeline_events)