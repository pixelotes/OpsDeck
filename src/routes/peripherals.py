from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, Peripheral, Asset, Purchase, Supplier, User, PeripheralAssignment
from .main import login_required

peripherals_bp = Blueprint('peripherals', __name__)

@peripherals_bp.route('/')
@login_required
def peripherals():
    peripherals = Peripheral.query.filter_by(is_archived=False).all()
    return render_template('peripherals/list.html', peripherals=peripherals)

@peripherals_bp.route('/<int:id>')
@login_required
def peripheral_detail(id):
    peripheral = Peripheral.query.get_or_404(id)
    return render_template('peripherals/detail.html', peripheral=peripheral)

@peripherals_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_peripheral():
    if request.method == 'POST':
        peripheral = Peripheral(
            name=request.form['name'],
            type=request.form.get('type'),
            brand=request.form.get('brand'),
            serial_number=request.form.get('serial_number'),
            status=request.form['status'],
            purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date() if request.form['purchase_date'] else None,
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
        flash('Peripheral created successfully!')
        return redirect(url_for('peripherals.peripherals'))

    return render_template('peripherals/form.html',
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all())

@peripherals_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_peripheral(id):
    peripheral = Peripheral.query.get_or_404(id)
    
    if request.method == 'POST':
        # Enforce EoL Workflow
        new_status = request.form.get('status')
        if new_status in ['Disposed', 'Sold']:
            flash('To dispose of a peripheral, please use the "Record Disposal" action from its detail page. This ensures a proper audit trail.', 'warning')
            return redirect(url_for('peripherals.peripheral_detail', id=id))

        # Check for validated purchase
        if peripheral.purchase and peripheral.purchase.validated_cost is not None:
            peripheral.name = request.form['name']
            peripheral.type = request.form.get('type')
            peripheral.brand = request.form.get('brand')
            peripheral.serial_number = request.form.get('serial_number')
            peripheral.status = new_status
            peripheral.user_id = request.form.get('user_id') or None
            db.session.commit()
            flash('Peripheral updated. Cost cannot be changed because the associated purchase has been validated.', 'info')
            return redirect(url_for('peripherals.peripheral_detail', id=id))

        # Full update
        peripheral.name = request.form['name']
        peripheral.type = request.form.get('type')
        peripheral.brand = request.form.get('brand')
        peripheral.serial_number = request.form.get('serial_number')
        peripheral.status = new_status
        peripheral.purchase_date = datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date() if request.form['purchase_date'] else None
        peripheral.warranty_length = int(request.form.get('warranty_length')) if request.form.get('warranty_length') else None
        peripheral.cost = float(request.form.get('cost')) if request.form.get('cost') else None
        peripheral.currency = request.form.get('currency')
        peripheral.asset_id = request.form.get('asset_id') or None
        peripheral.purchase_id = request.form.get('purchase_id') or None
        peripheral.supplier_id = request.form.get('supplier_id') or None
        peripheral.user_id = request.form.get('user_id') or None
        
        db.session.commit()
        flash('Peripheral updated successfully!')
        return redirect(url_for('peripherals.peripheral_detail', id=id))

    return render_template('peripherals/form.html',
                            peripheral=peripheral,
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.filter_by(is_archived=False).order_by(User.name).all())

@peripherals_bp.route('/<int:id>/checkout', methods=['GET', 'POST'])
@login_required
def checkout_peripheral(id):
    peripheral = Peripheral.query.get_or_404(id)
    if peripheral.user:
        flash('This peripheral is already checked out.', 'warning')
        return redirect(url_for('peripherals.peripheral_detail', id=id))

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        notes = request.form.get('notes')
        
        if not user_id:
            flash('You must select a user.', 'danger')
            return redirect(url_for('peripherals.checkout_peripheral', id=id))
        
        user = User.query.get(user_id)
        if not user:
            flash('Selected user not found.', 'danger')
            return redirect(url_for('peripherals.checkout_peripheral', id=id))
        
        peripheral.user = user
        assignment = PeripheralAssignment(peripheral_id=id, user_id=user_id, notes=notes)
        db.session.add(assignment)

        db.session.commit()
        flash(f'Peripheral "{peripheral.name}" has been checked out to {user.name}.')
        return redirect(url_for('peripherals.peripheral_detail', id=id))
        
    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('peripherals/checkout.html', peripheral=peripheral, users=users)

@peripherals_bp.route('/<int:id>/checkin', methods=['POST'])
@login_required
def checkin_peripheral(id):
    peripheral = Peripheral.query.get_or_404(id)
    if not peripheral.user:
        flash('This peripheral is already checked in.', 'warning')
        return redirect(url_for('peripherals.peripheral_detail', id=id))

    assignment = PeripheralAssignment.query.filter_by(peripheral_id=id, checked_in_date=None).order_by(PeripheralAssignment.checked_out_date.desc()).first()
    
    if assignment:
        assignment.checked_in_date = datetime.utcnow()

    flash(f'Peripheral "{peripheral.name}" has been checked in from {peripheral.user.name}.', 'success')
    peripheral.user = None
    db.session.commit()
    return redirect(url_for('peripherals.peripheral_detail', id=id))


@peripherals_bp.route('/archived')
@login_required
def archived_peripherals():
    """Displays a list of all archived peripherals."""
    archived = Peripheral.query.filter_by(is_archived=True).order_by(Peripheral.name).all()
    return render_template('peripherals/archived.html', peripherals=archived)


@peripherals_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_peripheral(id):
    """Sets a peripheral's status to archived."""
    peripheral = Peripheral.query.get_or_404(id)
    peripheral.is_archived = True
    db.session.commit()
    flash(f'Peripheral "{peripheral.name}" has been archived.')
    return redirect(url_for('peripherals.peripherals'))


@peripherals_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_peripheral(id):
    """Restores an archived peripheral to active."""
    peripheral = Peripheral.query.get_or_404(id)
    peripheral.is_archived = False
    db.session.commit()
    flash(f'Peripheral "{peripheral.name}" has been restored.')
    return redirect(url_for('peripherals.archived_peripherals'))