from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, PaymentMethod, User
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

payment_methods_bp = Blueprint('payment_methods', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'finance'
PAYMENT_METHODS = 'payment_methods.payment_methods'

@payment_methods_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def payment_methods():
    methods = PaymentMethod.query.filter_by(is_archived=False).all()
    return render_template('payment_methods/list.html', payment_methods=methods)

@payment_methods_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_payment_methods():
    methods = PaymentMethod.query.filter_by(is_archived=True).all()
    return render_template('payment_methods/archived.html', payment_methods=methods)

@payment_methods_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def archive_payment_method(id):
    if not has_write_permission(MODULE):
        flash('Write access required to archive payment methods.', 'danger')
        return redirect(url_for(PAYMENT_METHODS))
    method = db.get_or_404(PaymentMethod, id)
    method.is_archived = True
    db.session.commit()
    flash(f'Payment method "{method.name}" has been archived.', 'warning')
    return redirect(url_for(PAYMENT_METHODS))

@payment_methods_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unarchive_payment_method(id):
    if not has_write_permission(MODULE):
        flash('Write access required to restore payment methods.', 'danger')
        return redirect(url_for('payment_methods.archived_payment_methods'))
    method = db.get_or_404(PaymentMethod, id)
    method.is_archived = False
    db.session.commit()
    flash(f'Payment method "{method.name}" has been restored.', 'success')
    return redirect(url_for('payment_methods.archived_payment_methods'))


@payment_methods_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def payment_method_detail(id):
    method = db.get_or_404(PaymentMethod, id)
    return render_template('payment_methods/detail.html', method=method)

@payment_methods_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_payment_method():
    users = User.query.filter_by(is_archived=False).all()
    
    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for(PAYMENT_METHODS))
        expiry_date = None
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%m/%y').date()

        user_id = request.form.get('user_id')

        method = PaymentMethod(
            name=request.form['name'],
            method_type=request.form['method_type'],
            details=request.form.get('details'),
            expiry_date=expiry_date,
            user_id=int(user_id) if user_id else None
        )
        db.session.add(method)
        db.session.commit()
        flash('Payment method created successfully!', 'success')
        return redirect(url_for(PAYMENT_METHODS))

    return render_template('payment_methods/form.html', users=users)

@payment_methods_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_payment_method(id):
    method = db.get_or_404(PaymentMethod, id)
    users = User.query.filter_by(is_archived=False).all()

    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for('payment_methods.payment_method_detail', id=id))
        expiry_date = None
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%m/%y').date()

        method.name = request.form['name']
        method.method_type = request.form['method_type']
        method.details = request.form.get('details')
        method.expiry_date = expiry_date
        
        user_id = request.form.get('user_id')
        method.user_id = int(user_id) if user_id else None

        db.session.commit()
        flash('Payment method updated successfully!', 'success')
        return redirect(url_for(PAYMENT_METHODS))

    return render_template('payment_methods/form.html', method=method, users=users)

@payment_methods_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_payment_method(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to delete payment methods.', 'danger')
        return redirect(url_for(PAYMENT_METHODS))
    method = db.get_or_404(PaymentMethod, id)
    db.session.delete(method)
    db.session.commit()
    flash('Payment method deleted successfully!', 'success')
    return redirect(url_for(PAYMENT_METHODS))