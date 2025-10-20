from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
)
from sqlalchemy import or_
from markupsafe import Markup
from functools import wraps
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
from ..models import db, User, Subscription, NotificationSetting, Asset, Supplier, Contact, Purchase, Peripheral, Location, PaymentMethod
import calendar

main_bp = Blueprint('main', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'] # Changed from username
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid email or password')

    return render_template('login.html')

@main_bp.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    return redirect(url_for('main.login'))

def password_change_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id)
            if user and user.name == 'admin' and user.check_password('admin123'): # Check name for default admin
                if request.endpoint not in ['main.change_password', 'main.logout', 'static']: # Check if request is not for allowed endpoints

                    link = url_for('main.change_password')
                    message_text = f'For security, you must change the default admin password. <a href="{link}" class="alert-link">Click here to change it now.</a>'
                    message = Markup(message_text)
                    
                    # Check if there's already a "warning" message in the queue
                    flashed_messages = session.get('_flashed_messages', [])
                    message_already_flashed = any(
                        msg[0] == 'warning' and msg[1] == message_text
                        for msg in flashed_messages
                    )

                    if not message_already_flashed:
                        flash(message, 'warning') # Add only if message is missing
                        
                    return redirect(url_for('main.change_password'))
        return f(*args, **kwargs)
    return decorated_function

@main_bp.route('/')
@login_required
def dashboard():
    # --- STAT CARD COUNTS ---
    stats = {
        'subscriptions': Subscription.query.filter_by(is_archived=False).count(),
        'assets': Asset.query.filter_by(is_archived=False).count(),
        'peripherals': Peripheral.query.filter_by(is_archived=False).count(),
        'suppliers': Supplier.query.filter_by(is_archived=False).count(),
        'users': User.query.filter_by(is_archived=False).count(),
        'locations': Location.query.filter_by(is_archived=False).count(),
        'contacts': Contact.query.filter_by(is_archived=False).count(),
        'payment_methods': PaymentMethod.query.filter_by(is_archived=False).count(),
    }

    # --- Upcoming Renewals & Filter Logic ---
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

    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()
    upcoming_renewals, total_cost = [], 0

    for subscription in all_active_subscriptions:
        next_renewal = subscription.next_renewal_date
        while next_renewal <= end_date:
            if next_renewal >= start_date:
                upcoming_renewals.append((next_renewal, subscription))
                total_cost += subscription.cost_eur
            next_renewal = subscription.get_renewal_date_after(next_renewal)
            
    upcoming_renewals.sort(key=lambda x: x[0])

    # --- Forecast Chart Logic ---
    forecast_start_date = today.replace(day=1)
    end_of_forecast_period = forecast_start_date + relativedelta(months=+13)

    forecast_labels, forecast_keys, forecast_costs = [], [], {}
    for i in range(13):
        month_date = forecast_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_keys.append(year_month_key)
        forecast_costs[year_month_key] = 0

    for subscription in all_active_subscriptions:
        renewal = subscription.renewal_date
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += subscription.cost_eur
            renewal = subscription.get_renewal_date_after(renewal)

    forecast_data = [round(cost, 2) for cost in forecast_costs.values()]

    # --- CORRECTED: EXPIRING ITEMS LOGIC ---
    thirty_days_from_now = today + timedelta(days=30)
    
    # Query only non-archived items with warranty info
    expiring_assets = Asset.query.filter(
        Asset.is_archived == False,
        Asset.purchase_date.isnot(None), 
        Asset.warranty_length.isnot(None)
    ).all()
    expiring_peripherals = Peripheral.query.filter(
        Peripheral.is_archived == False,
        Peripheral.purchase_date.isnot(None), 
        Peripheral.warranty_length.isnot(None)
    ).all()
    
    all_expiring_items = [
        item for item in expiring_assets + expiring_peripherals 
        if item.warranty_end_date and today <= item.warranty_end_date <= thirty_days_from_now
    ]
    all_expiring_items.sort(key=lambda x: x.warranty_end_date)

    # CORRECTED: Payment methods expiring in the next 90 days
    ninety_days_from_now = today + timedelta(days=90)
    expiring_payment_methods = []
    all_payment_methods = PaymentMethod.query.filter(
        PaymentMethod.is_archived == False,
        PaymentMethod.expiry_date.isnot(None)
    ).order_by(PaymentMethod.expiry_date).all()

    for method in all_payment_methods:
        # Find the last day of the expiry month
        last_day_of_expiry_month = method.expiry_date.replace(day=calendar.monthrange(method.expiry_date.year, method.expiry_date.month)[1])
        if today <= last_day_of_expiry_month <= ninety_days_from_now:
            expiring_payment_methods.append(method)

    return render_template(
        'dashboard.html',
        stats=stats,
        upcoming_renewals=upcoming_renewals,
        total_cost=total_cost,
        selected_period=period,
        today=today,
        forecast_labels=forecast_labels,
        forecast_keys=forecast_keys,
        forecast_data=forecast_data,
        expiring_items=all_expiring_items,
        expiring_payment_methods=expiring_payment_methods
    )


