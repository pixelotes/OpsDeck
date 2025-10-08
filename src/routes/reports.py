from flask import (
    Blueprint, render_template, request
)
from sqlalchemy import func
from datetime import date
from dateutil.relativedelta import relativedelta
from ..models import db, Service, Asset, Supplier
from .main import login_required

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/subscription-reports')
@login_required
def subscription_reports():
    today = date.today()
    selected_year = request.args.get('year', default=today.year, type=int)

    all_active_services = Service.query.filter_by(is_archived=False).all()

    # Chart 1: Spending by Supplier
    supplier_spending = {}
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)

    for service in all_active_services:
        renewal = service.renewal_date
        while renewal < year_start:
            renewal = service.get_renewal_date_after(renewal)

        while renewal <= year_end:
            supplier_name = service.supplier.name
            if supplier_name not in supplier_spending:
                supplier_spending[supplier_name] = 0
            supplier_spending[supplier_name] += service.cost_eur
            renewal = service.get_renewal_date_after(renewal)

    sorted_supplier_spending = sorted(supplier_spending.items(), key=lambda item: item[1], reverse=True)
    supplier_labels = [item[0] for item in sorted_supplier_spending]
    supplier_data = [round(item[1], 2) for item in sorted_supplier_spending]

    available_years_query = db.session.query(func.strftime('%Y', Service.renewal_date)).distinct().order_by(func.strftime('%Y', Service.renewal_date).desc()).all()
    available_years = [int(y[0]) for y in available_years_query]

    # Chart 2: Services by type
    services_by_type = db.session.query(Service.service_type, func.count(Service.id)).filter(Service.is_archived == False).group_by(Service.service_type).order_by(func.count(Service.id).desc()).all()
    type_labels = [item[0].title() for item in services_by_type]
    type_data = [item[1] for item in services_by_type]

    # Chart 3 & 4: Historical Spending
    monthly_start_date = (today.replace(day=1) - relativedelta(months=12))
    monthly_labels, monthly_costs = [], {}
    for i in range(13):
        month_date = monthly_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        monthly_labels.append(month_date.strftime('%b %Y'))
        monthly_costs[year_month_key] = 0

    yearly_start_date = today.replace(year=today.year - 4, month=1, day=1)
    yearly_labels, yearly_costs = [], {}
    for i in range(5):
        year_date = yearly_start_date + relativedelta(years=i)
        yearly_labels.append(year_date.strftime('%Y'))
        yearly_costs[year_date.strftime('%Y')] = 0

    for service in all_active_services:
        renewal = service.renewal_date
        while renewal < yearly_start_date:
            renewal = service.get_renewal_date_after(renewal)

        while renewal <= today:
            year_key = renewal.strftime('%Y')
            if year_key in yearly_costs:
                yearly_costs[year_key] += service.cost_eur

            month_key = renewal.strftime('%Y-%m')
            if month_key in monthly_costs:
                monthly_costs[month_key] += service.cost_eur

            renewal = service.get_renewal_date_after(renewal)

    monthly_data = [round(cost, 2) for cost in monthly_costs.values()]
    yearly_data = [round(cost, 2) for cost in yearly_costs.values()]

    # Forecast Chart
    end_of_forecast_period = today + relativedelta(months=+13)
    forecast_labels, forecast_costs = [], {}
    for i in range(13):
        month_date = today + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_costs[year_month_key] = 0

    for service in all_active_services:
        renewal = service.next_renewal_date
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += service.cost_eur
            renewal = service.get_renewal_date_after(renewal)

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

@reports_bp.route('/asset-reports')
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