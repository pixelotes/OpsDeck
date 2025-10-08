from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
)
from sqlalchemy import or_
from functools import wraps
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
from ..models import db, AppUser, Service, NotificationSetting, Asset, Supplier, Contact, Purchase, Peripheral

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
            next_renewal = service.get_renewal_date_after(next_renewal)
    upcoming_renewals.sort(key=lambda x: x[0])

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
        renewal = service.renewal_date
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += service.cost_eur
            renewal = service.get_renewal_date_after(renewal)

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

    # Search Services
    services = Service.query.filter(Service.name.ilike(search_term), Service.is_archived == False).limit(limit).all()
    for item in services:
        results.append({
            'name': item.name,
            'type': 'Service',
            'url': url_for('services.service_detail', id=item.id)
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