# src/routes/reports.py

from flask import (
    Blueprint, render_template, request
)
from sqlalchemy import func
from datetime import date, timedelta # Import timedelta if not already there
from dateutil.relativedelta import relativedelta
# *** Ensure License is imported ***
from ..models import db, Subscription, Asset, Supplier, User, Group, Peripheral, Location, CURRENCY_RATES, License, Purchase # Import Purchase if filtering by it
from .main import login_required

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/subscription-reports')
@login_required
def subscription_reports():
    today = date.today()
    selected_year = request.args.get('year', default=today.year, type=int)

    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()

    # Chart 1: Spending by Supplier
    supplier_spending = {}
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)

    for subscription in all_active_subscriptions:
        renewal = subscription.renewal_date
        # Ensure initial renewal is correctly handled if before year_start
        while renewal < year_start:
            renewal = subscription.get_renewal_date_after(renewal)

        while renewal <= year_end:
            supplier_name = subscription.supplier.name
            if supplier_name not in supplier_spending:
                supplier_spending[supplier_name] = 0
            supplier_spending[supplier_name] += subscription.cost_eur # Assuming cost_eur property exists
            renewal = subscription.get_renewal_date_after(renewal)

    sorted_supplier_spending = sorted(supplier_spending.items(), key=lambda item: item[1], reverse=True)
    supplier_labels = [item[0] for item in sorted_supplier_spending]
    supplier_data = [round(item[1], 2) for item in sorted_supplier_spending]

    available_years_query = db.session.query(func.strftime('%Y', Subscription.renewal_date)).distinct().order_by(func.strftime('%Y', Subscription.renewal_date).desc()).all()
    available_years = [int(y[0]) for y in available_years_query if y[0]] # Filter out None years

    # Chart 2: Subscriptions by type
    subscriptions_by_type = db.session.query(Subscription.subscription_type, func.count(Subscription.id)).filter(Subscription.is_archived == False).group_by(Subscription.subscription_type).order_by(func.count(Subscription.id).desc()).all()
    type_labels = [item[0].title() for item in subscriptions_by_type]
    type_data = [item[1] for item in subscriptions_by_type]

    # Chart 3 & 4: Historical Spending
    monthly_start_date = (today.replace(day=1) - relativedelta(months=12))
    monthly_labels, monthly_costs = [], {}
    for i in range(13): # 13 months to cover the full range
        month_date = monthly_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        monthly_labels.append(month_date.strftime('%b %Y'))
        monthly_costs[year_month_key] = 0

    yearly_start_date = today.replace(year=today.year - 4, month=1, day=1)
    yearly_labels, yearly_costs = [], {}
    for i in range(5): # Last 5 years including current
        year_date = yearly_start_date + relativedelta(years=i)
        yearly_labels.append(year_date.strftime('%Y'))
        yearly_costs[year_date.strftime('%Y')] = 0

    for subscription in all_active_subscriptions:
        renewal = subscription.renewal_date
        # Ensure initial renewal is correctly handled if before start dates
        while renewal < yearly_start_date:
             renewal = subscription.get_renewal_date_after(renewal)

        while renewal <= today:
            year_key = renewal.strftime('%Y')
            if year_key in yearly_costs:
                yearly_costs[year_key] += subscription.cost_eur

            month_key = renewal.strftime('%Y-%m')
            if month_key in monthly_costs:
                monthly_costs[month_key] += subscription.cost_eur

            renewal = subscription.get_renewal_date_after(renewal)

    monthly_data = [round(cost, 2) for cost in monthly_costs.values()]
    yearly_data = [round(cost, 2) for cost in yearly_costs.values()]

    # Forecast Chart (Logic reused from dashboard)
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
        renewal = subscription.renewal_date # Start from original renewal
        while renewal < forecast_start_date: # Find first renewal within or after forecast start
            renewal = subscription.get_renewal_date_after(renewal)

        while renewal < end_of_forecast_period: # Check renewals within the forecast period
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += subscription.cost_eur
            renewal = subscription.get_renewal_date_after(renewal)

    forecast_data = [round(cost, 2) for cost in forecast_costs.values()]


    return render_template(
        'reports/subscription_reports.html',
        supplier_labels=supplier_labels, supplier_data=supplier_data,
        type_labels=type_labels, type_data=type_data,
        monthly_labels=monthly_labels, monthly_data=monthly_data,
        yearly_labels=yearly_labels, yearly_data=yearly_data,
        forecast_labels=forecast_labels, forecast_keys=forecast_keys, forecast_data=forecast_data, # Pass keys for forecast chart interactivity
        available_years=available_years, selected_year=selected_year
    )

