from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from ..models import db, Subscription, Supplier, Contact, PaymentMethod, Tag, CostHistory, CURRENCY_RATES
from .main import login_required

subscriptions_bp = Blueprint('subscriptions', __name__)

@subscriptions_bp.route('/')
@login_required
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
                next_renewal = subscription.next_renewal_date
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
def subscription_detail(id):
    subscription = Subscription.query.get_or_404(id)
    cost_history_labels = [entry.changed_date.strftime('%Y-%m-%d') for entry in subscription.cost_history]
    cost_history_data = [
        round(
            entry.cost * CURRENCY_RATES.get(entry.currency, 1.0), 2
        ) for entry in subscription.cost_history
    ]

    return render_template(
        'subscriptions/detail.html',
        subscription=subscription,
        cost_history_labels=cost_history_labels,
        cost_history_data=cost_history_data
    )

@subscriptions_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_subscription():
    if request.method == 'POST':
        subscription = Subscription(
            name=request.form['name'],
            subscription_type=request.form['subscription_type'],
            description=request.form.get('description'),
            renewal_date=datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date(),
            renewal_period_type=request.form['renewal_period_type'],
            renewal_period_value=int(request.form.get('renewal_period_value', 1)),
            auto_renew='auto_renew' in request.form,
            cost=float(request.form['cost']),
            currency=request.form['currency'],
            supplier_id=request.form['supplier_id']
        )

        if subscription.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                subscription.monthly_renewal_day = selector
            elif selector == 'specific':
                subscription.monthly_renewal_day = request.form.get('monthly_renewal_day')

        initial_cost = CostHistory(
            subscription=subscription, cost=subscription.cost, currency=subscription.currency, changed_date=date.today()
        )
        db.session.add(initial_cost)

        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact: subscription.contacts.append(contact)

        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm: subscription.payment_methods.append(pm)

        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag: subscription.tags.append(tag)

        db.session.add(subscription)
        db.session.commit()
        flash('Subscription created successfully!')
        return redirect(url_for('subscriptions.subscriptions'))

    return render_template('subscriptions/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@subscriptions_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_subscription(id):
    subscription = Subscription.query.get_or_404(id)

    if request.method == 'POST':
        new_cost = float(request.form['cost'])
        new_currency = request.form['currency']

        if subscription.cost != new_cost or subscription.currency != new_currency:
            cost_entry = CostHistory(
                subscription_id=subscription.id, cost=new_cost, currency=new_currency, changed_date=date.today()
            )
            db.session.add(cost_entry)

        subscription.name = request.form['name']
        subscription.subscription_type = request.form['subscription_type']
        subscription.description = request.form.get('description')
        subscription.renewal_date = datetime.strptime(request.form['renewal_date'], '%Y-%m-%d').date()
        subscription.renewal_period_type = request.form['renewal_period_type']
        subscription.renewal_period_value = int(request.form.get('renewal_period_value', 1))
        subscription.auto_renew = 'auto_renew' in request.form
        subscription.cost = new_cost
        subscription.currency = new_currency
        subscription.supplier_id = request.form['supplier_id']
        subscription.monthly_renewal_day = None
        if subscription.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                subscription.monthly_renewal_day = selector
            elif selector == 'specific':
                subscription.monthly_renewal_day = request.form.get('monthly_renewal_day')

        subscription.contacts.clear()
        for contact_id in request.form.getlist('contact_ids'):
            contact = Contact.query.get(contact_id)
            if contact: subscription.contacts.append(contact)

        subscription.payment_methods.clear()
        for pm_id in request.form.getlist('payment_method_ids'):
            pm = PaymentMethod.query.get(pm_id)
            if pm: subscription.payment_methods.append(pm)

        subscription.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag: subscription.tags.append(tag)

        db.session.commit()
        flash('Subscription updated successfully!')
        return redirect(url_for('subscriptions.subscription_detail', id=subscription.id))

    return render_template('subscriptions/form.html',
                            subscription=subscription,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@subscriptions_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    db.session.delete(subscription)
    db.session.commit()
    flash('Subscription deleted successfully!')
    return redirect(url_for('subscriptions.subscriptions'))

@subscriptions_bp.route('/archived')
@login_required
def archived_subscriptions():
    archived = Subscription.query.filter_by(is_archived=True).order_by(Subscription.name).all()
    return render_template('subscriptions/archived.html', subscriptions=archived)

@subscriptions_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    subscription.is_archived = True
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been archived.')
    return redirect(url_for('subscriptions.subscriptions'))

@subscriptions_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_subscription(id):
    subscription = Subscription.query.get_or_404(id)
    subscription.is_archived = False
    db.session.commit()
    flash(f'Subscription "{subscription.name}" has been restored.')
    return redirect(url_for('subscriptions.archived_subscriptions'))

@subscriptions_bp.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')

@subscriptions_bp.route('/api/calendar-events')
@login_required
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
        next_renewal = subscription.next_renewal_date
        while next_renewal < end_date:
            if next_renewal >= start_date:
                events.append({
                    'id': subscription.id,
                    'title': subscription.name,
                    'start': next_renewal.isoformat(),
                    'backgroundColor': '#007bff' if subscription.auto_renew else '#ffc107',
                    'borderColor': '#007bff' if subscription.auto_renew else '#ffc107',
                    'url': url_for('subscriptions.subscription_detail', id=subscription.id),
                    'extendedProps': {
                        'subscription_name': subscription.name,
                        'cost_eur': f"€{subscription.cost_eur:.2f}"
                    }
                })
            next_renewal = subscription.get_renewal_date_after(next_renewal)

    return jsonify(events)