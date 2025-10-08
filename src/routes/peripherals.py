from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Peripheral, Asset, Purchase, Supplier
from .main import login_required

peripherals_bp = Blueprint('peripherals', __name__)

@peripherals_bp.route('/')
@login_required
def peripherals():
    peripherals = Peripheral.query.filter_by(is_archived=False).all()
    return render_template('peripherals/list.html', peripherals=peripherals)


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

@peripherals_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_peripheral():
    if request.method == 'POST':
        peripheral = Peripheral(
            name=request.form['name'],
            type=request.form.get('type'),
            serial_number=request.form.get('serial_number'),
            status=request.form['status'],
            asset_id=request.form.get('asset_id'),
            purchase_id=request.form.get('purchase_id'),
            supplier_id=request.form.get('supplier_id')
        )
        db.session.add(peripheral)
        db.session.commit()
        flash('Peripheral created successfully!')
        return redirect(url_for('peripherals.peripherals'))

    return render_template('peripherals/form.html',
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all())

@peripherals_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_peripheral(id):
    peripheral = Peripheral.query.get_or_404(id)

    if request.method == 'POST':
        peripheral.name = request.form['name']
        peripheral.type = request.form.get('type')
        peripheral.serial_number = request.form.get('serial_number')
        peripheral.status = request.form['status']
        peripheral.asset_id = request.form.get('asset_id')
        peripheral.purchase_id = request.form.get('purchase_id')
        peripheral.supplier_id = request.form.get('supplier_id')

        db.session.commit()
        flash('Peripheral updated successfully!')
        return redirect(url_for('peripherals.peripherals'))

    return render_template('peripherals/form.html',
                            peripheral=peripheral,
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all())