from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Supplier
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

suppliers_bp = Blueprint('suppliers', __name__)

SUPPLIERS_LIST_ENDPOINT = 'suppliers.suppliers'
MODULE = 'procurement'

@suppliers_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def suppliers():
    suppliers = Supplier.query.filter_by(is_archived=False).all()
    return render_template('suppliers/list.html', suppliers=suppliers)

@suppliers_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_suppliers():
    suppliers = Supplier.query.filter_by(is_archived=True).all()
    return render_template('suppliers/archived.html', suppliers=suppliers)

@suppliers_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    supplier.is_archived = True
    db.session.commit()
    flash(f'Supplier "{supplier.name}" has been archived.', 'warning')
    return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))


@suppliers_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    supplier.is_archived = False
    db.session.commit()
    flash(f'Supplier "{supplier.name}" has been restored.', 'success')
    return redirect(url_for('suppliers.archived_suppliers'))

@suppliers_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_supplier():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))
        supplier = Supplier(
            name=request.form['name'],
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            website=request.form.get('website'),
            notes=request.form.get('notes'),
            compliance_status=request.form.get('compliance_status'),
            compliance_notes=request.form.get('compliance_notes'),
            is_critical=request.form.get('is_critical') == 'on'
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier created successfully!', 'success')
        return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))

    return render_template('suppliers/form.html')

@suppliers_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def supplier_detail(id):
    supplier = db.get_or_404(Supplier, id)
    return render_template('suppliers/detail.html', supplier=supplier)

@suppliers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('suppliers.supplier_detail', id=id))
        supplier.name = request.form['name']
        supplier.email = request.form.get('email')
        supplier.phone = request.form.get('phone')
        supplier.address = request.form.get('address')
        supplier.website = request.form.get('website')
        supplier.notes = request.form.get('notes')
        supplier.compliance_status = request.form.get('compliance_status')
        supplier.compliance_notes = request.form.get('compliance_notes')
        supplier.data_storage_region = request.form.get('data_storage_region')
        supplier.is_critical = request.form.get('is_critical') == 'on'
        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('suppliers.supplier_detail', id=supplier.id)) # Redirect to detail view
    
    return render_template('suppliers/form.html', supplier=supplier)

@suppliers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully!', 'success')
    return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))