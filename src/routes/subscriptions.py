from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from ..models import db, Subscription, Supplier, Contact, PaymentMethod, Tag, CostHistory, Software, Budget, User
from ..services.finance_service import get_conversion_rate
from ..services.permissions_service import requires_permission
from .main import login_required
from src.utils.timezone_helper import today


subscriptions_bp = Blueprint('subscriptions', __name__)

@subscriptions_bp.route('/')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def subscriptions():
    subscription_type_filter = request.args.get('subscription_type')
    tag_filter = request.args.get('tag_id', type=int)
    month_filter = request.args.get('month')

    query = Subscription.query.join(Supplier).filter(Subscription.is_archived == False)

    if subscription_type_filter and subscription_type_filter != 'all':
        query = query.filter(Subscription.subscription_type == subscription_type_filter)

    if tag_filter:
        tag = Tag.query.get_or_404(tag_filter)
        query = query.filter(Subscription.tags.contains(tag))

    all_subscriptions = query.order_by(Subscription.name).all()

    if month_filter:
        try:
            filter_month_start = datetime.strptime(month_filter, '%Y-%m').date()
            filter_month_end = filter_month_start + relativedelta(months=+1, days=-1)

            filtered_subscriptions = []
            for subscription in all_subscriptions:
                next_renewal = subscription.renewal_date
                while next_renewal <= filter_month_end:
                    if next_renewal >= filter_month_start:
                        filtered_subscriptions.append(subscription)
                        break
                    next_renewal = subscription.get_renewal_date_after(next_renewal)

            all_subscriptions = filtered_subscriptions
        except ValueError:
            flash("Invalid month format in filter.", "error")

    total_cost_of_listed_subscriptions = sum(subscription.cost_eur for subscription in all_subscriptions)

    subscription_types_query = db.session.query(Subscription.subscription_type).distinct().all()
    subscription_types = [st[0] for st in subscription_types_query]
    all_tags = Tag.query.order_by(Tag.name).all()

    return render_template('subscriptions/list.html',
                            subscriptions=all_subscriptions,
                            subscription_types=subscription_types,
                            selected_filter=subscription_type_filter,
                            tags=all_tags,
                            selected_tag_id=tag_filter,
                            month_filter=month_filter,
                            total_cost=total_cost_of_listed_subscriptions)

@subscriptions_bp.route('/<int:id>')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def subscription_detail(id):
    subscription = Subscription.query.get_or_404(id)
    cost_history_labels = [entry.changed_date.strftime('%Y-%m-%d') for entry in subscription.cost_history]
    cost_history_data = [
        round(
            entry.cost * get_conversion_rate(entry.currency), 2
        ) for entry in subscription.cost_history
    ]

    all_users = User.query.filter_by(is_archived=False).order_by(User.name).all()

    return render_template(
        'subscriptions/detail.html',
        subscription=subscription,
        cost_history_labels=cost_history_labels,
        cost_history_data=cost_history_data,
        all_users=all_users
    )

