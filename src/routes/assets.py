"""Routes for hardware asset management (list, CRUD, archive, history, warranties)."""
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime, date
from ..models import db, Asset, AssetHistory, User, Location, Supplier, Purchase, AssetAssignment, Peripheral
from ..models.assets import Brand, AssetModel
from ..models.core import CustomFieldDefinition
from .main import login_required

from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.logger import log_audit
from src.utils.timezone_helper import now, today


assets_bp = Blueprint('assets', __name__)

# Permission module and frequently-referenced endpoints (avoid duplicated literals)
MODULE = 'core_inventory'
ASSET_DETAIL = 'assets.asset_detail'
ASSET_LIST = 'assets.assets'
WRITE_REQUIRED = 'Write access required for this action.'

@assets_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def assets():
    assets = Asset.query.filter_by(is_archived=False).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()
    return render_template('assets/list.html', assets=assets, users=users, locations=locations)

@assets_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_assets():
    """Displays a list of all archived assets."""
    archived = Asset.query.filter_by(is_archived=True).order_by(Asset.name).all()
    return render_template('assets/archived.html', assets=archived)


@assets_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_asset(id):
    """Sets an asset's status to archived."""
    asset = db.get_or_404(Asset, id)
    asset.is_archived = True
    db.session.commit()
    
    log_audit(
        event_type='asset.archived',
        action='delete',
        target_object=f"Asset:{asset.id}",
        target_info=asset.name
    )
    
    flash(f'Asset "{asset.name}" has been archived.', 'warning')
    return redirect(url_for(ASSET_LIST))


@assets_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_asset(id):
    """Restores an archived asset to active."""
    asset = db.get_or_404(Asset, id)
    asset.is_archived = False
    db.session.commit()
    
    log_audit(
        event_type='asset.restored',
        action='update',
        target_object=f"Asset:{asset.id}",
        target_info=asset.name
    )
    
    flash(f'Asset "{asset.name}" has been restored.', 'success')
    return redirect(url_for('assets.archived_assets'))

@assets_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY') # READ_ONLY here, manually check POST
def new_asset():
    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(ASSET_LIST))
        asset = Asset(
            name=request.form['name'],
            brand_id=int(request.form.get('brand_id')) if request.form.get('brand_id') else None,
            model_id=int(request.form.get('model_id')) if request.form.get('model_id') else None,
            serial_number=request.form.get('serial_number'),
            status=request.form['status'],
            internal_id=request.form.get('internal_id'),
            comments=request.form.get('comments'),
            purchase_date=datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date() if request.form.get('purchase_date') else None,
            cost=float(request.form.get('cost')) if request.form.get('cost') else None,
            currency=request.form.get('currency'),
            warranty_length=int(request.form.get('warranty_length')) if request.form.get('warranty_length') else None,
            user_id=int(request.form.get('user_id')) if request.form.get('user_id') else None,
            location_id=int(request.form.get('location_id')) if request.form.get('location_id') else None,
            supplier_id=int(request.form.get('supplier_id')) if request.form.get('supplier_id') else None,
            purchase_id=int(request.form.get('purchase_id')) if request.form.get('purchase_id') else None,
            is_critical=request.form.get('is_critical') == 'on',
            is_virtual=request.form.get('is_virtual') == 'on'
        )
        db.session.add(asset)
        db.session.commit()
        
        asset.save_custom_properties(request.form)
        db.session.commit()
        
        log_audit(
            event_type='asset.created',
            action='create',
            target_object=f"Asset:{asset.id}",
            target_info=asset.name
        )
        
        flash('Asset created successfully!', 'success')
        return redirect(url_for(ASSET_LIST))

    return render_template('assets/form.html',
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            brands=Brand.query.order_by(Brand.name).all(),
                            custom_field_definitions=CustomFieldDefinition.query.filter_by(entity_type='Asset').all())

