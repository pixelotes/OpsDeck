from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import datetime

from ..models import db, Supplier, User
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..utils.owner import parse_owner, owner_choices, InvalidOwner
from ..services import supplier_review_service as reviews


def _apply_review_schedule(supplier, form):
    """Review interval and next review date from the supplier form."""
    interval = form.get('review_interval_months', type=int)
    supplier.review_interval_months = interval if interval and interval > 0 else None
    raw_date = (form.get('next_review_date') or '').strip()
    if not supplier.review_interval_months:
        supplier.next_review_date = None
    elif raw_date:
        try:
            supplier.next_review_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            flash('Ignored an invalid next review date.', 'warning')
    if supplier.review_interval_months and not supplier.next_review_date:
        supplier.next_review_date = reviews.initial_next_review_date(supplier)

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
        try:
            owner_type, owner_id = parse_owner(request.form.get('owner'))
        except InvalidOwner:
            flash('The selected owner does not exist.', 'danger')
            users, groups = owner_choices()
            return render_template('suppliers/form.html', users=users, groups=groups), 400
        supplier = Supplier(
            owner_type=owner_type,
            owner_id=owner_id,
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
        _apply_review_schedule(supplier, request.form)
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier created successfully!', 'success')
        return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))

    users, groups = owner_choices()
    return render_template('suppliers/form.html', users=users, groups=groups)

@suppliers_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def supplier_detail(id):
    supplier = db.get_or_404(Supplier, id)
    user = db.session.get(User, session.get('user_id'))
    is_owner = reviews.is_reviewer(user, supplier)
    can_edit_reviews = has_write_permission('compliance')
    return render_template('suppliers/detail.html', supplier=supplier,
                           can_start_review=is_owner or can_edit_reviews or has_write_permission(MODULE),
                           can_fill_open=is_owner or can_edit_reviews)

@suppliers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('suppliers.supplier_detail', id=id))
        try:
            supplier.owner_type, supplier.owner_id = parse_owner(
                request.form.get('owner'), current=(supplier.owner_type, supplier.owner_id))
        except InvalidOwner:
            db.session.rollback()
            flash('The selected owner does not exist.', 'danger')
            users, groups = owner_choices()
            return render_template('suppliers/form.html', supplier=supplier, users=users, groups=groups), 400
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
        _apply_review_schedule(supplier, request.form)
        db.session.commit()
        flash('Supplier updated successfully!', 'success')
        return redirect(url_for('suppliers.supplier_detail', id=supplier.id)) # Redirect to detail view
    
    users, groups = owner_choices()
    return render_template('suppliers/form.html', supplier=supplier, users=users, groups=groups)

@suppliers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_supplier(id):
    supplier = db.get_or_404(Supplier, id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully!', 'success')
    return redirect(url_for(SUPPLIERS_LIST_ENDPOINT))