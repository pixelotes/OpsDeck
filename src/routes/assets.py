from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, Asset, AssetHistory, User, Location, Supplier, Purchase, AssetAssignment, Peripheral
from .main import login_required

assets_bp = Blueprint('assets', __name__)

@assets_bp.route('/')
@login_required
def assets():
    assets = Asset.query.filter_by(is_archived=False).all()
    return render_template('assets/list.html', assets=assets)

@assets_bp.route('/archived')
@login_required
def archived_assets():
    """Displays a list of all archived assets."""
    archived = Asset.query.filter_by(is_archived=True).order_by(Asset.name).all()
    return render_template('assets/archived.html', assets=archived)


@assets_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_asset(id):
    """Sets an asset's status to archived."""
    asset = Asset.query.get_or_404(id)
    asset.is_archived = True
    db.session.commit()
    flash(f'Asset "{asset.name}" has been archived.')
    return redirect(url_for('assets.assets'))


@assets_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_asset(id):
    """Restores an archived asset to active."""
    asset = Asset.query.get_or_404(id)
    asset.is_archived = False
    db.session.commit()
    flash(f'Asset "{asset.name}" has been restored.')
    return redirect(url_for('assets.archived_assets'))

@assets_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_asset():
    if request.method == 'POST':
        asset = Asset(
            name=request.form['name'],
            model=request.form.get('model'),
            brand=request.form.get('brand'),
            serial_number=request.form.get('serial_number'),
            status=request.form['status'],
            internal_id=request.form.get('internal_id'),
            comments=request.form.get('comments'),
            purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date() if request.form['purchase_date'] else None,
            cost=float(request.form.get('cost')) if request.form.get('cost') else None,
            currency=request.form.get('currency'),
            warranty_length=int(request.form.get('warranty_length')) if request.form.get('warranty_length') else None,
            user_id=request.form.get('user_id'),
            location_id=request.form.get('location_id'),
            supplier_id=request.form.get('supplier_id'),
            purchase_id=request.form.get('purchase_id')
        )
        db.session.add(asset)
        db.session.commit()
        flash('Asset created successfully!')
        return redirect(url_for('assets.assets'))

    return render_template('assets/form.html',
                            users=User.query.order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all())

@assets_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_asset(id):
    asset = Asset.query.get_or_404(id)

    if request.method == 'POST':
        changes = []
        if asset.name != request.form['name']:
            changes.append(('name', asset.name, request.form['name']))
        if asset.internal_id != request.form.get('internal_id'):
            changes.append(('internal_id', asset.internal_id, request.form.get('internal_id')))
        if asset.brand != request.form.get('brand'):
            changes.append(('brand', asset.brand, request.form.get('brand')))
        if asset.model != request.form.get('model'):
            changes.append(('model', asset.model, request.form.get('model')))
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
            history_entry = AssetHistory(asset_id=asset.id, field_changed=field, old_value=str(old_value), new_value=str(new_value))
            db.session.add(history_entry)

        asset.name = request.form['name']
        asset.model = request.form.get('model')
        asset.brand = request.form.get('brand')
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

        db.session.commit()
        flash('Asset updated successfully!')
        return redirect(url_for('assets.assets'))

    return render_template('assets/form.html',
                            asset=asset,
                            users=User.query.order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all())

@assets_bp.route('/<int:id>')
@login_required
def asset_detail(id):
    asset = Asset.query.get_or_404(id)
    return render_template('assets/detail.html', asset=asset)

@assets_bp.route('/<int:id>/checkout', methods=['GET', 'POST'])
@login_required
def checkout_asset(id):
    asset = Asset.query.get_or_404(id)
    if asset.user:
        flash('This asset is already checked out.', 'warning')
        return redirect(url_for('assets.asset_detail', id=id))

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        notes = request.form.get('notes')
        
        if not user_id:
            flash('You must select a user.', 'danger')
            return redirect(url_for('assets.checkout_asset', id=id))
        
        user = User.query.get(user_id)
        if not user:
            flash('Selected user not found.', 'danger')
            return redirect(url_for('assets.checkout_asset', id=id))
        
        asset.user = user
        
        assignment = AssetAssignment(asset_id=id, user_id=user_id, notes=notes)
        db.session.add(assignment)
        
        history_entry = AssetHistory(asset_id=id, field_changed='Status', old_value=asset.status, new_value=f'Checked out to {user.name}')
        db.session.add(history_entry)

        db.session.commit()
        flash(f'Asset "{asset.name}" has been checked out to {user.name}.')
        return redirect(url_for('assets.asset_detail', id=id))
        
    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('assets/checkout.html', asset=asset, users=users)


@assets_bp.route('/<int:id>/checkin', methods=['POST'])
@login_required
def checkin_asset(id):
    asset = Asset.query.get_or_404(id)
    if not asset.user:
        flash('This asset is already checked in.', 'warning')
        return redirect(url_for('assets.asset_detail', id=id))

    assignment = AssetAssignment.query.filter_by(asset_id=id, checked_in_date=None).order_by(AssetAssignment.checked_out_date.desc()).first()
    
    if assignment:
        assignment.checked_in_date = datetime.utcnow()

    history_entry = AssetHistory(asset_id=id, field_changed='Status', old_value=f'Checked out to {asset.user.name}', new_value='Checked In')
    db.session.add(history_entry)
    
    asset.user = None
    
    db.session.commit()
    flash(f'Asset "{asset.name}" has been checked in.')
    return redirect(url_for('assets.asset_detail', id=id))

@assets_bp.route('/warranties')
@login_required
def warranties():
    assets = Asset.query.filter(Asset.warranty_length.isnot(None)).all()
    peripherals = Peripheral.query.filter(Peripheral.warranty_length.isnot(None)).all()
    
    # Combine and sort assets and peripherals with warranties
    all_items = assets + peripherals
    
    # Filter out items where warranty_end_date is None (it shouldn't happen with the query, but it's safe)
    items_with_warranties = [item for item in all_items if item.warranty_end_date]
    
    sorted_items = sorted(items_with_warranties, key=lambda x: x.warranty_end_date, reverse=True)
    
    return render_template('assets/warranties.html', items=sorted_items)

@assets_bp.route('/<int:id>/history')
@login_required
def asset_history(id):
    """Displays the full history for a single asset."""
    asset = Asset.query.get_or_404(id)
    # The history is ordered by date in the model, so no need to sort here
    return render_template('assets/history.html', asset=asset)