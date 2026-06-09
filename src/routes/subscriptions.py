from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from ..models import db, Subscription, Supplier, Contact, PaymentMethod, Tag, CostHistory, Software, Budget, User
from ..models.procurement import log_subscription_cost_change
from ..services.finance_service import get_conversion_rate
from ..services.permissions_service import requires_permission, has_write_permission
from .main import login_required
from src.utils.timezone_helper import today


subscriptions_bp = Blueprint('subscriptions', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
SUBSCRIPTIONS = 'subscriptions.subscriptions'
SUBSCRIPTION_DETAIL = 'subscriptions.subscription_detail'
SUBSCRIPTIONS_FORM_HTML = 'subscriptions/form.html'

@subscriptions_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def subscriptions():
    subscription_type_filter = request.args.get('subscription_type')
    tag_filter = request.args.get('tag_id', type=int)
    month_filter = request.args.get('month')

    query = Subscription.query.join(Supplier).filter(Subscription.is_archived == False)

    if subscription_type_filter and subscription_type_filter != 'all':
        query = query.filter(Subscription.subscription_type == subscription_type_filter)

    if tag_filter:
        tag = db.get_or_404(Tag, tag_filter)
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

@subscriptions_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def subscription_detail(id):
    subscription = db.get_or_404(Subscription, id)
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
        all_users=all_users,
        get_conversion_rate=get_conversion_rate
    )

