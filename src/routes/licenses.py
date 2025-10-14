from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import db, License, User, Purchase, Subscription
from .main import login_required

licenses_bp = Blueprint('licenses', __name__, url_prefix='/licenses')

@licenses_bp.route('/')
@login_required
def list_licenses():
    page = request.args.get('page', 1, type=int)
    licenses = License.query.filter_by(is_archived=False).order_by(License.name.asc()).paginate(page=page, per_page=15)
    return render_template('licenses/list.html', licenses=licenses)

@licenses_bp.route('/<int:id>')
@login_required
def detail(id):
    license = License.query.get_or_404(id)
    return render_template('licenses/detail.html', license=license)

@licenses_bp.route('/new', methods=['GET', 'POST'])
@login_required
def add_license():
    if request.method == 'POST':
        # Safely extract form data, converting empty strings to None and applying type conversion
        cost_form = request.form.get('cost')
        purchase_date_form = request.form.get('purchase_date')
        expiry_date_form = request.form.get('expiry_date')
        
        new_license = License(
            name=request.form['name'],
            license_key=request.form.get('license_key'),
            cost=float(cost_form) if cost_form else None, # FIX: Convert empty string to None or float
            currency=request.form.get('currency'),
            purchase_date=datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None, # FIX: Convert to date or None
            expiry_date=datetime.strptime(expiry_date_form, '%Y-%m-%d').date() if expiry_date_form else None, # FIX: Convert to date or None
            user_id=request.form.get('user_id') or None,
            purchase_id=request.form.get('purchase_id') or None,
            subscription_id=request.form.get('subscription_id') or None
        )
        db.session.add(new_license)
        db.session.commit()
        flash('License added successfully!', 'success')
        return redirect(url_for('licenses.list_licenses'))

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    return render_template('licenses/form.html', license=None, users=users, purchases=purchases, subscriptions=subscriptions)

@licenses_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_license(id):
    license = License.query.get_or_404(id)
    if request.method == 'POST':
        cost_form = request.form.get('cost')
        purchase_date_form = request.form.get('purchase_date')
        expiry_date_form = request.form.get('expiry_date')

        license.name = request.form['name']
        license.license_key = request.form.get('license_key')
        license.cost = float(cost_form) if cost_form else None # FIX
        license.currency = request.form.get('currency')
        license.purchase_date = datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None # FIX
        license.expiry_date = datetime.strptime(expiry_date_form, '%Y-%m-%d').date() if expiry_date_form else None # FIX
        license.user_id = request.form.get('user_id') or None
        license.purchase_id = request.form.get('purchase_id') or None
        license.subscription_id = request.form.get('subscription_id') or None
        db.session.commit()
        flash('License updated successfully!', 'success')
        return redirect(url_for('licenses.detail', id=id))

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    return render_template('licenses/form.html', license=license, users=users, purchases=purchases, subscriptions=subscriptions)

@licenses_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_license(id):
    license = License.query.get_or_404(id)
    license.is_archived = True
    db.session.commit()
    flash(f'License "{license.name}" has been archived.', 'info')
    return redirect(url_for('licenses.list_licenses'))

@licenses_bp.route('/archived')
@login_required
def archived_licenses():
    licenses = License.query.filter_by(is_archived=True).order_by(License.name).all()
    return render_template('licenses/archived.html', licenses=licenses)

@licenses_bp.route('/<int:id>/restore', methods=['POST'])
@login_required
def restore_license(id):
    license = License.query.get_or_404(id)
    license.is_archived = False
    db.session.commit()
    flash(f'License "{license.name}" has been restored.', 'success')
    return redirect(url_for('licenses.archived_licenses'))