@subscriptions_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def new_subscription():
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()

    users = User.query.filter_by(is_archived=False).all()

    if request.method == 'POST':
        # Manual check for WRITE access
        from ..services.permissions_cache import permissions_cache
        from ..services.permissions_service import get_user_modules
        from flask import session
        user_id = session.get('user_id')
        user_role = session.get('user_role')
        if (user_role or session.get('role')) != 'admin':
            perms = permissions_cache.get(user_id)
            if perms is None:
                get_user_modules(user_id)
                perms = permissions_cache.get(user_id)
            if perms.get('core_inventory') != 'WRITE':
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('subscriptions.subscriptions'))
        renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None

        # Validate renewal_date is not too far in the past (prevents performance issues)
        from datetime import timedelta
        current_date = today()
        days_in_past = (current_date - renewal_date).days if renewal_date < current_date else 0

        if days_in_past > 365:
            flash('Error: Renewal date cannot be more than 1 year in the past. Please use a more recent date.', 'danger')
            return render_template('subscriptions/form.html',
                                    suppliers=Supplier.query.order_by(Supplier.name).all(),
                                    contacts=Contact.query.order_by(Contact.name).all(),
                                    payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                    tags=Tag.query.order_by(Tag.name).all(),
                                    software_items=software_items,
                                    budgets=Budget.query.order_by(Budget.name).all(),
                                    users=users)
        elif days_in_past > 30:
            flash(f'Warning: Renewal date is {days_in_past} days in the past. The next renewal will be calculated from this date.', 'warning')

        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(renewal_date):
                flash('Error: This subscription renewal date is outside the selected Budget\'s validity period.', 'danger')
                return render_template('subscriptions/form.html',
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)

        # Validate cost
        try:
            cost = float(request.form['cost'])
            if cost <= 0:
                flash('Error: Subscription cost must be greater than 0.', 'danger')
                return render_template('subscriptions/form.html',
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)
        except (ValueError, KeyError):
            flash('Error: Invalid cost value.', 'danger')
            return render_template('subscriptions/form.html',
                                    suppliers=Supplier.query.order_by(Supplier.name).all(),
                                    contacts=Contact.query.order_by(Contact.name).all(),
                                    payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                    tags=Tag.query.order_by(Tag.name).all(),
                                    software_items=software_items,
                                    budgets=Budget.query.order_by(Budget.name).all(),
                                    users=users)

        user_id = request.form.get('user_id')

        subscription = Subscription(
            name=request.form['name'],
            subscription_type=request.form['subscription_type'],
            description=request.form.get('description'),
            renewal_date=renewal_date,
            renewal_period_type=request.form['renewal_period_type'],
            renewal_period_value=int(request.form.get('renewal_period_value', 1)),
            auto_renew='auto_renew' in request.form,
            cost=cost,
            currency=request.form['currency'],
            supplier_id=request.form.get('supplier_id') or None,
            software_id=request.form.get('software_id') or None,
            budget_id=budget_id,
            user_id=int(user_id) if user_id else None
        )

        if subscription.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                subscription.monthly_renewal_day = selector
            elif selector == 'specific':
                subscription.monthly_renewal_day = request.form.get('monthly_renewal_day')

        initial_cost = CostHistory(
            subscription=subscription, cost=subscription.cost, currency=subscription.currency, changed_date=today()
        )
        db.session.add(initial_cost)

        for contact_id in request.form.getlist('contact_ids'):
            contact = db.session.get(Contact,contact_id)
            if contact: subscription.contacts.append(contact)

        for pm_id in request.form.getlist('payment_method_ids'):
            pm = db.session.get(PaymentMethod,pm_id)
            if pm: subscription.payment_methods.append(pm)

        for tag_id in request.form.getlist('tag_ids'):
            tag = db.session.get(Tag,tag_id)
            if tag: subscription.tags.append(tag)

        db.session.add(subscription)
        db.session.commit()
        flash('Subscription created successfully!')
        return redirect(url_for('subscriptions.subscriptions'))

    return render_template('subscriptions/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            software_items=software_items,
                            budgets=Budget.query.order_by(Budget.name).all(),
                            users=users)

@subscriptions_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def edit_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()

    users = User.query.filter_by(is_archived=False).all()

    if request.method == 'POST':
        # Manual check for WRITE access
        from ..services.permissions_cache import permissions_cache
        from ..services.permissions_service import get_user_modules
        from flask import session
        user_id = session.get('user_id')
        user_role = session.get('user_role')
        if (user_role or session.get('role')) != 'admin':
            perms = permissions_cache.get(user_id)
            if perms is None:
                get_user_modules(user_id)
                perms = permissions_cache.get(user_id)
            if perms.get('core_inventory') != 'WRITE':
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('subscriptions.subscription_detail', id=id))
        renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None

        # Validate renewal_date is not too far in the past (prevents performance issues)
        from datetime import timedelta
        current_date = today()
        days_in_past = (current_date - renewal_date).days if renewal_date < current_date else 0

        if days_in_past > 365:
            flash('Error: Renewal date cannot be more than 1 year in the past. Please use a more recent date.', 'danger')
            return render_template('subscriptions/form.html',
                                    subscription=subscription,
                                    suppliers=Supplier.query.order_by(Supplier.name).all(),
                                    contacts=Contact.query.order_by(Contact.name).all(),
                                    payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                    tags=Tag.query.order_by(Tag.name).all(),
                                    software_items=software_items,
                                    budgets=Budget.query.order_by(Budget.name).all(),
                                    users=users)
        elif days_in_past > 30:
            flash(f'Warning: Renewal date is {days_in_past} days in the past. The next renewal will be calculated from this date.', 'warning')

        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(renewal_date):
                flash('Error: This subscription renewal date is outside the selected Budget\'s validity period.', 'danger')
                return render_template('subscriptions/form.html',
                                        subscription=subscription,
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)

        # Validate cost
        try:
            new_cost = float(request.form['cost'])
            if new_cost <= 0:
                flash('Error: Subscription cost must be greater than 0.', 'danger')
                return render_template('subscriptions/form.html',
                                        subscription=subscription,
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)
        except (ValueError, KeyError):
            flash('Error: Invalid cost value.', 'danger')
            return render_template('subscriptions/form.html',
                                    subscription=subscription,
                                    suppliers=Supplier.query.order_by(Supplier.name).all(),
                                    contacts=Contact.query.order_by(Contact.name).all(),
                                    payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                    tags=Tag.query.order_by(Tag.name).all(),
                                    software_items=software_items,
                                    budgets=Budget.query.order_by(Budget.name).all(),
                                    users=users)

        new_currency = request.form['currency']

        if subscription.cost != new_cost or subscription.currency != new_currency:
            cost_entry = CostHistory(
                subscription_id=subscription.id, cost=new_cost, currency=new_currency, changed_date=today()
            )
            db.session.add(cost_entry)

        subscription.name = request.form['name']
        subscription.subscription_type = request.form['subscription_type']
        subscription.description = request.form.get('description')
        subscription.renewal_date = renewal_date
        subscription.renewal_period_type = request.form['renewal_period_type']
        subscription.renewal_period_value = int(request.form.get('renewal_period_value', 1))
        subscription.auto_renew = 'auto_renew' in request.form
        subscription.cost = new_cost
        subscription.currency = new_currency
        subscription.supplier_id = request.form.get('supplier_id') or None
        subscription.software_id = request.form.get('software_id') or None
        subscription.budget_id = budget_id
        
        user_id = request.form.get('user_id')
        subscription.user_id = int(user_id) if user_id else None
        
        subscription.monthly_renewal_day = None
        if subscription.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                subscription.monthly_renewal_day = selector
            elif selector == 'specific':
                subscription.monthly_renewal_day = request.form.get('monthly_renewal_day')

        subscription.contacts.clear()
        for contact_id in request.form.getlist('contact_ids'):
            contact = db.session.get(Contact,contact_id)
            if contact: subscription.contacts.append(contact)

        subscription.payment_methods.clear()
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = db.session.get(PaymentMethod,pm_id)
            if pm: subscription.payment_methods.append(pm)

        subscription.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = db.session.get(Tag,tag_id)
            if tag: subscription.tags.append(tag)

        db.session.commit()
        flash('Subscription updated successfully!')
        return redirect(url_for('subscriptions.subscription_detail', id=subscription.id))

    return render_template('subscriptions/form.html',
                            subscription=subscription,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            software_items=software_items,
                            budgets=Budget.query.order_by(Budget.name).all(),
                            users=users)