@assets_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_asset(id):
    asset = db.get_or_404(Asset, id)

    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(ASSET_DETAIL, id=id))
        # --- ENFORCE EOL WORKFLOW ---
        new_status = request.form.get('status')
        if new_status in ['Disposed', 'Sold']:
            flash('To dispose of an asset, please use the "Record Disposal" action from the asset detail page. This ensures a proper audit trail.', 'warning')
            return redirect(url_for(ASSET_DETAIL, id=id))

        changes = []
        old_status = asset.status
        
        if asset.name != request.form['name']:
            changes.append(('name', asset.name, request.form['name']))
        if asset.internal_id != request.form.get('internal_id'):
            changes.append(('internal_id', asset.internal_id, request.form.get('internal_id')))
        brand_id_form = request.form.get('brand_id')
        new_brand_id = int(brand_id_form) if brand_id_form else None
        if asset.brand_id != new_brand_id:
            old_brand_name = asset.brand.name if asset.brand else None
            new_brand_name = Brand.query.get(new_brand_id).name if new_brand_id else None
            changes.append(('brand', old_brand_name, new_brand_name))

        model_id_form = request.form.get('model_id')
        new_model_id = int(model_id_form) if model_id_form else None
        if asset.model_id != new_model_id:
            old_model_name = asset.model.name if asset.model else None
            new_model_name = AssetModel.query.get(new_model_id).name if new_model_id else None
            changes.append(('model', old_model_name, new_model_name))

        if asset.serial_number != request.form.get('serial_number'):
            changes.append(('serial_number', asset.serial_number, request.form.get('serial_number')))
        if asset.status != request.form.get('status'):
            changes.append(('status', asset.status, request.form.get('status')))

        purchase_date_form = request.form.get('purchase_date')
        purchase_date = datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None
        if asset.purchase_date != purchase_date:
            changes.append(('purchase_date', asset.purchase_date, purchase_date))

        cost_form = request.form.get('cost')
        cost = float(cost_form) if cost_form else None
        if asset.cost != cost:
            changes.append(('cost', asset.cost, cost))

        if asset.currency != request.form.get('currency'):
            changes.append(('currency', asset.currency, request.form.get('currency')))

        warranty_length_form = request.form.get('warranty_length')
        warranty_length = int(warranty_length_form) if warranty_length_form else None
        if asset.warranty_length != warranty_length:
            changes.append(('warranty_length', asset.warranty_length, warranty_length))

        supplier_id_form = request.form.get('supplier_id')
        supplier_id = int(supplier_id_form) if supplier_id_form else None
        if asset.supplier_id != supplier_id:
            changes.append(('supplier_id', asset.supplier_id, supplier_id))

        purchase_id_form = request.form.get('purchase_id')
        purchase_id = int(purchase_id_form) if purchase_id_form else None
        if asset.purchase_id != purchase_id:
            changes.append(('purchase_id', asset.purchase_id, purchase_id))

        user_id_form = request.form.get('user_id')
        user_id = int(user_id_form) if user_id_form else None
        if asset.user_id != user_id:
            changes.append(('user_id', asset.user_id, user_id))

        location_id_form = request.form.get('location_id')
        location_id = int(location_id_form) if location_id_form else None
        if asset.location_id != location_id:
            changes.append(('location_id', asset.location_id, location_id))

        if asset.comments != request.form.get('comments'):
            changes.append(('comments', asset.comments, request.form.get('comments')))


        for field, old_value, new_value in changes:
            # Normalize None and empty strings so we don't log no-op changes
            norm_old = old_value if old_value is not None and old_value != '' else None
            norm_new = new_value if new_value is not None and new_value != '' else None
            if norm_old == norm_new:
                continue
            history_entry = AssetHistory(asset_id=asset.id, field_changed=field, old_value=str(old_value), new_value=str(new_value))
            db.session.add(history_entry)

        asset.name = request.form['name']
        asset.brand_id = new_brand_id
        asset.model_id = new_model_id
        asset.serial_number = request.form.get('serial_number')
        asset.status = request.form['status']
        asset.internal_id = request.form.get('internal_id')
        asset.comments = request.form.get('comments')
        asset.purchase_date = purchase_date
        asset.cost = cost
        asset.currency = request.form.get('currency')
        asset.warranty_length = warranty_length
        asset.user_id = user_id
        asset.location_id = location_id
        asset.supplier_id = supplier_id
        asset.purchase_id = purchase_id
        asset.is_critical = request.form.get('is_critical') == 'on'
        asset.is_virtual = request.form.get('is_virtual') == 'on'

        asset.save_custom_properties(request.form)

        db.session.commit()
        
        # Audit Log
        event_ctx = {'target_object': f"Asset:{asset.id}"}
        if old_status != asset.status:
             event_ctx['old_status'] = old_status
             event_ctx['new_status'] = asset.status
             
        log_audit(
            event_type='asset.updated',
            action='update',
            **event_ctx
        )
        
        flash('Asset updated successfully!', 'success')
        return redirect(url_for(ASSET_LIST))

    return render_template('assets/form.html',
                            asset=asset,
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            brands=Brand.query.order_by(Brand.name).all(),
                            custom_field_definitions=CustomFieldDefinition.query.filter_by(entity_type='Asset').all())

