from flask import (
    Blueprint, render_template, request
)
from sqlalchemy import func
from datetime import date
from dateutil.relativedelta import relativedelta
from ..models import db, Service, Asset, Supplier, User, Group, Peripheral, Location, CURRENCY_RATES
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

    # --- CORRECTED WARRANTY LOGIC ---
    today = date.today()
    all_assets = Asset.query.filter(Asset.purchase_date.isnot(None), Asset.warranty_length.isnot(None)).all()
    warranty_active = 0
    for asset in all_assets:
        if asset.warranty_end_date and asset.warranty_end_date > today:
            warranty_active += 1
    
    warranty_expired = len(all_assets) - warranty_active
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

@reports_bp.route('/spend-analysis', methods=['GET'])
@login_required
def spend_analysis():
    # --- Get filter options from the database ---
    suppliers = Supplier.query.order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    
    # Get a distinct list of brands from both assets and peripherals
    asset_brands = db.session.query(Asset.brand).filter(Asset.brand.isnot(None)).distinct()
    peripheral_brands = db.session.query(Peripheral.brand).filter(Peripheral.brand.isnot(None)).distinct()
    all_brands = sorted([b[0] for b in asset_brands.union(peripheral_brands)])

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    item_type = request.args.get('item_type', 'both')
    supplier_id = request.args.get('supplier_id', type=int)
    brand = request.args.get('brand')
    user_id = request.args.get('user_id', type=int)
    group_id = request.args.get('group_id', type=int)

    # --- Build the queries ---
    assets_query = Asset.query
    peripherals_query = Peripheral.query

    if start_date:
        assets_query = assets_query.filter(Asset.purchase_date >= start_date)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date >= start_date)
    if end_date:
        assets_query = assets_query.filter(Asset.purchase_date <= end_date)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date <= end_date)
    if supplier_id:
        assets_query = assets_query.filter(Asset.supplier_id == supplier_id)
        peripherals_query = peripherals_query.filter(Peripheral.supplier_id == supplier_id)
    if brand:
        assets_query = assets_query.filter(Asset.brand == brand)
        peripherals_query = peripherals_query.filter(Peripheral.brand == brand)
    
    # Handle user/group filtering
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = Group.query.get(group_id)
        if group:
            user_ids_to_filter.extend([user.id for user in group.users])
    
    if user_ids_to_filter:
        assets_query = assets_query.filter(Asset.user_id.in_(user_ids_to_filter))
        peripherals_query = peripherals_query.filter(Peripheral.user_id.in_(user_ids_to_filter))
    
    # --- Execute queries and combine results ---
    results = []
    if item_type == 'assets' or item_type == 'both':
        results.extend(assets_query.all())
    if item_type == 'peripherals' or item_type == 'both':
        results.extend(peripherals_query.all())

    total_cost = sum(item.cost for item in results if item.cost)

    return render_template(
        'reports/spend_analysis.html',
        results=results,
        total_cost=total_cost,
        suppliers=suppliers,
        users=users,
        groups=groups,
        all_brands=all_brands,
        # Pass filters back to template to pre-fill form
        start_date=start_date, end_date=end_date, item_type=item_type,
        supplier_id=supplier_id, brand=brand, user_id=user_id, group_id=group_id
    )