@subscriptions_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def delete_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    db.session.delete(subscription)
    db.session.commit()
    flash('Subscription deleted successfully!')
    return redirect(url_for('subscriptions.subscriptions'))

@subscriptions_bp.route('/archived')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def archived_subscriptions():
    archived = Subscription.query.filter_by(is_archived=True).order_by(Subscription.name).all()
    return render_template('subscriptions/archived.html', subscriptions=archived)

@subscriptions_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def archive_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    subscription.is_archived = True
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been archived.')
    return redirect(url_for('subscriptions.subscriptions'))

@subscriptions_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def unarchive_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    subscription.is_archived = False
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been restored.')
    return redirect(url_for('subscriptions.archived_subscriptions'))

@subscriptions_bp.route('/calendar')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def calendar():
    return render_template('calendar.html')

@subscriptions_bp.route('/api/calendar-events')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def calendar_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        start_date = datetime.fromisoformat(start_str).date()
        end_date = datetime.fromisoformat(end_str).date()
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date format"}), 400

    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()
    events = []

    for subscription in all_active_subscriptions:
        if subscription.auto_renew:
            # For auto-renewing subscriptions, show all future renewals in the date range
            next_renewal = subscription.next_renewal_date
            while next_renewal and next_renewal < end_date:
                if next_renewal >= start_date:
                    events.append({
                        'id': subscription.id,
                        'title': subscription.name,
                        'start': next_renewal.isoformat(),
                        'backgroundColor': '#007bff',
                        'borderColor': '#007bff',
                        'url': url_for('subscriptions.subscription_detail', id=subscription.id),
                        'extendedProps': {
                            'subscription_name': subscription.name,
                            'cost_eur': f"€{subscription.cost_eur:.2f}"
                        }
                    })
                next_renewal = subscription.get_renewal_date_after(next_renewal)
        else:
            # For non-renewing subscriptions, show only the initial renewal_date (expiration date)
            renewal_date = subscription.renewal_date
            if start_date <= renewal_date < end_date:
                events.append({
                    'id': subscription.id,
                    'title': f"{subscription.name} (Expira)",
                    'start': renewal_date.isoformat(),
                    'backgroundColor': '#ffc107',
                    'borderColor': '#ffc107',
                    'url': url_for('subscriptions.subscription_detail', id=subscription.id),
                    'extendedProps': {
                        'subscription_name': subscription.name,
                        'cost_eur': f"€{subscription.cost_eur:.2f}"
                    }
                })

    return jsonify(events)

@subscriptions_bp.route('/<int:id>/users/add', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def add_user_access(id):
    subscription = Subscription.query.get_or_404(id)
    user_id = request.form.get('user_id')
    
    if user_id:
        user = db.session.get(User,user_id)
        if user and user not in subscription.users:
            subscription.users.append(user)
            db.session.commit()
            flash(f'User {user.name} added to {subscription.name}.', 'success')
            
    return redirect(url_for('subscriptions.subscription_detail', id=id))

@subscriptions_bp.route('/<int:id>/users/remove/<int:user_id>', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def remove_user_access(id, user_id):
    subscription = Subscription.query.get_or_404(id)
    user = User.query.get_or_404(user_id)
    
    if user in subscription.users:
        subscription.users.remove(user)
        db.session.commit()
        flash(f'User {user.name} removed from {subscription.name}.', 'warning')
        
    return redirect(url_for('subscriptions.subscription_detail', id=id))