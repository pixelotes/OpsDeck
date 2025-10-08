from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from functools import wraps
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from ..models import db, AppUser, Service, NotificationSetting

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
    # ... (dashboard logic remains the same)
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