@assets_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def asset_detail(id):
    asset = db.get_or_404(Asset, id)
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='Asset').all()
    return render_template('assets/detail.html', asset=asset, locations=locations, custom_field_definitions=custom_field_definitions)

@assets_bp.route('/<int:id>/checkout', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def checkout_asset(id):
    asset = db.get_or_404(Asset, id)
    if asset.user:
        flash('This asset is already checked out.', 'warning')
        return redirect(url_for(ASSET_DETAIL, id=id))

    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(ASSET_DETAIL, id=id))
        user_id = request.form.get('user_id')
        notes = request.form.get('notes')
        location_mode = request.form.get('location_mode', 'keep')
        
        if not user_id:
            flash('You must select a user.', 'danger')
            return redirect(url_for('assets.checkout_asset', id=id))
        
        user = db.session.get(User,user_id)
        if not user:
            flash('Selected user not found.', 'danger')
            return redirect(url_for('assets.checkout_asset', id=id))
        
        asset.user = user
        asset.status = 'In Use'  # Auto-update status on checkout
        log_msg = f'Checked out to {user.name}'
        
        # Handle location mode
        if location_mode == 'remote':
            old_loc = asset.location.name if asset.location else 'None'
            asset.location = None
            log_msg += f' (Moved to Remote from {old_loc})'
        else:
            log_msg += f' (Kept at {asset.location.name if asset.location else "Unknown"})'
        
        assignment = AssetAssignment(asset_id=id, user_id=user_id, notes=notes)
        db.session.add(assignment)
        
        history_entry = AssetHistory(asset_id=id, field_changed='Status', old_value=asset.status, new_value=log_msg)
        db.session.add(history_entry)

        db.session.commit()
        flash(f'Asset "{asset.name}" has been checked out to {user.name}.', 'success')
        return redirect(url_for(ASSET_DETAIL, id=id))
        
    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()
    return render_template('assets/checkout.html', asset=asset, users=users, locations=locations)


