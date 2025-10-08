from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, PaymentMethod
from .main import login_required

payment_methods_bp = Blueprint('payment_methods', __name__)

@payment_methods_bp.route('/')
@login_required
def payment_methods():
    methods = PaymentMethod.query.filter_by(is_archived=False).all()
    return render_template('payment_methods/list.html', payment_methods=methods)

@payment_methods_bp.route('/archived')
@login_required
def archived_payment_methods():
    methods = PaymentMethod.query.filter_by(is_archived=True).all()
    return render_template('payment_methods/archived.html', payment_methods=methods)

@payment_methods_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    method.is_archived = True
    db.session.commit()
    flash(f'Payment method "{method.name}" has been archived.')
    return redirect(url_for('payment_methods.payment_methods'))

@payment_methods_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    method.is_archived = False
    db.session.commit()
    flash(f'Payment method "{method.name}" has been restored.')
    return redirect(url_for('payment_methods.archived_payment_methods'))


@payment_methods_bp.route('/<int:id>')
@login_required
def payment_method_detail(id):
    method = PaymentMethod.query.get_or_404(id)
    return render_template('payment_methods/detail.html', method=method)

@payment_methods_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_payment_method():
    if request.method == 'POST':
        expiry_date = None
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%m/%y').date()

        method = PaymentMethod(
            name=request.form['name'],
            method_type=request.form['method_type'],
            details=request.form.get('details'),
            expiry_date=expiry_date
        )
        db.session.add(method)
        db.session.commit()
        flash('Payment method created successfully!')
        return redirect(url_for('payment_methods.payment_methods'))

    return render_template('payment_methods/form.html')

@payment_methods_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    if request.method == 'POST':
        expiry_date = None
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%m/%y').date()

        method.name = request.form['name']
        method.method_type = request.form['method_type']
        method.details = request.form.get('details')
        method.expiry_date = expiry_date
        db.session.commit()
        flash('Payment method updated successfully!')
        return redirect(url_for('payment_methods.payment_methods'))

    return render_template('payment_methods/form.html', method=method)

@payment_methods_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    db.session.delete(method)
    db.session.commit()
    flash('Payment method deleted successfully!')
    return redirect(url_for('payment_methods.payment_methods'))