from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import db, License, User, Purchase, Subscription, Software, Budget # Import Software and Budget
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
        cost_form = request.form.get('cost')
        purchase_date_form = request.form.get('purchase_date')
        expiry_date_form = request.form.get('expiry_date')
        link_type = request.form.get('link_type')
        software_id_form = None
        subscription_id_form = None
        final_cost = None # Initialize cost as None

        if link_type == 'software':
            software_id_form = request.form.get('software_id') or None
            # Only assign cost if it's a software/perpetual license and cost is provided
            final_cost = float(cost_form) if cost_form else None
        elif link_type == 'subscription':
            subscription_id_form = request.form.get('subscription_id') or None
            # Cost should be None for subscription seats
            final_cost = None

        new_license = License(
            name=request.form['name'],
            license_key=request.form.get('license_key'),
            cost=final_cost, # Use the determined cost
            currency=request.form.get('currency') if final_cost is not None else 'EUR', # Default currency if cost is None, or get from form
            purchase_date=datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None,
            expiry_date=datetime.strptime(expiry_date_form, '%Y-%m-%d').date() if expiry_date_form else None,
            user_id=int(request.form.get('user_id')) if request.form.get('user_id') else None,
            purchase_id=int(request.form.get('purchase_id')) if request.form.get('purchase_id') else None,
            subscription_id=int(subscription_id_form) if subscription_id_form else None,
            software_id=int(software_id_form) if software_id_form else None
        )
        db.session.add(new_license)
        db.session.commit()
        flash('License added successfully!', 'success')
        return redirect(url_for('licenses.list_licenses'))

    # --- (GET request part remains the same) ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
    return render_template('licenses/form.html', license=None, users=users, purchases=purchases, subscriptions=subscriptions, software_items=software_items)


@licenses_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_license(id):
    license = License.query.get_or_404(id)
    original_purchase = license.purchase # Store original purchase before potential changes

    if request.method == 'POST':
        # --- Check if original or NEW purchase is validated ---
        new_purchase_id_form = request.form.get('purchase_id')
        new_purchase_id = int(new_purchase_id_form) if new_purchase_id_form else None
        new_purchase = Purchase.query.get(new_purchase_id) if new_purchase_id else None

        is_validated = False
        validated_purchase_desc = None

        if original_purchase and original_purchase.validated_cost is not None:
             # If the original purchase was validated, prevent changing financial fields OR the purchase itself
            if new_purchase_id != original_purchase.id:
                 is_validated = True
                 validated_purchase_desc = original_purchase.description
            elif request.form.get('cost') or request.form.get('currency'):
                 # Allow updates if cost/currency fields are empty or match existing (for non-financial edits)
                 cost_form = request.form.get('cost')
                 final_cost = float(cost_form) if cost_form else None
                 if final_cost != license.cost or request.form.get('currency') != license.currency:
                      is_validated = True
                      validated_purchase_desc = original_purchase.description

        elif new_purchase and new_purchase.validated_cost is not None:
            # If trying to link TO a validated purchase
            is_validated = True
            validated_purchase_desc = new_purchase.description

        if is_validated:
            flash(f'Cannot change financial details or link to/from a validated purchase ({validated_purchase_desc}). Please un-validate the purchase first.', 'warning')
             # --- Reload necessary data for the form ---
            users = User.query.filter_by(is_archived=False).order_by(User.name).all()
            purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
            subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
            software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
            return render_template('licenses/form.html', license=license, users=users, purchases=purchases, subscriptions=subscriptions, software_items=software_items)
        # --- End Validation Check ---

        # (Existing code for processing form data and saving, starting from cost_form = ...)
        # ... Ensure you keep the logic from the previous step for final_cost ...
        cost_form = request.form.get('cost')
        purchase_date_form = request.form.get('purchase_date')
        expiry_date_form = request.form.get('expiry_date')
        link_type = request.form.get('link_type')
        software_id_form = None
        subscription_id_form = None
        final_cost = None # Initialize cost as None

        # Update basic fields
        license.name = request.form['name']
        license.license_key = request.form.get('license_key')
        license.purchase_date = datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None
        license.expiry_date = datetime.strptime(expiry_date_form, '%Y-%m-%d').date() if expiry_date_form else None
        license.user_id = int(request.form.get('user_id')) if request.form.get('user_id') else None
        license.purchase_id = new_purchase_id # Use the already determined new_purchase_id

        # Logic for Exclusive Link AND Cost
        if link_type == 'software':
            software_id_form = request.form.get('software_id')
            license.software_id = int(software_id_form) if software_id_form else None
            license.subscription_id = None
            final_cost = float(cost_form) if cost_form else None
        elif link_type == 'subscription':
            subscription_id_form = request.form.get('subscription_id')
            license.subscription_id = int(subscription_id_form) if subscription_id_form else None
            license.software_id = None
            final_cost = None
        else:
            license.software_id = None
            license.subscription_id = None
            final_cost = None

        license.cost = final_cost
        license.currency = request.form.get('currency') if final_cost is not None else license.currency

        db.session.commit()
        flash('License updated successfully!', 'success')
        return redirect(url_for('licenses.detail', id=id))

    # --- (GET request part remains the same) ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
    return render_template('licenses/form.html', license=license, users=users, purchases=purchases, subscriptions=subscriptions, software_items=software_items)
    license = License.query.get_or_404(id)
    if request.method == 'POST':
        cost_form = request.form.get('cost')
        purchase_date_form = request.form.get('purchase_date')
        expiry_date_form = request.form.get('expiry_date')
        link_type = request.form.get('link_type')
        software_id_form = None
        subscription_id_form = None
        final_cost = None # Initialize cost as None

        # Update basic fields
        license.name = request.form['name']
        license.license_key = request.form.get('license_key')
        license.purchase_date = datetime.strptime(purchase_date_form, '%Y-%m-%d').date() if purchase_date_form else None
        license.expiry_date = datetime.strptime(expiry_date_form, '%Y-%m-%d').date() if expiry_date_form else None
        license.user_id = int(request.form.get('user_id')) if request.form.get('user_id') else None
        license.purchase_id = int(request.form.get('purchase_id')) if request.form.get('purchase_id') else None

        # --- CORRECTED Logic for Exclusive Link AND Cost ---
        if link_type == 'software':
            software_id_form = request.form.get('software_id')
            license.software_id = int(software_id_form) if software_id_form else None
            license.subscription_id = None
            # Only assign cost if it's a software/perpetual license and cost is provided
            final_cost = float(cost_form) if cost_form else None
        elif link_type == 'subscription':
            subscription_id_form = request.form.get('subscription_id')
            license.subscription_id = int(subscription_id_form) if subscription_id_form else None
            license.software_id = None
            # Cost should be None (or 0) for subscription seats
            final_cost = None # Explicitly set cost to None
        else:
            license.software_id = None
            license.subscription_id = None
            final_cost = None # Should not happen with required field, but safe fallback

        license.cost = final_cost
        # Only update currency if there is a cost
        license.currency = request.form.get('currency') if final_cost is not None else license.currency # Keep existing if cost is None
        # --- END CORRECTION ---

        db.session.commit()
        flash('License updated successfully!', 'success')
        return redirect(url_for('licenses.detail', id=id))

    # --- (GET request part remains the same) ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    purchases = Purchase.query.filter_by(is_archived=False).order_by(Purchase.purchase_date.desc()).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
    return render_template('licenses/form.html', license=license, users=users, purchases=purchases, subscriptions=subscriptions, software_items=software_items)

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