@main_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
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

        days_before = request.form.getlist('days_before')
        settings.notify_days_before = ','.join(days_before)

        db.session.commit()
        flash('Notification settings updated successfully!')
        return redirect(url_for('main.notification_settings'))

    notify_days_list = [int(day) for day in settings.notify_days_before.split(',') if day]

    return render_template(
        'notifications/settings.html',
        settings=settings,
        notify_days_list=notify_days_list
    )

@main_bp.route('/api/search')
@login_required
def search():
    query = request.args.get('q', '').strip()
    results = []

    if len(query) < 2:
        return jsonify([])

    search_term = f'%{query}%'
    limit = 5

    # Search Subscriptions
    subscriptions = Subscription.query.filter(Subscription.name.ilike(search_term), Subscription.is_archived == False).limit(limit).all()
    for item in subscriptions:
        results.append({
            'name': item.name,
            'type': 'Subscription',
            'url': url_for('subscriptions.subscription_detail', id=item.id)
        })

    # Search Assets
    assets = Asset.query.filter(
        or_(
            Asset.name.ilike(search_term),
            Asset.serial_number.ilike(search_term)
        ), Asset.is_archived == False
    ).limit(limit).all()
    for item in assets:
        results.append({
            'name': item.name,
            'type': 'Asset',
            'url': url_for('assets.asset_detail', id=item.id)
        })

    # Search Suppliers
    suppliers = Supplier.query.filter(Supplier.name.ilike(search_term), Supplier.is_archived == False).limit(limit).all()
    for item in suppliers:
        results.append({
            'name': item.name,
            'type': 'Supplier',
            'url': url_for('suppliers.supplier_detail', id=item.id)
        })

    # Search Contacts
    contacts = Contact.query.filter(Contact.name.ilike(search_term), Contact.is_archived == False).limit(limit).all()
    for item in contacts:
        results.append({
            'name': f"{item.name} ({item.supplier.name})",
            'type': 'Contact',
            'url': url_for('contacts.contact_detail', id=item.id)
        })
    
    # Search Purchases
    purchases = Purchase.query.filter(Purchase.description.ilike(search_term)).limit(limit).all()
    for item in purchases:
        results.append({
            'name': item.description,
            'type': 'Purchase',
            'url': url_for('purchases.purchase_detail', id=item.id)
        })

    # Search Peripherals
    peripherals = Peripheral.query.filter(
        or_(
            Peripheral.name.ilike(search_term),
            Peripheral.serial_number.ilike(search_term)
        ), Peripheral.is_archived == False
    ).limit(limit).all()
    for item in peripherals:
        results.append({
            'name': item.name,
            'type': 'Peripheral',
            'url': url_for('peripherals.edit_peripheral', id=item.id)
        })

    return jsonify(results)


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        user = User.query.get(session['user_id'])

        if not user.check_password(current_password):
            flash('Your current password was incorrect.', 'danger')
        elif new_password != confirm_password:
            flash('The new passwords do not match.', 'danger')
        elif len(new_password) < 8:
            flash('The new password must be at least 8 characters long.', 'danger')
        else:
            user.set_password(new_password)
            db.session.commit()
            flash('Your password has been updated successfully!', 'success')
            return redirect(url_for('main.dashboard'))

    return render_template('change_password.html')