@reports_bp.route('/asset-reports')
@login_required
def asset_reports():
    assets_by_brand = db.session.query(Asset.brand, func.count(Asset.id)).filter(Asset.is_archived == False).group_by(Asset.brand).all()
    brand_labels = [item[0] or 'N/A' for item in assets_by_brand]
    brand_data = [item[1] for item in assets_by_brand]

    assets_by_supplier = db.session.query(Supplier.name, func.count(Asset.id)).join(Asset).filter(Asset.is_archived == False).group_by(Supplier.name).all()
    supplier_labels = [item[0] or 'N/A' for item in assets_by_supplier]
    supplier_data = [item[1] for item in assets_by_supplier]

    assets_by_status = db.session.query(Asset.status, func.count(Asset.id)).filter(Asset.is_archived == False).group_by(Asset.status).all()
    status_labels = [item[0] for item in assets_by_status]
    status_data = [item[1] for item in assets_by_status]

    # --- Warranty Logic (Considering both Assets and Peripherals potentially) ---
    today = date.today()
    # Query only non-archived items with purchase_date and warranty_length
    all_assets_with_warranty = Asset.query.filter(
        Asset.is_archived == False,
        Asset.purchase_date.isnot(None),
        Asset.warranty_length.isnot(None)
    ).all()
    # Add peripherals if you track warranty for them similarly
    # all_peripherals_with_warranty = Peripheral.query.filter(...)
    # all_items_with_warranty = all_assets_with_warranty + all_peripherals_with_warranty
    all_items_with_warranty = all_assets_with_warranty # Use only assets for now

    warranty_active = 0
    for item in all_items_with_warranty:
        if item.warranty_end_date and item.warranty_end_date > today:
            warranty_active += 1

    warranty_expired = len(all_items_with_warranty) - warranty_active
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
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()

    # Get a distinct list of brands from assets and peripherals
    asset_brands = db.session.query(Asset.brand).filter(Asset.brand.isnot(None), Asset.is_archived == False).distinct()
    peripheral_brands = db.session.query(Peripheral.brand).filter(Peripheral.brand.isnot(None), Peripheral.is_archived == False).distinct()
    all_brands = sorted([b[0] for b in asset_brands.union(peripheral_brands) if b[0]]) # Filter out None/empty brands

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    item_type = request.args.get('item_type', 'all') # Changed default to 'all'
    supplier_id = request.args.get('supplier_id', type=int)
    brand = request.args.get('brand') # Still applies to Asset/Peripheral
    user_id = request.args.get('user_id', type=int)
    group_id = request.args.get('group_id', type=int)
    location_id = request.args.get('location_id', type=int) # Only applies to Assets

    # --- Build the queries ---
    assets_query = Asset.query.filter(Asset.is_archived == False)
    peripherals_query = Peripheral.query.filter(Peripheral.is_archived == False)
    licenses_query = License.query.filter(
        License.is_archived == False,      # Also filter archived licenses
        License.subscription_id.is_(None), # Only perpetual/standalone
        License.cost.isnot(None)          # Only those with a cost
    )

    # Apply date filters
    if start_date:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        assets_query = assets_query.filter(Asset.purchase_date >= start_date_obj)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date >= start_date_obj)
        licenses_query = licenses_query.filter(License.purchase_date >= start_date_obj)
    if end_date:
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        assets_query = assets_query.filter(Asset.purchase_date <= end_date_obj)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date <= end_date_obj)
        licenses_query = licenses_query.filter(License.purchase_date <= end_date_obj)

    # Apply supplier filter (Join License via Purchase)
    if supplier_id:
        assets_query = assets_query.filter(Asset.supplier_id == supplier_id)
        peripherals_query = peripherals_query.filter(Peripheral.supplier_id == supplier_id)
        licenses_query = licenses_query.join(Purchase, Purchase.id == License.purchase_id).filter(Purchase.supplier_id == supplier_id)
        # If supplier_id added to License model:
        # licenses_query = licenses_query.filter(License.supplier_id == supplier_id)

    # Apply brand filter (only to Asset/Peripheral)
    if brand:
        assets_query = assets_query.filter(Asset.brand == brand)
        peripherals_query = peripherals_query.filter(Peripheral.brand == brand)

    # Apply location filter (only to Asset)
    if location_id:
        assets_query = assets_query.filter(Asset.location_id == location_id)

    # Handle user/group filtering
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = Group.query.get(group_id)
        if group:
            user_ids_to_filter.extend([user.id for user in group.users if not user.is_archived]) # Filter users by group membership

    if user_ids_to_filter:
        assets_query = assets_query.filter(Asset.user_id.in_(user_ids_to_filter))
        peripherals_query = peripherals_query.filter(Peripheral.user_id.in_(user_ids_to_filter))
        licenses_query = licenses_query.filter(License.user_id.in_(user_ids_to_filter))

    # --- Execute queries and combine results based on item_type ---
    results = []
    if item_type in ['assets', 'all']:
        results.extend(assets_query.all())
    if item_type in ['peripherals', 'all']:
        results.extend(peripherals_query.all())
    if item_type in ['licenses', 'all']:
        results.extend(licenses_query.all()) # Add licenses

    # --- Recalculate total_cost including licenses (summing original costs) ---
    total_cost = sum(item.cost for item in results if item.cost is not None)

    # Sort results for display (e.g., by purchase date descending, handle None dates)
    results.sort(key=lambda x: x.purchase_date if x.purchase_date else date.min, reverse=True)

    return render_template(
        'reports/spend_analysis.html',
        results=results,
        total_cost=total_cost,
        suppliers=suppliers,
        users=users,
        groups=groups,
        all_brands=all_brands,
        locations=locations,
        # Pass filters back to template
        start_date=start_date, end_date=end_date, item_type=item_type,
        supplier_id=supplier_id, brand=brand, user_id=user_id, group_id=group_id,
        location_id=location_id
    )


