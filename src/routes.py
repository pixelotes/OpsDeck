# src/routes.py

import uuid, os, calendar
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify, 
    session, current_app, send_from_directory
)
from sqlalchemy import func, case
from functools import wraps
from datetime import datetime, timedelta, date
from .models import (
    db, AppUser, User, Supplier, Contact, Service, PaymentMethod,
    NotificationSetting, Attachment, Tag, CostHistory, CURRENCY_RATES, Purchase,
    Asset, Location, AssetHistory, Peripheral, Budget
)
from calendar import month_abbr
from dateutil.relativedelta import relativedelta

main_bp = Blueprint('main', __name__)

# --- Authentication Decorator (now part of the blueprint) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@main_bp.route('/login', methods=['GET', 'POST'])
def login():  # <-- Ensure this function is named 'login'
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = AppUser.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@main_bp.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    return redirect(url_for('main.login'))

@main_bp.route('/')
@login_required
def dashboard():
    # --- Upcoming Renewals & Filter Logic (This part is correct and remains the same) ---
    period = request.args.get('period', '30', type=str)
    today = date.today()
    
    if period == '7':
        start_date, end_date = today, today + timedelta(days=7)
    elif period == '90':
        start_date, end_date = today, today + timedelta(days=90)
    elif period == 'current_month':
        start_date = today.replace(day=1)
        end_date = start_date + relativedelta(months=+1, days=-1)
    elif period == 'next_month':
        start_date = (today.replace(day=1) + relativedelta(months=+1))
        end_date = start_date + relativedelta(months=+1, days=-1)
    else:
        period = '30'
        start_date, end_date = today, today + timedelta(days=30)

    all_active_services = Service.query.filter_by(is_archived=False).all()
    upcoming_renewals, total_cost = [], 0

    for service in all_active_services:
        next_renewal = service.next_renewal_date
        while next_renewal <= end_date:
            if next_renewal >= start_date:
                upcoming_renewals.append((next_renewal, service))
                total_cost += service.cost_eur
            if service.renewal_period_type == 'monthly':
                next_renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                next_renewal += relativedelta(years=+service.renewal_period_value)
            else:
                next_renewal += timedelta(days=service.renewal_period_value)
    upcoming_renewals.sort(key=lambda x: x[0])


    # --- CORRECTED: Forecast Chart Logic ---
    forecast_start_date = today.replace(day=1)
    end_of_forecast_period = forecast_start_date + relativedelta(months=+13)
    
    forecast_labels, forecast_keys, forecast_costs = [], [], {}
    for i in range(13):
        month_date = forecast_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_keys.append(year_month_key)
        forecast_costs[year_month_key] = 0

    for service in all_active_services:
        # Start from the original renewal date to find the first relevant occurrence
        renewal = service.renewal_date
        while renewal < forecast_start_date:
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)

        # Now, loop through all renewals that fall within our 13-month window
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += service.cost_eur
            
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)
    
    forecast_data = [round(cost, 2) for cost in forecast_costs.values()]


    return render_template(
        'dashboard.html', 
        upcoming_renewals=upcoming_renewals,
        total_cost=total_cost,
        selected_period=period,
        today=today,
        forecast_labels=forecast_labels,
        forecast_keys=forecast_keys,
        forecast_data=forecast_data
    )

# User routes
@main_bp.route('/users')
@login_required
def users():
    users = User.query.all()
    return render_template('users/list.html', users=users)

@main_bp.route('/users/<int:id>')
@login_required
def user_detail(id):
    user = User.query.get_or_404(id)
    return render_template('users/detail.html', user=user)

@main_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
def new_user():
    if request.method == 'POST':
        user = User(
            name=request.form['name'],
            email=request.form.get('email'),
            department=request.form.get('department'),
            job_title=request.form.get('job_title')
        )
        db.session.add(user)
        db.session.commit()
        flash('User created successfully!')
        return redirect(url_for('main.users'))
    
    return render_template('users/form.html')

@main_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    user = User.query.get_or_404(id)
    
    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form.get('email')
        user.department = request.form.get('department')
        user.job_title = request.form.get('job_title')
        db.session.commit()
        flash('User updated successfully!')
        return redirect(url_for('main.users'))
    
    return render_template('users/form.html', user=user)

# Purchase routes
@main_bp.route('/purchases')
@login_required
def purchases():
    purchases = Purchase.query.all()
    return render_template('purchases/list.html', purchases=purchases)

@main_bp.route('/purchases/<int:id>')
@login_required
def purchase_detail(id):
    purchase = Purchase.query.get_or_404(id)
    return render_template('purchases/detail.html', purchase=purchase)

