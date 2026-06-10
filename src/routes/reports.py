from flask import (
    Blueprint, render_template, request, url_for
)
from sqlalchemy import func
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from ..models import db, Subscription, Asset, Supplier, User, Group, Peripheral, Location, License, Purchase
from ..models.assets import Brand
from ..services.finance_service import (
    get_conversion_rate, subscription_occurrences_in_range, subscription_effective_cost_at
)
from .main import login_required
from ..services.permissions_service import requires_permission
from src.utils.timezone_helper import now, today


reports_bp = Blueprint('reports', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'

@reports_bp.route('/subscription-reports', methods=['GET'])
@login_required
@requires_permission(MODULE)
def subscription_reports():
    local_today = today()
    selected_year = request.args.get('year', default=local_today.year, type=int)

    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()

    # Chart 1: Spending by Supplier
    supplier_spending = {}
    year_start = date(selected_year, 1, 1)
    year_end = date(selected_year, 12, 31)

    for subscription in all_active_subscriptions:
        if not subscription.auto_renew:
            continue
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
    monthly_start_date = (local_today.replace(day=1) - relativedelta(months=12))
    monthly_labels, monthly_costs = [], {}
    for i in range(13): # 13 months to cover the full range
        month_date = monthly_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        monthly_labels.append(month_date.strftime('%b %Y'))
        monthly_costs[year_month_key] = 0

    yearly_start_date = local_today.replace(year=local_today.year - 4, month=1, day=1)
    yearly_labels, yearly_costs = [], {}
    for i in range(5): # Last 5 years including current
        year_date = yearly_start_date + relativedelta(years=i)
        yearly_labels.append(year_date.strftime('%Y'))
        yearly_costs[year_date.strftime('%Y')] = 0

    for subscription in all_active_subscriptions:
        if not subscription.auto_renew:
            continue
        renewal = subscription.renewal_date
        # Ensure initial renewal is correctly handled if before start dates
        while renewal < yearly_start_date:
             renewal = subscription.get_renewal_date_after(renewal)

        while renewal <= local_today:
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
    forecast_start_date = local_today.replace(day=1)
    end_of_forecast_period = forecast_start_date + relativedelta(months=+13)
    forecast_labels, forecast_keys, forecast_costs = [], [], {}
    for i in range(13):
        month_date = forecast_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_keys.append(year_month_key)
        forecast_costs[year_month_key] = 0

    for subscription in all_active_subscriptions:
        if not subscription.auto_renew:
            continue
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

@reports_bp.route('/asset-reports', methods=['GET'])
@login_required
@requires_permission(MODULE)
def asset_reports():
    assets_by_brand = (
        db.session.query(Brand.name, func.count(Asset.id))
        .outerjoin(Asset, Asset.brand_id == Brand.id)
        .filter(Asset.is_archived == False)
        .group_by(Brand.name)
        .all()
    )
    # Include assets with no brand assigned
    unbranded_count = db.session.query(func.count(Asset.id)).filter(
        Asset.is_archived == False, Asset.brand_id.is_(None)
    ).scalar() or 0
    brand_labels = [item[0] for item in assets_by_brand]
    brand_data = [item[1] for item in assets_by_brand]
    if unbranded_count:
        brand_labels.append('N/A')
        brand_data.append(unbranded_count)

    assets_by_supplier = db.session.query(Supplier.name, func.count(Asset.id)).join(Asset).filter(Asset.is_archived == False).group_by(Supplier.name).all()
    supplier_labels = [item[0] or 'N/A' for item in assets_by_supplier]
    supplier_data = [item[1] for item in assets_by_supplier]

    assets_by_status = db.session.query(Asset.status, func.count(Asset.id)).filter(Asset.is_archived == False).group_by(Asset.status).all()
    status_labels = [item[0] for item in assets_by_status]
    status_data = [item[1] for item in assets_by_status]

    # --- Warranty Logic (Considering both Assets and Peripherals potentially) ---
    local_today = today()
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
        if item.warranty_end_date and item.warranty_end_date > local_today:
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

@reports_bp.route('/assets-dashboard', methods=['GET'])
@login_required
@requires_permission(MODULE)
def assets_dashboard():
    """Executive Asset Operations Dashboard with KPIs, health metrics, and lifecycle tracking."""
    from sqlalchemy.orm import joinedload
    from ..models.assets import MaintenanceLog
    
    local_today = today()
    
    # Single optimized query for all non-archived assets
    all_assets = Asset.query.filter(
        Asset.is_archived == False
    ).options(
        joinedload(Asset.location),
        joinedload(Asset.supplier)
    ).all()
    
    # --- KPI 1: Total Fleet Size ---
    total_fleet = len(all_assets)
    
    # --- KPI 2: Total Value (CAPEX vs Depreciated) ---
    total_capex = 0.0
    total_current_value = 0.0
    useful_life_months = 48  # 4 years default for IT equipment
    
    for asset in all_assets:
        if asset.cost:
            # Convert to EUR for aggregation
            rate_to_eur = get_conversion_rate(asset.currency)
            cost_eur = asset.cost * rate_to_eur
            total_capex += cost_eur
            
            # Calculate depreciated value
            if asset.purchase_date:
                months_old = (local_today - asset.purchase_date).days / 30.44
                depreciation_amount = (cost_eur / useful_life_months) * months_old
                current_value = max(0.0, cost_eur - depreciation_amount)
                total_current_value += current_value
            else:
                # No purchase date, assume full value
                total_current_value += cost_eur
    
    # --- KPI 3: Average Fleet Age ---
    ages = []
    for asset in all_assets:
        if asset.purchase_date:
            age_years = (local_today - asset.purchase_date).days / 365.25
            ages.append(age_years)
    
    avg_fleet_age = round(sum(ages) / len(ages), 1) if ages else 0.0
    
    # --- KPI 4: Dead Stock Rate ---
    in_stock_count = sum(1 for a in all_assets if a.status == 'In Stock')
    dead_stock_rate = round((in_stock_count / total_fleet * 100), 1) if total_fleet > 0 else 0.0
    
    # --- Health Metric 1: Breakdown Rate (last 12 months) ---
    twelve_months_ago = local_today - relativedelta(months=12)
    
    # Get all repair maintenance logs from last 12 months
    repair_logs = MaintenanceLog.query.filter(
        MaintenanceLog.event_type == 'Repair',
        MaintenanceLog.event_date >= twelve_months_ago,
        MaintenanceLog.asset_id.isnot(None)
    ).all()
    
    # Get unique asset IDs that had repairs
    assets_with_repairs = set(log.asset_id for log in repair_logs)
    breakdown_rate = round((len(assets_with_repairs) / total_fleet * 100), 1) if total_fleet > 0 else 0.0
    
    # --- Health Metric 2: "The Lemons" (Top 5 Problematic Assets) ---
    # Count maintenance incidents per asset
    maintenance_counts = {}
    all_maintenance = MaintenanceLog.query.filter(
        MaintenanceLog.asset_id.isnot(None)
    ).all()
    
    for log in all_maintenance:
        maintenance_counts[log.asset_id] = maintenance_counts.get(log.asset_id, 0) + 1
    
    # Get top 5 assets with most incidents
    top_problematic = sorted(maintenance_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    lemons = []
    for asset_id, count in top_problematic:
        asset = db.session.get(Asset,asset_id)
        if asset and not asset.is_archived:
            lemons.append({'asset': asset, 'incident_count': count})
    
    # --- Lifecycle Metric 1: Warranty Cliff ---
    warranty_30_days = 0
    warranty_60_days = 0
    warranty_90_days = 0
    warranty_expiring_soon = []  # For table display
    
    for asset in all_assets:
        if asset.warranty_end_date:
            days_until_expiry = (asset.warranty_end_date - local_today).days
            
            if 0 <= days_until_expiry <= 30:
                warranty_30_days += 1
                warranty_expiring_soon.append({
                    'asset': asset,
                    'days_remaining': days_until_expiry
                })
            elif 0 <= days_until_expiry <= 60:
                warranty_60_days += 1
            elif 0 <= days_until_expiry <= 90:
                warranty_90_days += 1
    
    # Sort warranty expiring by days remaining
    warranty_expiring_soon.sort(key=lambda x: x['days_remaining'])
    
    # --- Lifecycle Metric 2: EOL Candidates (> 5 years old) ---
    eol_candidates = []
    for asset in all_assets:
        if asset.purchase_date:
            age_years = (local_today - asset.purchase_date).days / 365.25
            if age_years > 5:
                eol_candidates.append(asset)
    
    # --- Chart Data 1: Distribution by Status ---
    status_counts = {}
    for asset in all_assets:
        status = asset.status or 'Unknown'
        status_counts[status] = status_counts.get(status, 0) + 1
    
    status_labels = list(status_counts.keys())
    status_data = list(status_counts.values())
    
    # --- Chart Data 2: Breakdown Rate by Brand ---
    brand_breakdown = {}
    brand_totals = {}
    
    for asset in all_assets:
        brand = asset.brand.name if asset.brand else 'Unknown'
        brand_totals[brand] = brand_totals.get(brand, 0) + 1

        if asset.id in assets_with_repairs:
            brand_breakdown[brand] = brand_breakdown.get(brand, 0) + 1
    
    # Calculate percentages
    brand_labels = []
    brand_breakdown_rates = []

    for brand, total in sorted(brand_totals.items(), key=lambda x: x[1], reverse=True)[:10]:  # Top 10 brands
        breakdown_count = brand_breakdown.get(brand, 0)
        rate = round((breakdown_count / total * 100), 1) if total > 0 else 0.0
        brand_labels.append(brand)
        brand_breakdown_rates.append(rate)

    # --- Chart Data 3: Distribution by Brand (fleet count) ---
    brand_distribution_labels = []
    brand_distribution_data = []
    for brand, total in sorted(brand_totals.items(), key=lambda x: x[1], reverse=True):
        brand_distribution_labels.append(brand)
        brand_distribution_data.append(total)
    
    return render_template(
        'reports/assets_dashboard.html',
        # KPIs
        total_fleet=total_fleet,
        total_capex=round(total_capex, 2),
        total_current_value=round(total_current_value, 2),
        avg_fleet_age=avg_fleet_age,
        dead_stock_rate=dead_stock_rate,
        # Health Metrics
        breakdown_rate=breakdown_rate,
        lemons=lemons,
        # Lifecycle Metrics
        warranty_30_days=warranty_30_days,
        warranty_60_days=warranty_60_days,
        warranty_90_days=warranty_90_days,
        warranty_expiring_soon=warranty_expiring_soon[:10],  # Top 10 for table
        eol_candidates_count=len(eol_candidates),
        # Chart Data
        status_labels=status_labels,
        status_data=status_data,
        brand_labels=brand_labels,
        brand_breakdown_rates=brand_breakdown_rates,
        brand_distribution_labels=brand_distribution_labels,
        brand_distribution_data=brand_distribution_data
    )


@reports_bp.route('/assets-dashboard/pdf', methods=['GET'])
@login_required
@requires_permission(MODULE)
def assets_dashboard_pdf():
    """Export Assets Dashboard as PDF."""
    from weasyprint import HTML
    from flask import make_response, session
    from sqlalchemy.orm import joinedload
    from ..models.assets import MaintenanceLog
    
    local_today = today()
    
    # Re-fetch data (similar to dashboard but optimized for PDF)
    all_assets = Asset.query.filter(
        Asset.is_archived == False
    ).options(
        joinedload(Asset.location),
        joinedload(Asset.supplier)
    ).all()
    
    total_fleet = len(all_assets)
    
    # Calculate KPIs
    total_capex = 0.0
    total_current_value = 0.0
    useful_life_months = 48
    
    for asset in all_assets:
        if asset.cost:
            rate_to_eur = get_conversion_rate(asset.currency)
            cost_eur = asset.cost * rate_to_eur
            total_capex += cost_eur
            
            if asset.purchase_date:
                months_old = (local_today - asset.purchase_date).days / 30.44
                depreciation_amount = (cost_eur / useful_life_months) * months_old
                current_value = max(0.0, cost_eur - depreciation_amount)
                total_current_value += current_value
            else:
                total_current_value += cost_eur
    
    ages = [
        (local_today - asset.purchase_date).days / 365.25
        for asset in all_assets if asset.purchase_date
    ]
    avg_fleet_age = round(sum(ages) / len(ages), 1) if ages else 0.0
    
    in_stock_count = sum(1 for a in all_assets if a.status == 'In Stock')
    dead_stock_rate = round((in_stock_count / total_fleet * 100), 1) if total_fleet > 0 else 0.0
    
    # Breakdown rate
    twelve_months_ago = local_today - relativedelta(months=12)
    repair_logs = MaintenanceLog.query.filter(
        MaintenanceLog.event_type == 'Repair',
        MaintenanceLog.event_date >= twelve_months_ago,
        MaintenanceLog.asset_id.isnot(None)
    ).all()
    
    assets_with_repairs = set(log.asset_id for log in repair_logs)
    breakdown_rate = round((len(assets_with_repairs) / total_fleet * 100), 1) if total_fleet > 0 else 0.0
    
    # Lemons
    maintenance_counts = {}
    all_maintenance = MaintenanceLog.query.filter(
        MaintenanceLog.asset_id.isnot(None)
    ).all()
    
    for log in all_maintenance:
        maintenance_counts[log.asset_id] = maintenance_counts.get(log.asset_id, 0) + 1
    
    top_problematic = sorted(maintenance_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    lemons = []
    for asset_id, count in top_problematic:
        asset = db.session.get(Asset,asset_id)
        if asset and not asset.is_archived:
            lemons.append({'asset': asset, 'incident_count': count})
    
    # Warranty expiring
    warranty_expiring_soon = []
    for asset in all_assets:
        if asset.warranty_end_date:
            days_until_expiry = (asset.warranty_end_date - local_today).days
            if 0 <= days_until_expiry <= 90:
                warranty_expiring_soon.append({
                    'asset': asset,
                    'days_remaining': days_until_expiry
                })
    
    warranty_expiring_soon.sort(key=lambda x: x['days_remaining'])
    
    # Status distribution for PDF
    status_counts = {}
    for asset in all_assets:
        status = asset.status or 'Unknown'
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Metadata
    user = db.session.get(User,session.get('user_id'))
    
    # Render HTML
    html_content = render_template(
        'reports/assets_dashboard_pdf.html',
        total_fleet=total_fleet,
        total_capex=round(total_capex, 2),
        total_current_value=round(total_current_value, 2),
        avg_fleet_age=avg_fleet_age,
        dead_stock_rate=dead_stock_rate,
        breakdown_rate=breakdown_rate,
        lemons=lemons,
        warranty_expiring_soon=warranty_expiring_soon[:20],
        status_counts=status_counts,
        generated_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        generated_by=user.name if user else 'System'
    )
    
    # Generate PDF
    pdf_file = HTML(string=html_content).write_pdf()
    
    response = make_response(pdf_file)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=assets_dashboard.pdf'
    
    return response


@reports_bp.route('/spend-analysis', methods=['GET'])
@login_required
@requires_permission('finance')
def spend_analysis():
    # --- Get filter options from the database ---
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()

    # Brand options come from the Brand table (only brands actually in use)
    all_brands = Brand.query.order_by(Brand.name).all()

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    item_type = request.args.get('item_type', 'all') # Changed default to 'all'
    supplier_id = request.args.get('supplier_id', type=int)
    brand_id = request.args.get('brand_id', type=int)
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
    if brand_id:
        assets_query = assets_query.filter(Asset.brand_id == brand_id)
        peripherals_query = peripherals_query.filter(Peripheral.brand_id == brand_id)

    # Apply location filter (only to Asset)
    if location_id:
        assets_query = assets_query.filter(Asset.location_id == location_id)

    # Handle user/group filtering
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = db.session.get(Group,group_id)
        if group:
            user_ids_to_filter.extend([user.id for user in group.users if not user.is_archived]) # Filter users by group membership

    if user_ids_to_filter:
        assets_query = assets_query.filter(Asset.user_id.in_(user_ids_to_filter))
        peripherals_query = peripherals_query.filter(Peripheral.user_id.in_(user_ids_to_filter))
        licenses_query = licenses_query.filter(License.user_id.in_(user_ids_to_filter))

    # --- Build unified spend rows (everything normalised to EUR) ---
    def to_eur(amount, currency):
        return (amount or 0) * get_conversion_rate(currency or 'EUR')

    rows = []

    # One-off purchases (assets, peripherals, standalone licenses)
    one_off = []
    if item_type in ['assets', 'all']:
        one_off.extend(assets_query.all())
    if item_type in ['peripherals', 'all']:
        one_off.extend(peripherals_query.all())
    if item_type in ['licenses', 'all']:
        one_off.extend(licenses_query.all())

    type_url = {
        'Asset': 'assets.asset_detail',
        'Peripheral': 'peripherals.peripheral_detail',
        'License': 'licenses.detail',
    }
    for item in one_off:
        cls = item.__class__.__name__
        if cls in ('Asset', 'Peripheral'):
            detail = item.brand.name if item.brand else 'N/A'
        elif cls == 'License':
            detail = item.software.name if item.software else 'N/A'
        else:
            detail = 'N/A'
        rows.append({
            'kind': cls,
            'recurring': False,
            'name': item.name,
            'url': url_for(type_url[cls], id=item.id),
            'detail': detail,
            'user': item.user.name if getattr(item, 'user', None) else 'N/A',
            'date': item.purchase_date,
            'currency': item.currency,
            'amount': item.cost,
            'amount_eur': to_eur(item.cost, item.currency),
        })

    # Subscriptions: actual recurring spend reconstructed per billing occurrence,
    # valued at the cost that was effective on each charge date (price + seats).
    # Recurring spend needs a bounded past window: default to the trailing 12
    # months when no range is given. Brand/Location filters don't apply to
    # subscriptions, so when either is set subscriptions are excluded.
    include_subs = item_type in ['subscriptions', 'all'] and not brand_id and not location_id
    sub_window = None
    if include_subs:
        window_end = end_date_obj if end_date else today()
        window_start = start_date_obj if start_date else (window_end - relativedelta(months=12))
        sub_window = (window_start, window_end)

        subs_query = Subscription.query.filter(Subscription.is_archived == False)
        if supplier_id:
            subs_query = subs_query.filter(Subscription.supplier_id == supplier_id)
        subscriptions_list = subs_query.all()
        if user_ids_to_filter:
            uid_set = set(user_ids_to_filter)
            subscriptions_list = [s for s in subscriptions_list if uid_set & {u.id for u in s.users}]

        for occ_date, sub in subscription_occurrences_in_range(subscriptions_list, window_start, window_end):
            amount, currency, amount_eur = subscription_effective_cost_at(sub, occ_date)
            rows.append({
                'kind': 'Subscription',
                'recurring': True,
                'name': sub.name,
                'url': url_for('subscriptions.subscription_detail', id=sub.id),
                'detail': sub.supplier.name if sub.supplier else 'N/A',
                'user': 'N/A',
                'date': occ_date,
                'currency': currency,
                'amount': amount,
                'amount_eur': amount_eur,
            })

    # Newest first
    rows.sort(key=lambda r: r['date'] if r['date'] else date.min, reverse=True)

    total_cost_eur = sum(r['amount_eur'] for r in rows)

    # Spend by month (EUR) — what was actually paid each month
    monthly_totals = {}
    for r in rows:
        if r['date']:
            key = r['date'].strftime('%Y-%m')
            monthly_totals[key] = monthly_totals.get(key, 0) + r['amount_eur']
    monthly_totals = dict(sorted(monthly_totals.items(), reverse=True))

    return render_template(
        'reports/spend_analysis.html',
        rows=rows,
        total_cost_eur=total_cost_eur,
        monthly_totals=monthly_totals,
        sub_window=sub_window,
        suppliers=suppliers,
        users=users,
        groups=groups,
        all_brands=all_brands,
        locations=locations,
        # Pass filters back to template
        start_date=start_date, end_date=end_date, item_type=item_type,
        supplier_id=supplier_id, brand_id=brand_id, user_id=user_id, group_id=group_id,
        location_id=location_id
    )


@reports_bp.route('/depreciation', methods=['GET'])
@login_required
@requires_permission(MODULE)
def depreciation_report():
    # --- Get filter options from the database ---
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()

    all_brands = Brand.query.order_by(Brand.name).all()

    # --- Get filter criteria from URL arguments ---
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    depreciation_period = request.args.get('depreciation_period', 5, type=int)
    depreciation_algorithm = request.args.get('depreciation_algorithm', 'linear')
    item_type = request.args.get('item_type', 'both') # 'both', 'assets', 'peripherals'
    supplier_id = request.args.get('supplier_id', type=int)
    brand_id = request.args.get('brand_id', type=int)
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
    if brand_id:
        assets_query = assets_query.filter(Asset.brand_id == brand_id)
        peripherals_query = peripherals_query.filter(Peripheral.brand_id == brand_id)

    # Apply location filter (only to Asset)
    if location_id:
        assets_query = assets_query.filter(Asset.location_id == location_id)

    # Handle user/group filtering
    user_ids_to_filter = []
    if user_id:
        user_ids_to_filter.append(user_id)
    if group_id:
        group = db.session.get(Group,group_id)
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
    local_today = today()
    total_original_value_eur = 0.0
    total_depreciated_value_eur = 0.0
    depreciation_by_location = {} # Store {'Location Name': {'original': X, 'depreciated': Y}} in EUR

    for item in results_to_depreciate:
        cost = item.cost # Already filtered for cost is not None
        depreciated_value_original_currency = None
        rate_to_eur = get_conversion_rate(item.currency)
        original_value_eur = cost * rate_to_eur

        if item.purchase_date: # Already filtered for purchase_date is not None
            age_in_days = (local_today - item.purchase_date).days
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
            rate_from_eur = get_conversion_rate(currency)
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
        supplier_id=supplier_id, brand_id=brand_id, user_id=user_id, group_id=group_id,
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