@reports_bp.route('/depreciation', methods=['GET'])
@login_required
def depreciation_report():
    # --- Get filter options from the database ---
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()

    asset_brands = db.session.query(Asset.brand).filter(Asset.brand.isnot(None), Asset.is_archived == False).distinct()
    peripheral_brands = db.session.query(Peripheral.brand).filter(Peripheral.brand.isnot(None), Peripheral.is_archived == False).distinct()
    all_brands = sorted([b[0] for b in asset_brands.union(peripheral_brands) if b[0]]) # Filter out None/empty brands

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    depreciation_period = request.args.get('depreciation_period', 5, type=int)
    depreciation_algorithm = request.args.get('depreciation_algorithm', 'linear')
    item_type = request.args.get('item_type', 'both') # 'both', 'assets', 'peripherals'
    supplier_id = request.args.get('supplier_id', type=int)
    brand = request.args.get('brand')
    user_id = request.args.get('user_id', type=int)
    group_id = request.args.get('group_id', type=int)
    location_id = request.args.get('location_id', type=int)
    currency = request.args.get('currency') # Target currency for display

    # --- Build the queries ---
    # Only include non-archived items with cost and purchase date for depreciation
    assets_query = Asset.query.filter(Asset.is_archived == False, Asset.cost.isnot(None), Asset.purchase_date.isnot(None))
    peripherals_query = Peripheral.query.filter(Peripheral.is_archived == False, Peripheral.cost.isnot(None), Peripheral.purchase_date.isnot(None))

    # Apply date filters
    if start_date:
        start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        assets_query = assets_query.filter(Asset.purchase_date >= start_date_obj)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date >= start_date_obj)
    if end_date:
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        assets_query = assets_query.filter(Asset.purchase_date <= end_date_obj)
        peripherals_query = peripherals_query.filter(Peripheral.purchase_date <= end_date_obj)

    # Apply supplier filter
    if supplier_id:
        assets_query = assets_query.filter(Asset.supplier_id == supplier_id)
        peripherals_query = peripherals_query.filter(Peripheral.supplier_id == supplier_id)

    # Apply brand filter
    if brand:
        assets_query = assets_query.filter(Asset.brand == brand)
        peripherals_query = peripherals_query.filter(Peripheral.brand == brand)

    # Apply location filter (only to Asset)
    if location_id:
        assets_query = assets_query.filter(Asset.location_id == location_id)

    # Handle user/group filtering
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = Group.query.get(group_id)
        if group:
            user_ids_to_filter.extend([user.id for user in group.users if not user.is_archived])

    if user_ids_to_filter:
        assets_query = assets_query.filter(Asset.user_id.in_(user_ids_to_filter))
        peripherals_query = peripherals_query.filter(Peripheral.user_id.in_(user_ids_to_filter))

    # --- Execute queries and combine results based on item_type ---
    results_to_depreciate = []
    if item_type in ['assets', 'both']:
        results_to_depreciate.extend(assets_query.all())
    if item_type in ['peripherals', 'both']:
        results_to_depreciate.extend(peripherals_query.all())

    # --- Depreciation and Chart Calculations ---
    depreciation_results_display = [] # For the table display
    today = date.today()
    total_original_value_eur = 0.0
    total_depreciated_value_eur = 0.0
    depreciation_by_location = {} # Store {'Location Name': {'original': X, 'depreciated': Y}} in EUR

    for item in results_to_depreciate:
        cost = item.cost # Already filtered for cost is not None
        depreciated_value_original_currency = None
        rate_to_eur = CURRENCY_RATES.get(item.currency, 1.0) # Rate to convert item's currency to EUR
        original_value_eur = cost * rate_to_eur

        if item.purchase_date: # Already filtered for purchase_date is not None
            age_in_days = (today - item.purchase_date).days
            age_in_years = age_in_days / 365.25 # Approximate years

            if depreciation_period <= 0: # Avoid division by zero
                depreciated_value_original_currency = cost # No depreciation
            elif depreciation_algorithm == 'linear':
                depreciation_per_year = cost / depreciation_period
                depreciation_amount = depreciation_per_year * age_in_years
                depreciated_value_original_currency = max(0.0, cost - depreciation_amount)
            elif depreciation_algorithm == 'declining_balance':
                # Simplified declining balance - adjust factor if needed
                factor = 2.0 # Common factor (e.g., double declining)
                yearly_rate = factor / depreciation_period
                book_value = cost
                # Calculate depreciation year by year up to the current age
                full_years = int(age_in_years)
                for _ in range(full_years):
                     depreciation_this_year = book_value * yearly_rate
                     book_value -= depreciation_this_year
                # Apply partial year depreciation if needed (more complex, linear approx for remainder here)
                remaining_fraction = age_in_years - full_years
                if remaining_fraction > 0:
                     depreciation_this_year = book_value * yearly_rate
                     book_value -= (depreciation_this_year * remaining_fraction)

                depreciated_value_original_currency = max(0.0, book_value)


            # Calculate depreciated value in EUR for charts
            depreciated_value_eur = depreciated_value_original_currency * rate_to_eur

            total_original_value_eur += original_value_eur
            total_depreciated_value_eur += depreciated_value_eur

            # Accumulate values by location (only for Assets)
            if isinstance(item, Asset) and item.location:
                location_name = item.location.name
                if location_name not in depreciation_by_location:
                    depreciation_by_location[location_name] = {'original': 0.0, 'depreciated': 0.0}
                depreciation_by_location[location_name]['original'] += original_value_eur
                depreciation_by_location[location_name]['depreciated'] += depreciated_value_eur

        # --- Currency Conversion Logic for Table Display ---
        display_currency_code = item.currency
        display_cost = cost
        display_depreciated_value = depreciated_value_original_currency

        if currency and currency != item.currency:
            # Convert to the target display currency via EUR
            rate_from_eur = CURRENCY_RATES.get(currency, 1.0)
            if rate_from_eur != 0: # Avoid division by zero if target currency is unknown
                 display_currency_code = currency
                 display_cost = original_value_eur / rate_from_eur
                 if depreciated_value_original_currency is not None:
                     display_depreciated_value = depreciated_value_eur / rate_from_eur


        depreciation_results_display.append({
            'item': item,
            'cost': display_cost,
            'depreciated_value': display_depreciated_value,
            'display_currency': display_currency_code
        })

    # Prepare data for charts (always in EUR)
    value_chart_labels = ['Depreciated Value', 'Value Lost to Depreciation']
    value_chart_data = [round(total_depreciated_value_eur, 2), round(max(0.0, total_original_value_eur - total_depreciated_value_eur), 2)]

    location_chart_labels = list(depreciation_by_location.keys())
    location_chart_data_original = [round(data['original'], 2) for data in depreciation_by_location.values()]
    location_chart_data_depreciated = [round(data['depreciated'], 2) for data in depreciation_by_location.values()]

    # Sort results for display
    depreciation_results_display.sort(key=lambda x: x['item'].purchase_date if x['item'].purchase_date else date.min, reverse=True)


    return render_template(
        'reports/depreciation.html',
        results=depreciation_results_display, # Use the display-ready results
        suppliers=suppliers,
        users=users,
        groups=groups,
        locations=locations,
        all_brands=all_brands,
        # Pass filters back
        start_date=start_date, end_date=end_date, item_type=item_type,
        supplier_id=supplier_id, brand=brand, user_id=user_id, group_id=group_id,
        location_id=location_id,
        depreciation_period=depreciation_period,
        depreciation_algorithm=depreciation_algorithm,
        currency=currency, # Pass selected display currency
        # Chart data (in EUR)
        value_chart_labels=value_chart_labels,
        value_chart_data=value_chart_data,
        location_chart_labels=location_chart_labels,
        location_chart_data_original=location_chart_data_original,
        location_chart_data_depreciated=location_chart_data_depreciated
    )