@assets_bp.route('/<int:id>/checkin', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def checkin_asset(id):
    asset = db.get_or_404(Asset, id)
    redirect_url = request.form.get('redirect_url')
    
    if not asset.user:
        flash('This asset is already checked in.', 'warning')
        return redirect(redirect_url or url_for(ASSET_DETAIL, id=id))

    # REQUIRED: Select return location
    return_location_id = request.form.get('return_location_id')
    if not return_location_id:
        flash('You must select a location to return the asset to.', 'danger')
        return redirect(redirect_url or url_for(ASSET_DETAIL, id=id))
    
    target_location = db.session.get(Location,return_location_id)
    if not target_location:
        flash('Selected location not found.', 'danger')
        return redirect(redirect_url or url_for(ASSET_DETAIL, id=id))

    assignment = AssetAssignment.query.filter_by(asset_id=id, checked_in_date=None).order_by(AssetAssignment.checked_out_date.desc()).first()
    
    if assignment:
        assignment.checked_in_date = now()

    history_entry = AssetHistory(asset_id=id, field_changed='Status', old_value=f'Checked out to {asset.user.name}', new_value=f'Checked In to {target_location.name}')
    db.session.add(history_entry)
    
    asset.user = None
    asset.location = target_location
    asset.status = 'Available'  # Auto-update status on checkin
    
    # Auto-complete related offboarding item if exists
    from ..models.onboarding import ProcessItem
    with db.session.no_autoflush:
        offboarding_item = ProcessItem.query.filter_by(
            item_type='Asset',
            linked_object_id=id,
            is_completed=False
        ).first()
    if offboarding_item and offboarding_item.offboarding_process_id:
        offboarding_item.is_completed = True

    db.session.commit()
    flash(f'Asset "{asset.name}" has been returned to {target_location.name}.', 'success')
    return redirect(redirect_url or url_for(ASSET_DETAIL, id=id))

@assets_bp.route('/warranties', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def warranties():
    assets = Asset.query.filter(Asset.warranty_length.isnot(None)).all()
    peripherals = Peripheral.query.filter(Peripheral.warranty_length.isnot(None)).all()
    
    # Combine and sort assets and peripherals with warranties
    all_items = assets + peripherals
    
    # Filter out items where warranty_end_date is None (it shouldn't happen with the query, but it's safe)
    items_with_warranties = [item for item in all_items if item.warranty_end_date]
    
    sorted_items = sorted(items_with_warranties, key=lambda x: x.warranty_end_date, reverse=True)
    
    return render_template('assets/warranties.html', items=sorted_items, today=today())

@assets_bp.route('/<int:id>/history', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def asset_history(id):
    """Displays the full history for a single asset as a visual timeline."""
    asset = db.get_or_404(Asset, id)
    
    # Build unified timeline from multiple sources
    timeline_events = []
    
    # 1. Purchase/Creation event
    if asset.purchase_date:
        timeline_events.append({
            'date': datetime.combine(asset.purchase_date, datetime.min.time()),
            'event_type': 'purchase',
            'icon': 'fa-shopping-cart',
            'color': 'success',
            'title': 'Asset Purchased',
            'description': f'Purchased for {asset.currency} {asset.cost:.2f}' if asset.cost else 'Purchase date recorded'
        })
    elif asset.created_at:
        timeline_events.append({
            'date': asset.created_at,
            'event_type': 'creation',
            'icon': 'fa-plus-circle',
            'color': 'success',
            'title': 'Asset Created',
            'description': 'Asset was added to the system'
        })
    
    # 2. Assignment events (checkout/checkin)
    for assignment in asset.assignments:
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
                'description': 'Asset returned'
            })

    # 3. Maintenance events
    for log in asset.maintenance_logs:
        timeline_events.append({
            'date': datetime.combine(log.event_date, datetime.min.time()),
            'event_type': 'maintenance',
            'icon': 'fa-tools',
            'color': 'danger',
            'title': f'{log.event_type}',
            'description': log.description,
            'status': log.status,
            'url': url_for('maintenance.log_detail', id=log.id)
        })

    # 4. Field change history
    for entry in asset.history:
        timeline_events.append({
            'date': entry.changed_at,
            'event_type': 'change',
            'icon': 'fa-edit',
            'color': 'secondary',
            'title': f'Field Changed: {entry.field_changed}',
            'description': f'{entry.old_value or "N/A"} → {entry.new_value or "N/A"}'
        })

    # 5. Disposal record
    if asset.disposal_record:
        rec = asset.disposal_record
        desc = f'Method: {rec.disposal_method}'
        if rec.disposal_partner:
            desc += f' — Partner: {rec.disposal_partner.name}'
        if rec.notes:
            desc += f' — {rec.notes}'
        timeline_events.append({
            'date': datetime.combine(rec.disposal_date, datetime.min.time()),
            'event_type': 'disposal',
            'icon': 'fa-trash-alt',
            'color': 'dark',
            'title': 'Asset Disposed',
            'description': desc,
            'url': url_for('disposal.disposal_detail', id=rec.id)
        })

    # 6. Related changes
    for change in asset.changes:
        timeline_events.append({
            'date': change.created_at,
            'event_type': 'change_ticket',
            'icon': 'fa-exchange-alt',
            'color': 'info',
            'title': f'{change.change_type} Change: {change.title}',
            'description': f'Status: {change.status}',
            'status': change.status,
            'url': url_for('changes.detail_change', id=change.id)
        })
    
    # Sort by date descending (newest first)
    timeline_events.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('assets/history.html', asset=asset, timeline_events=timeline_events)