@reports_bp.route('/depreciation', methods=['GET'])
@login_required
def depreciation_report():
    # --- Get filter options from the database ---
    suppliers = Supplier.query.order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    locations = Location.query.order_by(Location.name).all()
    
    asset_brands = db.session.query(Asset.brand).filter(Asset.brand.isnot(None)).distinct()
    peripheral_brands = db.session.query(Peripheral.brand).filter(Peripheral.brand.isnot(None)).distinct()
    all_brands = sorted([b[0] for b in asset_brands.union(peripheral_brands)])

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    depreciation_period = request.args.get('depreciation_period', 5, type=int)
    depreciation_algorithm = request.args.get('depreciation_algorithm', 'linear')
    item_type = request.args.get('item_type', 'both')
    supplier_id = request.args.get('supplier_id', type=int)
    brand = request.args.get('brand')
    user_id = request.args.get('user_id', type=int)
    group_id = request.args.get('group_id', type=int)
    location_id = request.args.get('location_id', type=int)
    currency = request.args.get('currency')

    # --- Build the queries ---
    assets_query = Asset.query
    peripherals_query = Peripheral.query

    if start_date:
        assets_query = assets_query.filter(Asset.purchase_date >= start_date)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date >= start_date)
    if end_date:
        assets_query = assets_query.filter(Asset.purchase_date <= end_date)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date <= end_date)
    if supplier_id:
        assets_query = assets_query.filter(Asset.supplier_id == supplier_id)
        peripherals_query = peripherals_query.filter(Peripheral.supplier_id == supplier_id)
    if brand:
        assets_query = assets_query.filter(Asset.brand == brand)
        peripherals_query = peripherals_query.filter(Peripheral.brand == brand)
    if location_id:
        assets_query = assets_query.filter(Asset.location_id == location_id)
    
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = Group.query.get(group_id)
        if group:
            user_ids_to_filter.extend([user.id for user in group.users])
    
    if user_ids_to_filter:
        assets_query = assets_query.filter(Asset.user_id.in_(user_ids_to_filter))
        peripherals_query = peripherals_query.filter(Peripheral.user_id.in_(user_ids_to_filter))
    
    results = []
    if item_type == 'assets' or item_type == 'both':
        results.extend(assets_query.all())
    if item_type == 'peripherals' or item_type == 'both':
        results.extend(peripherals_query.all())

    # --- Depreciation and Chart Calculations ---
    depreciation_results = []
    today = date.today()
    total_original_value_eur = 0
    total_depreciated_value_eur = 0
    depreciation_by_location = {}

    for item in results:
        cost = item.cost
        depreciated_value = None
        
        if item.purchase_date and cost and cost > 0:
            age_in_days = (today - item.purchase_date).days
            age_in_years = age_in_days / 365.25

            if depreciation_algorithm == 'linear':
                depreciation_per_year = cost / depreciation_period
                depreciation_amount = depreciation_per_year * age_in_years
                depreciated_value = max(0, cost - depreciation_amount)
            elif depreciation_algorithm == 'declining_balance':
                factor = 2
                book_value = cost
                for _ in range(int(age_in_years)):
                    book_value -= (book_value * (factor / depreciation_period))
                depreciated_value = max(0, book_value)

            # Convert original and depreciated values to EUR for chart calculations
            rate_to_eur = CURRENCY_RATES.get(item.currency, 1.0)
            original_value_eur = cost * rate_to_eur
            depreciated_value_eur = (depreciated_value * rate_to_eur) if depreciated_value is not None else 0
            
            total_original_value_eur += original_value_eur
            total_depreciated_value_eur += depreciated_value_eur
            
            if hasattr(item, 'location') and item.location:
                location_name = item.location.name
                if location_name not in depreciation_by_location:
                    depreciation_by_location[location_name] = {'original': 0, 'depreciated': 0}
                depreciation_by_location[location_name]['original'] += original_value_eur
                depreciation_by_location[location_name]['depreciated'] += depreciated_value_eur

        # --- CORRECTED CURRENCY CONVERSION LOGIC FOR TABLE DISPLAY ---
        display_currency = item.currency
        if currency and currency != item.currency:
            display_currency = currency
            if cost:
                # Step 1: Convert original cost to EUR
                cost_in_eur = cost * CURRENCY_RATES.get(item.currency, 1.0)
                # Step 2: Convert EUR to target currency
                cost = cost_in_eur / CURRENCY_RATES.get(currency, 1.0)

                if depreciated_value is not None:
                    # Step 1: Convert original depreciated value to EUR
                    depreciated_in_eur = depreciated_value * CURRENCY_RATES.get(item.currency, 1.0)
                    # Step 2: Convert EUR to target currency
                    depreciated_value = depreciated_in_eur / CURRENCY_RATES.get(currency, 1.0)
        
        depreciation_results.append({
            'item': item,
            'cost': cost,
            'depreciated_value': depreciated_value,
            'display_currency': display_currency
        })

    # Prepare data for charts
    value_chart_labels = ['Depreciated Value', 'Value Lost to Depreciation']
    value_chart_data = [round(total_depreciated_value_eur, 2), round(max(0, total_original_value_eur - total_depreciated_value_eur), 2)]

    location_chart_labels = list(depreciation_by_location.keys())
    location_chart_data_original = [round(data['original'], 2) for data in depreciation_by_location.values()]
    location_chart_data_depreciated = [round(data['depreciated'], 2) for data in depreciation_by_location.values()]

    return render_template(
        'reports/depreciation.html',
        results=depreciation_results,
        suppliers=suppliers,
        users=users,
        groups=groups,
        locations=locations,
        all_brands=all_brands,
        start_date=start_date, end_date=end_date, item_type=item_type,
        supplier_id=supplier_id, brand=brand, user_id=user_id, group_id=group_id,
        location_id=location_id,
        depreciation_period=depreciation_period,
        depreciation_algorithm=depreciation_algorithm,
        currency=currency,
        value_chart_labels=value_chart_labels,
        value_chart_data=value_chart_data,
        location_chart_labels=location_chart_labels,
        location_chart_data_original=location_chart_data_original,
        location_chart_data_depreciated=location_chart_data_depreciated
    )