@main_bp.route('/purchases/new', methods=['GET', 'POST'])
@login_required
def new_purchase():
    if request.method == 'POST':
        purchase = Purchase(
            internal_id=request.form.get('internal_id'),
            description=request.form['description'],
            invoice_number=request.form.get('invoice_number'),
            purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date(),
            cost=float(request.form['cost']),
            currency=request.form['currency'],
            comments=request.form.get('comments'),
            supplier_id=request.form.get('supplier_id'),
            payment_method_id=request.form.get('payment_method_id'),
            budget_id=request.form.get('budget_id')
        )

        for user_id in request.form.getlist('user_ids'):
            user = User.query.get(user_id)
            if user:
                purchase.users.append(user)
        
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                purchase.tags.append(tag)

        db.session.add(purchase)
        db.session.commit()
        flash('Purchase created successfully!')
        return redirect(url_for('main.purchases'))
    
    return render_template('purchases/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

@main_bp.route('/purchases/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    
    if request.method == 'POST':
        purchase.internal_id = request.form.get('internal_id')
        purchase.description = request.form['description']
        purchase.invoice_number = request.form.get('invoice_number')
        purchase.purchase_date = datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date()
        purchase.cost = float(request.form['cost'])
        purchase.currency = request.form['currency']
        purchase.comments = request.form.get('comments')
        purchase.supplier_id = request.form.get('supplier_id')
        purchase.payment_method_id = request.form.get('payment_method_id')
        purchase.budget_id = request.form.get('budget_id')

        purchase.users.clear()
        for user_id in request.form.getlist('user_ids'):
            user = User.query.get(user_id)
            if user:
                purchase.users.append(user)
        
        purchase.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                purchase.tags.append(tag)
        
        db.session.commit()
        flash('Purchase updated successfully!')
        return redirect(url_for('main.purchases'))

    return render_template('purchases/form.html',
                            purchase=purchase,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

# Asset routes
@main_bp.route('/assets')
@login_required
def assets():
    assets = Asset.query.all()
    return render_template('assets/list.html', assets=assets)

@main_bp.route('/assets/new', methods=['GET', 'POST'])
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
            price=float(request.form.get('price')) if request.form.get('price') else None,
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
        return redirect(url_for('main.assets'))

    return render_template('assets/form.html',
                            users=User.query.order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all())

@main_bp.route('/assets/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_asset(id):
    asset = Asset.query.get_or_404(id)
    
    if request.method == 'POST':
        # Track changes
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

        price_form = request.form.get('price')
        price = float(price_form) if price_form else None
        if asset.price != price:
            changes.append(('price', asset.price, price))
        
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
        asset.price = price
        asset.currency = request.form.get('currency')
        asset.warranty_length = warranty_length
        asset.user_id = user_id
        asset.location_id = location_id
        asset.supplier_id = supplier_id
        asset.purchase_id = purchase_id
        
        db.session.commit()
        flash('Asset updated successfully!')
        return redirect(url_for('main.assets'))

    return render_template('assets/form.html',
                            asset=asset,
                            users=User.query.order_by(User.name).all(),
                            locations=Location.query.order_by(Location.name).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all())
@main_bp.route('/assets/<int:id>')
@login_required
def asset_detail(id):
    asset = Asset.query.get_or_404(id)
    return render_template('assets/detail.html', asset=asset)

# Peripheral routes
@main_bp.route('/peripherals')
@login_required
def peripherals():
    peripherals = Peripheral.query.all()
    return render_template('peripherals/list.html', peripherals=peripherals)

@main_bp.route('/peripherals/new', methods=['GET', 'POST'])
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
        return redirect(url_for('main.peripherals'))

    return render_template('peripherals/form.html',
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all())

@main_bp.route('/peripherals/<int:id>/edit', methods=['GET', 'POST'])
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
        return redirect(url_for('main.peripherals'))

    return render_template('peripherals/form.html',
                            peripheral=peripheral,
                            assets=Asset.query.order_by(Asset.name).all(),
                            purchases=Purchase.query.order_by(Purchase.description).all(),
                            suppliers=Supplier.query.order_by(Supplier.name).all())

# Location routes
@main_bp.route('/locations')
@login_required
def locations():
    locations = Location.query.all()
    return render_template('locations/list.html', locations=locations)

@main_bp.route('/locations/new', methods=['GET', 'POST'])
@login_required
def new_location():
    if request.method == 'POST':
        location = Location(name=request.form['name'])
        db.session.add(location)
        db.session.commit()
        flash('Location created successfully!')
        return redirect(url_for('main.locations'))
    
    return render_template('locations/form.html')

@main_bp.route('/locations/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_location(id):
    location = Location.query.get_or_404(id)
    
    if request.method == 'POST':
        location.name = request.form['name']
        db.session.commit()
        flash('Location updated successfully!')
        return redirect(url_for('main.locations'))
    
    return render_template('locations/form.html', location=location)

@main_bp.route('/locations/<int:id>')
@login_required
def location_detail(id):
    location = Location.query.get_or_404(id)
    return render_template('locations/detail.html', location=location)

# Budget routes
@main_bp.route('/budgets')
@login_required
def budgets():
    budgets = Budget.query.all()
    return render_template('budgets/list.html', budgets=budgets)

@main_bp.route('/budgets/<int:id>')
@login_required
def budget_detail(id):
    budget = Budget.query.get_or_404(id)
    return render_template('budgets/detail.html', budget=budget)

@main_bp.route('/budgets/new', methods=['GET', 'POST'])
@login_required
def new_budget():
    if request.method == 'POST':
        budget = Budget(
            name=request.form['name'],
            category=request.form.get('category'),
            amount=float(request.form['amount']),
            currency=request.form['currency'],
            period=request.form['period']
        )
        db.session.add(budget)
        db.session.commit()
        flash('Budget created successfully!')
        return redirect(url_for('main.budgets'))
    
    return render_template('budgets/form.html')

@main_bp.route('/budgets/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_budget(id):
    budget = Budget.query.get_or_404(id)
    
    if request.method == 'POST':
        budget.name = request.form['name']
        budget.category = request.form.get('category')
        budget.amount = float(request.form['amount'])
        budget.currency = request.form['currency']
        budget.period = request.form['period']
        db.session.commit()
        flash('Budget updated successfully!')
        return redirect(url_for('main.budgets'))
    
    return render_template('budgets/form.html', budget=budget)

# Supplier routes
@main_bp.route('/suppliers')
@login_required
def suppliers():
    suppliers = Supplier.query.all()
    return render_template('suppliers/list.html', suppliers=suppliers)

@main_bp.route('/suppliers/new', methods=['GET', 'POST'])
@login_required
def new_supplier():
    if request.method == 'POST':
        supplier = Supplier(
            name=request.form['name'],
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            address=request.form.get('address')
        )
        db.session.add(supplier)
        db.session.commit()
        flash('Supplier created successfully!')
        return redirect(url_for('main.suppliers'))
    
    return render_template('suppliers/form.html')

@main_bp.route('/suppliers/<int:id>')
@login_required
def supplier_detail(id):
    supplier = Supplier.query.get_or_404(id)
    return render_template('suppliers/detail.html', supplier=supplier)

@main_bp.route('/suppliers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    
    if request.method == 'POST':
        supplier.name = request.form['name']
        supplier.email = request.form.get('email')
        supplier.phone = request.form.get('phone')
        supplier.address = request.form.get('address')
        db.session.commit()
        flash('Supplier updated successfully!')
        return redirect(url_for('main.suppliers'))
    
    return render_template('suppliers/form.html', supplier=supplier)

@main_bp.route('/suppliers/<int:id>/delete', methods=['POST'])
@login_required
def delete_supplier(id):
    supplier = Supplier.query.get_or_404(id)
    db.session.delete(supplier)
    db.session.commit()
    flash('Supplier deleted successfully!')
    return redirect(url_for('main.suppliers'))

# Contact routes
@main_bp.route('/contacts')
@login_required
def contacts():
    contacts = Contact.query.join(Supplier).all()
    return render_template('contacts/list.html', contacts=contacts)

@main_bp.route('/contacts/<int:id>')
@login_required
def contact_detail(id):
    contact = Contact.query.get_or_404(id)
    return render_template('contacts/detail.html', contact=contact)

@main_bp.route('/contacts/new', methods=['GET', 'POST'])
@login_required
def new_contact():
    if request.method == 'POST':
        contact = Contact(
            name=request.form['name'],
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            role=request.form.get('role'),
            supplier_id=request.form['supplier_id']
        )
        db.session.add(contact)
        db.session.commit()
        flash('Contact created successfully!')
        return redirect(url_for('main.contacts'))
    
    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', suppliers=suppliers)

@main_bp.route('/contacts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_contact(id):
    contact = Contact.query.get_or_404(id)
    
    if request.method == 'POST':
        contact.name = request.form['name']
        contact.email = request.form.get('email')
        contact.phone = request.form.get('phone')
        contact.role = request.form.get('role')
        contact.supplier_id = request.form['supplier_id']
        db.session.commit()
        flash('Contact updated successfully!')
        return redirect(url_for('main.contacts'))
    
    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', contact=contact, suppliers=suppliers)

@main_bp.route('/contacts/<int:id>/delete', methods=['POST'])
@login_required
def delete_contact(id):
    contact = Contact.query.get_or_404(id)
    db.session.delete(contact)
    db.session.commit()
    flash('Contact deleted successfully!')
    return redirect(url_for('main.contacts'))

# Service routes
@main_bp.route('/services')
@login_required
def services():
    """
    Displays a list of services, with multiple filtering options.
    """
    # --- Get all active filters from URL query parameters ---
    service_type_filter = request.args.get('service_type')
    tag_filter = request.args.get('tag_id', type=int)
    month_filter = request.args.get('month') # e.g., "2025-09"

    # --- Build the base database query ---
    query = Service.query.join(Supplier).filter(Service.is_archived == False)
    
    # Apply filters to the database query if they exist
    if service_type_filter and service_type_filter != 'all':
        query = query.filter(Service.service_type == service_type_filter)

    if tag_filter:
        tag = Tag.query.get_or_404(tag_filter)
        query = query.filter(Service.tags.contains(tag))
    
    all_services = query.order_by(Service.name).all()

    # --- CORRECTED: Apply the month filter with the new centralized logic ---
    if month_filter:
        try:
            # Determine the start and end date of the target month
            filter_month_start = datetime.strptime(month_filter, '%Y-%m').date()
            filter_month_end = filter_month_start + relativedelta(months=+1, days=-1)

            filtered_services = []
            for service in all_services:
                next_renewal = service.next_renewal_date
                
                # Loop through the future renewals of this service
                while next_renewal <= filter_month_end:
                    # If a renewal falls within the target month, add it and stop checking this service
                    if next_renewal >= filter_month_start:
                        filtered_services.append(service)
                        break # Move to the next service
                    
                    # Use the centralized method to get the next date
                    next_renewal = service.get_renewal_date_after(next_renewal)
            
            all_services = filtered_services # Overwrite the list with the filtered results
        except ValueError:
            flash("Invalid month format in filter.", "error")

    # Calculate combined costs of listed items
    total_cost_of_listed_services = sum(service.cost_eur for service in all_services)

    # --- Prepare data for the filter dropdowns in the template ---
    service_types_query = db.session.query(Service.service_type).distinct().all()
    service_types = [st[0] for st in service_types_query]
    all_tags = Tag.query.order_by(Tag.name).all()

    return render_template('services/list.html', 
                            services=all_services,
                            service_types=service_types, 
                            selected_filter=service_type_filter,
                            tags=all_tags, 
                            selected_tag_id=tag_filter,
                            month_filter=month_filter,
                            total_cost=total_cost_of_listed_services)

@main_bp.route('/services/<int:id>')
@login_required
def service_detail(id):
    service = Service.query.get_or_404(id)
    
    # --- NEW: Prepare data for the cost history chart ---
    cost_history_labels = [entry.changed_date.strftime('%Y-%m-%d') for entry in service.cost_history]
    # We'll use the cost in EUR for consistency in the chart
    cost_history_data = [
        round(
            entry.cost * CURRENCY_RATES.get(entry.currency, 1.0), 2
        ) for entry in service.cost_history
    ]

    return render_template(
        'services/detail.html', 
        service=service,
        cost_history_labels=cost_history_labels,
        cost_history_data=cost_history_data
    )

@main_bp.route('/services/new', methods=['GET', 'POST'])
@login_required
def new_service():
    if request.method == 'POST':
        # Create the main service object from form data
        service = Service(
            name=request.form['name'],
            service_type=request.form['service_type'],
            description=request.form.get('description'),
            renewal_date=datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date(),
            renewal_period_type=request.form['renewal_period_type'],
            renewal_period_value=int(request.form.get('renewal_period_value', 1)),
            auto_renew='auto_renew' in request.form,
            cost=float(request.form['cost']),
            currency=request.form['currency'],
            supplier_id=request.form['supplier_id']
        )
        
        # Handle the advanced monthly renewal day logic
        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')
        
        # Create the initial cost history entry
        initial_cost = CostHistory(
            service=service, cost=service.cost, currency=service.currency, changed_date=date.today()
        )
        db.session.add(initial_cost)

        # Add associations from multi-select fields
        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact: service.contacts.append(contact)
            
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm: service.payment_methods.append(pm)

        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag: service.tags.append(tag)
        
        db.session.add(service)
        db.session.commit()
        flash('Service created successfully!')
        return redirect(url_for('main.services'))
    
    # For a GET request, fetch all data for the form's dropdowns
    return render_template('services/form.html', 
                            suppliers=Supplier.query.order_by(Supplier.name).all(), 
                            contacts=Contact.query.order_by(Contact.name).all(), 
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())
    if request.method == 'POST':
        # Create the main service object from form data
        service = Service(
            name=request.form['name'],
            service_type=request.form['service_type'],
            description=request.form.get('description'),
            renewal_date=datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date(),
            renewal_period_type=request.form['renewal_period_type'],
            renewal_period_value=int(request.form.get('renewal_period_value', 1)),
            auto_renew='auto_renew' in request.form,
            cost=float(request.form['cost']),
            currency=request.form['currency'],
            supplier_id=request.form['supplier_id']
        )

        # Logic to handle advanced monthly renewal day
        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector == 'first' or selector == 'last':
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')
            # If 'default', we do nothing, leaving it Non
        
        # Create the initial cost history entry for this new service
        initial_cost = CostHistory(
            service=service,
            cost=service.cost,
            currency=service.currency,
            changed_date=date.today()
        )
        db.session.add(initial_cost)

        # Add associations from the form's multi-select fields
        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact:
                service.contacts.append(contact)
            
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm:
                service.payment_methods.append(pm)

        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                service.tags.append(tag)
        
        db.session.add(service)
        db.session.commit()
        flash('Service created successfully!')
        return redirect(url_for('main.services'))
    
    # For a GET request, fetch all necessary data for the form's dropdowns
    return render_template('services/form.html', 
                            suppliers=Supplier.query.order_by(Supplier.name).all(), 
                            contacts=Contact.query.order_by(Contact.name).all(), 
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@main_bp.route('/services/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_service(id):
    service = Service.query.get_or_404(id)
    
    if request.method == 'POST':
        new_cost = float(request.form['cost'])
        new_currency = request.form['currency']

        # Check if the cost or currency has changed to create a history entry
        if service.cost != new_cost or service.currency != new_currency:
            cost_entry = CostHistory(
                service_id=service.id, cost=new_cost, currency=new_currency, changed_date=date.today()
            )
            db.session.add(cost_entry)

        # Update all fields on the service object
        service.name = request.form['name']
        service.service_type = request.form['service_type']
        service.description = request.form.get('description')
        service.renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        service.renewal_period_type = request.form['renewal_period_type']
        service.renewal_period_value = int(request.form.get('renewal_period_value', 1))
        service.auto_renew = 'auto_renew' in request.form
        service.cost = new_cost
        service.currency = new_currency
        service.supplier_id = request.form['supplier_id']
        
        # Handle the advanced monthly renewal day logic
        service.monthly_renewal_day = None # Reset first
        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')

        # Clear and update all associations
        service.contacts.clear()
        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact: service.contacts.append(contact)
            
        service.payment_methods.clear()
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm: service.payment_methods.append(pm)

        service.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag: service.tags.append(tag)
        
        db.session.commit()
        flash('Service updated successfully!')
        return redirect(url_for('main.service_detail', id=service.id))
    
    # For a GET request, fetch all data needed to populate the edit form
    return render_template('services/form.html', 
                            service=service,
                            suppliers=Supplier.query.order_by(Supplier.name).all(), 
                            contacts=Contact.query.order_by(Contact.name).all(), 
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())
    service = Service.query.get_or_404(id)
    
    if request.method == 'POST':
        new_cost = float(request.form['cost'])
        new_currency = request.form['currency']

        # Check if the cost or currency has changed to create a history entry
        if service.cost != new_cost or service.currency != new_currency:
            cost_entry = CostHistory(
                service_id=service.id,
                cost=new_cost,
                currency=new_currency,
                changed_date=date.today()
            )
            db.session.add(cost_entry)

        # Update all fields on the service object
        service.name = request.form['name']
        service.service_type = request.form['service_type']
        service.description = request.form.get('description')
        service.renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        service.renewal_period_type = request.form['renewal_period_type']
        service.renewal_period_value = int(request.form.get('renewal_period_value', 1))
        service.auto_renew = 'auto_renew' in request.form
        service.cost = new_cost
        service.currency = new_currency
        service.supplier_id = request.form['supplier_id']
        
        # Logic to handle advanced monthly renewal day ---
        service.monthly_renewal_day = None # Reset first
        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector == 'first' or selector == 'last':
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')

        # Clear and update all associations
        service.contacts.clear()
        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact:
                service.contacts.append(contact)
            
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm:
                service.payment_methods.append(pm)

        service.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                service.tags.append(tag)
        
        db.session.commit()
        flash('Service updated successfully!')
        return redirect(url_for('main.service_detail', id=service.id))
    
    # For a GET request, fetch all data needed to populate the edit form
    return render_template('services/form.html', 
                            service=service,
                            suppliers=Supplier.query.order_by(Supplier.name).all(), 
                            contacts=Contact.query.order_by(Contact.name).all(), 
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@main_bp.route('/services/<int:id>/delete', methods=['POST'])
@login_required
def delete_service(id):
    service = Service.query.get_or_404(id)
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted successfully!')
    return redirect(url_for('main.services'))

# Calendar routes
@main_bp.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')

@main_bp.route('/api/calendar-events')
@login_required
def calendar_events():
    """
    Generates all recurring renewal events for the calendar's visible date range.
    """
    # Get the start and end dates from the calendar's request
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    try:
        # Convert the string dates from the request into date objects
        start_date = datetime.fromisoformat(start_str).date()
        end_date = datetime.fromisoformat(end_str).date()
    except (ValueError, TypeError):
        # If dates are invalid, return an error
        return jsonify({"error": "Invalid date format"}), 400

    all_active_services = Service.query.filter_by(is_archived=False).all()
    events = []

    for service in all_active_services:
        next_renewal = service.next_renewal_date
        
        # Loop through all future renewals of this service
        while next_renewal < end_date:
            # If a renewal falls within the calendar's visible window, create an event
            if next_renewal >= start_date:
                events.append({
                    'id': service.id,
                    'title': service.name,
                    'start': next_renewal.isoformat(),
                    'backgroundColor': '#007bff' if service.auto_renew else '#ffc107',
                    'borderColor': '#007bff' if service.auto_renew else '#ffc107',
                    'url': url_for('main.service_detail', id=service.id),
                    'extendedProps': {
                        'service_name': service.name,
                        'cost_eur': f"€{service.cost_eur:.2f}"
                    }
                })

            # CORRECTED: Use the centralized method to calculate the next occurrence
            next_renewal = service.get_renewal_date_after(next_renewal)
                
    return jsonify(events)

# Payment routes
@main_bp.route('/payment-methods')
@login_required
def payment_methods():
    methods = PaymentMethod.query.all()
    return render_template('payment_methods/list.html', payment_methods=methods)

@main_bp.route('/payment-methods/<int:id>')
@login_required
def payment_method_detail(id):
    method = PaymentMethod.query.get_or_404(id)
    return render_template('payment_methods/detail.html', method=method)

@main_bp.route('/payment-methods/new', methods=['GET', 'POST'])
@login_required
def new_payment_method():
    if request.method == 'POST':
        expiry_date = None
        # UPDATE THE LINE BELOW to parse 'MM/YY' format
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
        return redirect(url_for('main.payment_methods'))
    
    return render_template('payment_methods/form.html')

@main_bp.route('/payment-methods/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    if request.method == 'POST':
        expiry_date = None
        # UPDATE THE LINE BELOW to parse 'MM/YY' format
        if request.form.get('expiry_date'):
            expiry_date = datetime.strptime(request.form['expiry_date'], '%m/%y').date()

        method.name = request.form['name']
        method.method_type = request.form['method_type']
        method.details = request.form.get('details')
        method.expiry_date = expiry_date
        db.session.commit()
        flash('Payment method updated successfully!')
        return redirect(url_for('main.payment_methods'))
    
    return render_template('payment_methods/form.html', method=method)

@main_bp.route('/payment-methods/<int:id>/delete', methods=['POST'])
@login_required
def delete_payment_method(id):
    method = PaymentMethod.query.get_or_404(id)
    db.session.delete(method)
    db.session.commit()
    flash('Payment method deleted successfully!')
    return redirect(url_for('main.payment_methods'))

# Notification Settings Route
@main_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    # Get the first settings object, or create one if it doesn't exist
    settings = NotificationSetting.query.first()
    if not settings:
        settings = NotificationSetting()
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        settings.email_enabled = 'email_enabled' in request.form
        settings.email_recipient = request.form.get('email_recipient')
        settings.webhook_enabled = 'webhook_enabled' in request.form
        settings.webhook_url = request.form.get('webhook_url')
        
        # Collect checked days and join them into a string
        days_before = request.form.getlist('days_before')
        settings.notify_days_before = ','.join(days_before)
        
        db.session.commit()
        flash('Notification settings updated successfully!')
        return redirect(url_for('main.notification_settings'))

    # For the template, create a list of integers from the string
    notify_days_list = [int(day) for day in settings.notify_days_before.split(',') if day]
    
    return render_template(
        'notifications/settings.html', 
        settings=settings, 
        notify_days_list=notify_days_list
    )

# Archived services routes
@main_bp.route('/services/archived')
@login_required
def archived_services():
    """Displays a list of all archived services."""
    archived = Service.query.filter_by(is_archived=True).order_by(Service.name).all()
    return render_template('services/archived.html', services=archived)

@main_bp.route('/services/<int:id>/archive', methods=['POST'])
@login_required
def archive_service(id):
    """Sets a service's status to archived."""
    service = Service.query.get_or_404(id)
    service.is_archived = True
    db.session.commit()
    flash(f'Service "{service.name}" has been archived.')
    return redirect(url_for('main.services'))

@main_bp.route('/services/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_service(id):
    """Restores an archived service to active."""
    service = Service.query.get_or_404(id)
    service.is_archived = False
    db.session.commit()
    flash(f'Service "{service.name}" has been restored.')
    return redirect(url_for('main.archived_services'))

# Attachment Routes

@main_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    service_id = request.form.get('service_id')
    supplier_id = request.form.get('supplier_id')
    purchase_id = request.form.get('purchase_id')
    asset_id = request.form.get('asset_id')
    peripheral_id = request.form.get('peripheral_id')
    
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.referrer)
        
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.referrer)

    if file:
        original_filename = secure_filename(file.filename)
        # Create a unique filename to prevent conflicts
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
        
        new_attachment = Attachment(
            filename=original_filename,
            secure_filename=unique_filename,
            service_id=service_id if service_id else None,
            supplier_id=supplier_id if supplier_id else None,
            purchase_id=purchase_id if purchase_id else None,
            asset_id=asset_id if asset_id else None,
            peripheral_id=peripheral_id if peripheral_id else None
        )
        db.session.add(new_attachment)
        db.session.commit()
        flash('File uploaded successfully!')

    return redirect(request.referrer) # Redirect back to the page they were on


@main_bp.route('/download/<int:attachment_id>')
@login_required
def download_file(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'], 
        attachment.secure_filename, 
        as_attachment=True, 
        download_name=attachment.filename
    )

@main_bp.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    
    # Delete file from filesystem
    os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.secure_filename))
    
    # Delete record from database
    db.session.delete(attachment)
    db.session.commit()
    flash('Attachment deleted successfully.')
    return redirect(request.referrer)

# Tags routes
@main_bp.route('/tags')
@login_required
def tags():
    all_tags = Tag.query.order_by(Tag.name).all()
    return render_template('tags/list.html', tags=all_tags)

@main_bp.route('/tags/new', methods=['GET', 'POST'])
@login_required
def new_tag():
    if request.method == 'POST':
        tag_name = request.form.get('name')
        if tag_name and not Tag.query.filter_by(name=tag_name).first():
            new_tag = Tag(name=tag_name)
            db.session.add(new_tag)
            db.session.commit()
            flash(f'Tag "{tag_name}" created successfully.')
        else:
            flash(f'Tag "{tag_name}" already exists or is invalid.', 'error')
        return redirect(url_for('main.tags'))
    return render_template('tags/form.html')

@main_bp.route('/tags/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_tag(id):
    tag = Tag.query.get_or_404(id)
    if request.method == 'POST':
        new_name = request.form.get('name')
        if new_name:
            tag.name = new_name
            db.session.commit()
            flash('Tag updated successfully!')
            return redirect(url_for('main.tags'))
    return render_template('tags/form.html', tag=tag)

@main_bp.route('/tags/<int:id>/delete', methods=['POST'])
@login_required
def delete_tag(id):
    tag = Tag.query.get_or_404(id)
    db.session.delete(tag)
    db.session.commit()
    flash(f'Tag "{tag.name}" deleted successfully.')
    return redirect(url_for('main.tags'))

# Reports Route
@main_bp.route('/subscription-reports')
@login_required
def subscription_reports():
    today = date.today()
    selected_year = request.args.get('year', default=today.year, type=int)

    supplier_spending = {}

    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)

    all_active_services = Service.query.filter_by(is_archived=False).all()

    # --- Chart 1: Spending by Supplier) ---
    supplier_spending = {} # Use a dictionary to aggregate costs
    
    # Define the start and end of the selected year
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)

    for service in all_active_services:
        renewal = service.renewal_date
        # Fast-forward to the start of the selected year
        while renewal < year_start:
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)
        
        # Now, log every renewal that falls within the selected year
        while renewal <= year_end:
            supplier_name = service.supplier.name
            if supplier_name not in supplier_spending:
                supplier_spending[supplier_name] = 0
            supplier_spending[supplier_name] += service.cost_eur
            
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)
    
    # Sort suppliers by total spending
    sorted_supplier_spending = sorted(supplier_spending.items(), key=lambda item: item[1], reverse=True)
    
    supplier_labels = [item[0] for item in sorted_supplier_spending]
    supplier_data = [round(item[1], 2) for item in sorted_supplier_spending]

    # --- Get available years for the dropdown ---
    available_years_query = db.session.query(func.strftime('%Y', Service.renewal_date)).distinct().order_by(func.strftime('%Y', Service.renewal_date).desc()).all()
    available_years = [int(y[0]) for y in available_years_query]

    # --- Chart 2 (Services by type) ---

    services_by_type = db.session.query(Service.service_type, func.count(Service.id)).filter(Service.is_archived == False).group_by(Service.service_type).order_by(func.count(Service.id).desc()).all()
    type_labels = [item[0].title() for item in services_by_type]
    type_data = [item[1] for item in services_by_type]
    
    all_active_services = Service.query.filter_by(is_archived=False).all()
    today = date.today()

    # --- CORRECTED: Chart 3 & 4: Historical Spending ---
    # Monthly Spending (Last 12 full months + current month)
    monthly_start_date = (today.replace(day=1) - relativedelta(months=12))
    monthly_labels, monthly_costs = [], {}
    for i in range(13):
        month_date = monthly_start_date + relativedelta(months=i)
        year_month_key = month_date.strftime('%Y-%m')
        monthly_labels.append(month_date.strftime('%b %Y'))
        monthly_costs[year_month_key] = 0

    # Yearly Spending (Last 4 full years + current year)
    yearly_start_date = today.replace(year=today.year - 4, month=1, day=1)
    yearly_labels, yearly_costs = [], {}
    for i in range(5):
        year_date = yearly_start_date + relativedelta(years=i)
        yearly_labels.append(year_date.strftime('%Y'))
        yearly_costs[year_date.strftime('%Y')] = 0
        
    for service in all_active_services:
        # Start from the service's very first renewal date for historical accuracy
        renewal = service.renewal_date
        # Fast-forward to the start of our historical window
        while renewal < yearly_start_date:
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)
        
        # Now, log every renewal event that occurred up until today
        while renewal <= today:
            year_key = renewal.strftime('%Y')
            if year_key in yearly_costs:
                yearly_costs[year_key] += service.cost_eur
            
            month_key = renewal.strftime('%Y-%m')
            if month_key in monthly_costs:
                monthly_costs[month_key] += service.cost_eur

            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)

    monthly_data = [round(cost, 2) for cost in monthly_costs.values()]
    yearly_data = [round(cost, 2) for cost in yearly_costs.values()]
    
    # --- Forecast Chart Logic (This is also corrected to match the dashboard) ---
    end_of_forecast_period = today + relativedelta(months=+13)
    forecast_labels, forecast_keys, forecast_costs = [], [], {}
    for i in range(13):
        month_date = today + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_keys.append(year_month_key)
        forecast_costs[year_month_key] = 0

    for service in all_active_services:
        renewal = service.next_renewal_date
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += service.cost_eur
            if service.renewal_period_type == 'monthly':
                renewal += relativedelta(months=+service.renewal_period_value)
            elif service.renewal_period_type == 'yearly':
                renewal += relativedelta(years=+service.renewal_period_value)
            else:
                renewal += timedelta(days=service.renewal_period_value)
    
    forecast_data = [round(cost, 2) for cost in forecast_costs.values()]

    return render_template(
        'reports/subscription_reports.html',
        supplier_labels=supplier_labels, supplier_data=supplier_data,
        type_labels=type_labels, type_data=type_data,
        monthly_labels=monthly_labels, monthly_data=monthly_data,
        yearly_labels=yearly_labels, yearly_data=yearly_data,
        forecast_labels=forecast_labels, forecast_data=forecast_data,
        available_years=available_years, selected_year=selected_year
    )

@main_bp.route('/asset-reports')
@login_required
def asset_reports():
    assets_by_brand = db.session.query(Asset.brand, func.count(Asset.id)).group_by(Asset.brand).all()
    brand_labels = [item[0] for item in assets_by_brand]
    brand_data = [item[1] for item in assets_by_brand]

    assets_by_supplier = db.session.query(Supplier.name, func.count(Asset.id)).join(Asset).group_by(Supplier.name).all()
    supplier_labels = [item[0] for item in assets_by_supplier]
    supplier_data = [item[1] for item in assets_by_supplier]

    assets_by_status = db.session.query(Asset.status, func.count(Asset.id)).group_by(Asset.status).all()
    status_labels = [item[0] for item in assets_by_status]
    status_data = [item[1] for item in assets_by_status]

    today = date.today()
    warranty_active = Asset.query.filter(Asset.purchase_date + func.cast(Asset.warranty_length, db.Interval) > today).count()
    warranty_expired = Asset.query.count() - warranty_active
    warranty_labels = ['Active', 'Expired']
    warranty_data = [warranty_active, warranty_expired]

    return render_template(
        'reports/asset_reports.html',
        brand_labels=brand_labels,
        brand_data=brand_data,
        supplier_labels=supplier_labels,
        supplier_data=supplier_data,
        status_labels=status_labels,
        status_data=status_data,
        warranty_labels=warranty_labels,
        warranty_data=warranty_data,
    )

@main_bp.route('/warranties')
@login_required
def warranties():
    assets = Asset.query.all()
    return render_template('assets/warranties.html', assets=assets)