from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from ..models import db, Service, Supplier, Contact, PaymentMethod, Tag, CostHistory, CURRENCY_RATES
from .main import login_required

services_bp = Blueprint('services', __name__)

@services_bp.route('/')
@login_required
def services():
    service_type_filter = request.args.get('service_type')
    tag_filter = request.args.get('tag_id', type=int)
    month_filter = request.args.get('month')

    query = Service.query.join(Supplier).filter(Service.is_archived == False)

    if service_type_filter and service_type_filter != 'all':
        query = query.filter(Service.service_type == service_type_filter)

    if tag_filter:
        tag = Tag.query.get_or_404(tag_filter)
        query = query.filter(Service.tags.contains(tag))

    all_services = query.order_by(Service.name).all()

    if month_filter:
        try:
            filter_month_start = datetime.strptime(month_filter, '%Y-%m').date()
            filter_month_end = filter_month_start + relativedelta(months=+1, days=-1)

            filtered_services = []
            for service in all_services:
                next_renewal = service.next_renewal_date
                while next_renewal <= filter_month_end:
                    if next_renewal >= filter_month_start:
                        filtered_services.append(service)
                        break
                    next_renewal = service.get_renewal_date_after(next_renewal)

            all_services = filtered_services
        except ValueError:
            flash("Invalid month format in filter.", "error")

    total_cost_of_listed_services = sum(service.cost_eur for service in all_services)

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

@services_bp.route('/<int:id>')
@login_required
def service_detail(id):
    service = Service.query.get_or_404(id)
    cost_history_labels = [entry.changed_date.strftime('%Y-%m-%d') for entry in service.cost_history]
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

@services_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_service():
    if request.method == 'POST':
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

        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')

        initial_cost = CostHistory(
            service=service, cost=service.cost, currency=service.currency, changed_date=date.today()
        )
        db.session.add(initial_cost)

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
        return redirect(url_for('services.services'))

    return render_template('services/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@services_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_service(id):
    service = Service.query.get_or_404(id)

    if request.method == 'POST':
        new_cost = float(request.form['cost'])
        new_currency = request.form['currency']

        if service.cost != new_cost or service.currency != new_currency:
            cost_entry = CostHistory(
                service_id=service.id, cost=new_cost, currency=new_currency, changed_date=date.today()
            )
            db.session.add(cost_entry)

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
        service.monthly_renewal_day = None
        if service.renewal_period_type == 'monthly':
            selector = request.form.get('monthly_renewal_day_selector')
            if selector in ['first', 'last']:
                service.monthly_renewal_day = selector
            elif selector == 'specific':
                service.monthly_renewal_day = request.form.get('monthly_renewal_day')

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
        return redirect(url_for('services.service_detail', id=service.id))

    return render_template('services/form.html',
                            service=service,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            contacts=Contact.query.order_by(Contact.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all())

@services_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_service(id):
    service = Service.query.get_or_404(id)
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted successfully!')
    return redirect(url_for('services.services'))

@services_bp.route('/archived')
@login_required
def archived_services():
    archived = Service.query.filter_by(is_archived=True).order_by(Service.name).all()
    return render_template('services/archived.html', services=archived)

@services_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_service(id):
    service = Service.query.get_or_404(id)
    service.is_archived = True
    db.session.commit()
    flash(f'Service "{service.name}" has been archived.')
    return redirect(url_for('services.services'))

@services_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_service(id):
    service = Service.query.get_or_404(id)
    service.is_archived = False
    db.session.commit()
    flash(f'Service "{service.name}" has been restored.')
    return redirect(url_for('services.archived_services'))

@services_bp.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')

@services_bp.route('/api/calendar-events')
@login_required
def calendar_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        start_date = datetime.fromisoformat(start_str).date()
        end_date = datetime.fromisoformat(end_str).date()
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid date format"}), 400

    all_active_services = Service.query.filter_by(is_archived=False).all()
    events = []

    for service in all_active_services:
        next_renewal = service.next_renewal_date
        while next_renewal < end_date:
            if next_renewal >= start_date:
                events.append({
                    'id': service.id,
                    'title': service.name,
                    'start': next_renewal.isoformat(),
                    'backgroundColor': '#007bff' if service.auto_renew else '#ffc107',
                    'borderColor': '#007bff' if service.auto_renew else '#ffc107',
                    'url': url_for('services.service_detail', id=service.id),
                    'extendedProps': {
                        'service_name': service.name,
                        'cost_eur': f"€{service.cost_eur:.2f}"
                    }
                })
            next_renewal = service.get_renewal_date_after(next_renewal)

    return jsonify(events)