@subscriptions_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_subscription():
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()

    users = User.query.filter_by(is_archived=False).all()

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(SUBSCRIPTIONS))
        renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None

        # Inform when renewal_date is in the past. The next renewal is computed
        # mathematically (see Subscription.next_renewal_date), so old dates are fine.
        current_date = today()
        days_in_past = (current_date - renewal_date).days if renewal_date < current_date else 0

        if days_in_past > 30:
            flash(f'Warning: Renewal date is {days_in_past} days in the past. The next renewal will be calculated from this date.', 'warning')

        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(renewal_date):
                flash('Error: This subscription renewal date is outside the selected Budget\'s validity period.', 'danger')
                return render_template(SUBSCRIPTIONS_FORM_HTML,
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)

        # Get pricing model
        pricing_model = request.form.get('pricing_model', 'fixed')

        # Validate cost based on pricing model
        try:
            if pricing_model == 'fixed':
                cost = float(request.form['cost'])
                cost_per_user = None
                if cost <= 0:
                    flash('Error: Subscription cost must be greater than 0.', 'danger')
                    return render_template(SUBSCRIPTIONS_FORM_HTML,
                                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                                            contacts=Contact.query.order_by(Contact.name).all(),
                                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                            tags=Tag.query.order_by(Tag.name).all(),
                                            software_items=software_items,
                                            budgets=Budget.query.order_by(Budget.name).all(),
                                            users=users)
            else:  # per_user
                cost_per_user = float(request.form.get('cost_per_user', 0))
                cost = 0  # Will be calculated based on users
                if cost_per_user <= 0:
                    flash('Error: Cost per user must be greater than 0.', 'danger')
                    return render_template(SUBSCRIPTIONS_FORM_HTML,
                                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                                            contacts=Contact.query.order_by(Contact.name).all(),
                                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                            tags=Tag.query.order_by(Tag.name).all(),
                                            software_items=software_items,
                                            budgets=Budget.query.order_by(Budget.name).all(),
                                            users=users)
        except (ValueError, KeyError):
            flash('Error: Invalid cost value.', 'danger')
            return render_template(SUBSCRIPTIONS_FORM_HTML,
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
            pricing_model=pricing_model,
            cost=cost,
            cost_per_user=cost_per_user,
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

        db.session.add(subscription)
        db.session.flush()  # Get subscription.id before logging

        # Log initial cost
        log_subscription_cost_change(subscription, reason='created')

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
        flash('Subscription created successfully!', 'success')
        return redirect(url_for(SUBSCRIPTIONS))

    return render_template(SUBSCRIPTIONS_FORM_HTML,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            software_items=software_items,
                            budgets=Budget.query.order_by(Budget.name).all(),
                            users=users)

@subscriptions_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_subscription(id):
    subscription = db.get_or_404(Subscription, id)
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()

    users = User.query.filter_by(is_archived=False).all()

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(SUBSCRIPTION_DETAIL, id=id))
        renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None

        # Inform when renewal_date is in the past. The next renewal is computed
        # mathematically (see Subscription.next_renewal_date), so old dates are fine.
        current_date = today()
        days_in_past = (current_date - renewal_date).days if renewal_date < current_date else 0

        if days_in_past > 30:
            flash(f'Warning: Renewal date is {days_in_past} days in the past. The next renewal will be calculated from this date.', 'warning')

        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(renewal_date):
                flash('Error: This subscription renewal date is outside the selected Budget\'s validity period.', 'danger')
                return render_template(SUBSCRIPTIONS_FORM_HTML,
                                        subscription=subscription,
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        contacts=Contact.query.order_by(Contact.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        software_items=software_items,
                                        budgets=Budget.query.order_by(Budget.name).all(),
                                        users=users)

        # Get pricing model
        new_pricing_model = request.form.get('pricing_model', 'fixed')

        # Validate cost based on pricing model
        try:
            if new_pricing_model == 'fixed':
                new_cost = float(request.form['cost'])
                new_cost_per_user = None
                if new_cost <= 0:
                    flash('Error: Subscription cost must be greater than 0.', 'danger')
                    return render_template(SUBSCRIPTIONS_FORM_HTML,
                                            subscription=subscription,
                                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                                            contacts=Contact.query.order_by(Contact.name).all(),
                                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                            tags=Tag.query.order_by(Tag.name).all(),
                                            software_items=software_items,
                                            budgets=Budget.query.order_by(Budget.name).all(),
                                            users=users)
            else:  # per_user
                new_cost_per_user = float(request.form.get('cost_per_user', 0))
                new_cost = 0  # Will be calculated based on users
                if new_cost_per_user <= 0:
                    flash('Error: Cost per user must be greater than 0.', 'danger')
                    return render_template(SUBSCRIPTIONS_FORM_HTML,
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
            return render_template(SUBSCRIPTIONS_FORM_HTML,
                                    subscription=subscription,
                                    suppliers=Supplier.query.order_by(Supplier.name).all(),
                                    contacts=Contact.query.order_by(Contact.name).all(),
                                    payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                    tags=Tag.query.order_by(Tag.name).all(),
                                    software_items=software_items,
                                    budgets=Budget.query.order_by(Budget.name).all(),
                                    users=users)

        new_currency = request.form['currency']

        # Detect if cost-related fields changed
        cost_changed = (
            subscription.pricing_model != new_pricing_model or
            subscription.cost != new_cost or
            subscription.cost_per_user != new_cost_per_user or
            subscription.currency != new_currency
        )

        subscription.name = request.form['name']
        subscription.subscription_type = request.form['subscription_type']
        subscription.description = request.form.get('description')
        subscription.renewal_date = renewal_date
        subscription.renewal_period_type = request.form['renewal_period_type']
        subscription.renewal_period_value = int(request.form.get('renewal_period_value', 1))
        subscription.auto_renew = 'auto_renew' in request.form
        subscription.pricing_model = new_pricing_model
        subscription.cost = new_cost
        subscription.cost_per_user = new_cost_per_user
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

        # Log cost change if any cost-related field changed
        if cost_changed:
            log_subscription_cost_change(subscription, reason='manual')

        db.session.commit()
        flash('Subscription updated successfully!', 'success')
        return redirect(url_for(SUBSCRIPTION_DETAIL, id=subscription.id))

    return render_template(SUBSCRIPTIONS_FORM_HTML,
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
@requires_permission(MODULE, access_level='WRITE')
def delete_subscription(id):
    subscription = db.get_or_404(Subscription, id)
    db.session.delete(subscription)
    db.session.commit()
    flash('Subscription deleted successfully!', 'success')
    return redirect(url_for(SUBSCRIPTIONS))

@subscriptions_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_subscriptions():
    archived = Subscription.query.filter_by(is_archived=True).order_by(Subscription.name).all()
    return render_template('subscriptions/archived.html', subscriptions=archived)

@subscriptions_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_subscription(id):
    subscription = db.get_or_404(Subscription, id)
    subscription.is_archived = True
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been archived.', 'warning')
    return redirect(url_for(SUBSCRIPTIONS))

@subscriptions_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_subscription(id):
    subscription = db.get_or_404(Subscription, id)
    subscription.is_archived = False
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been restored.', 'success')
    return redirect(url_for('subscriptions.archived_subscriptions'))

@subscriptions_bp.route('/calendar', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def calendar():
    return render_template('calendar.html')

@subscriptions_bp.route('/api/calendar-events', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def calendar_events():
    from ..models.contracts import Contract
    from ..models.certificates import CertificateVersion
    from ..models.credentials import CredentialSecret

    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        start_date = datetime.fromisoformat(start_str).date()
        end_date = datetime.fromisoformat(end_str).date()
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date format"}), 400

    events = []

    # ============================================
    # 1. SUBSCRIPTIONS
    # ============================================
    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()

    for subscription in all_active_subscriptions:
        if subscription.auto_renew:
            # For auto-renewing subscriptions, show all future renewals in the date range
            next_renewal = subscription.next_renewal_date
            while next_renewal and next_renewal < end_date:
                if next_renewal >= start_date:
                    events.append({
                        'id': f'sub-{subscription.id}',
                        'title': f'📋 {subscription.name}',
                        'start': next_renewal.isoformat(),
                        'backgroundColor': '#007bff',
                        'borderColor': '#007bff',
                        'url': url_for(SUBSCRIPTION_DETAIL, id=subscription.id),
                        'extendedProps': {
                            'type': 'subscription',
                            'name': subscription.name,
                            'cost_eur': f"€{subscription.cost_eur:.2f}",
                            'auto_renew': True
                        }
                    })
                next_renewal = subscription.get_renewal_date_after(next_renewal)
        else:
            # For non-renewing subscriptions, show only the initial renewal_date (expiration date)
            renewal_date = subscription.renewal_date
            if start_date <= renewal_date < end_date:
                events.append({
                    'id': f'sub-{subscription.id}',
                    'title': f'📋 {subscription.name} (Expira)',
                    'start': renewal_date.isoformat(),
                    'backgroundColor': '#ffc107',
                    'borderColor': '#ffc107',
                    'url': url_for(SUBSCRIPTION_DETAIL, id=subscription.id),
                    'extendedProps': {
                        'type': 'subscription',
                        'name': subscription.name,
                        'cost_eur': f"€{subscription.cost_eur:.2f}",
                        'auto_renew': False
                    }
                })

    # ============================================
    # 2. CONTRACTS
    # ============================================
    all_active_contracts = Contract.query.filter(Contract.status == 'Active').all()

    for contract in all_active_contracts:
        # Only show contracts that end within the date range
        if start_date <= contract.end_date < end_date:
            if contract.is_auto_renew:
                title = f'📄 {contract.name} (Renueva)'
                color = '#28a745'  # Green
            else:
                title = f'📄 {contract.name} (Expira)'
                color = '#fd7e14'  # Orange

            events.append({
                'id': f'contract-{contract.id}',
                'title': title,
                'start': contract.end_date.isoformat(),
                'backgroundColor': color,
                'borderColor': color,
                'url': url_for('contracts.contract_detail', id=contract.id),
                'extendedProps': {
                    'type': 'contract',
                    'name': contract.name,
                    'auto_renew': contract.is_auto_renew
                }
            })

    # ============================================
    # 3. CERTIFICATES (Active Versions)
    # ============================================
    # Get all active certificate versions expiring in the date range
    expiring_cert_versions = CertificateVersion.query.filter(
        CertificateVersion.is_active == True,
        CertificateVersion.expires_at >= start_date,
        CertificateVersion.expires_at < end_date
    ).all()

    for cert_version in expiring_cert_versions:
        events.append({
            'id': f'cert-{cert_version.certificate.id}',
            'title': f'🔒 {cert_version.certificate.name} (Expira)',
            'start': cert_version.expires_at.isoformat(),
            'backgroundColor': '#dc3545',  # Red
            'borderColor': '#dc3545',
            'url': url_for('certificates.certificate_detail', id=cert_version.certificate.id),
            'extendedProps': {
                'type': 'certificate',
                'name': cert_version.certificate.name,
                'issuer': cert_version.issuer
            }
        })

    # ============================================
    # 4. CREDENTIALS (Active Secrets)
    # ============================================
    # Get all active credential secrets expiring in the date range
    expiring_secrets = CredentialSecret.query.filter(
        CredentialSecret.is_active == True,
        CredentialSecret.expires_at.isnot(None),
        CredentialSecret.expires_at >= start_date,
        CredentialSecret.expires_at < end_date
    ).all()

    for secret in expiring_secrets:
        events.append({
            'id': f'cred-{secret.credential.id}',
            'title': f'🔑 {secret.credential.name} (Expira)',
            'start': secret.expires_at.date().isoformat(),
            'backgroundColor': '#6f42c1',  # Purple
            'borderColor': '#6f42c1',
            'url': url_for('credentials.detail_credential', id=secret.credential.id),
            'extendedProps': {
                'type': 'credential',
                'name': secret.credential.name,
                'credential_type': secret.credential.type
            }
        })

    return jsonify(events)

@subscriptions_bp.route('/<int:id>/users/add', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_user_access(id):
    subscription = db.get_or_404(Subscription, id)
    user_ids = request.form.getlist('user_ids')

    added = []
    for user_id in user_ids:
        user = db.session.get(User, int(user_id))
        if user and user not in subscription.users:
            subscription.users.append(user)
            added.append(user.name)

    if added:
        if subscription.pricing_model == 'per_user':
            log_subscription_cost_change(subscription, reason='user_added')
        db.session.commit()
        flash(f'Added {", ".join(added)} to {subscription.name}.', 'success')

    return redirect(url_for(SUBSCRIPTION_DETAIL, id=id) + '#users')

@subscriptions_bp.route('/<int:id>/users/add-all', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_all_users(id):
    subscription = db.get_or_404(Subscription, id)
    all_users = User.query.filter_by(is_archived=False).all()

    added = []
    for user in all_users:
        if user not in subscription.users:
            subscription.users.append(user)
            added.append(user.name)

    if added:
        if subscription.pricing_model == 'per_user':
            log_subscription_cost_change(subscription, reason='user_added')
        db.session.commit()
        flash(f'Added {len(added)} users to {subscription.name}.', 'success')
    else:
        flash('All users already have access.', 'info')

    return redirect(url_for(SUBSCRIPTION_DETAIL, id=id) + '#users')

@subscriptions_bp.route('/<int:id>/users/remove/<int:user_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def remove_user_access(id, user_id):
    subscription = db.get_or_404(Subscription, id)
    user = db.get_or_404(User, user_id)

    if user in subscription.users:
        subscription.users.remove(user)
        if subscription.pricing_model == 'per_user':
            log_subscription_cost_change(subscription, reason='user_removed')
        db.session.commit()
        flash(f'User {user.name} removed from {subscription.name}.', 'warning')

    return redirect(url_for(SUBSCRIPTION_DETAIL, id=id) + '#users')