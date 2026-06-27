"""
Tests for src/routes/reports.py
Covers: subscription_reports, asset_reports, spend_analysis, depreciation_report
"""
import pytest
from datetime import timedelta
from src import db
from src.utils.timezone_helper import today
from src.models import (
    Subscription, Supplier, Asset, User, Group, Peripheral, Location, License, Purchase, Brand
)


def _brand(name):
    """Get-or-create a Brand by name (brand is now a relationship, not a string column)."""
    b = Brand.query.filter_by(name=name).first()
    if not b:
        b = Brand(name=name)
        db.session.add(b)
        db.session.flush()
    return b


@pytest.fixture
def reports_data(app):
    """Creates sample data for reports testing."""
    with app.app_context():
        # Create supplier
        supplier = Supplier(name="Test Supplier Inc", email="info@testsupplier.com")
        db.session.add(supplier)
        db.session.commit()

        # Create user
        user = User(name="Reports User", email="reports@test.com", role="user")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

        # Create location
        location = Location(name="Main Office")
        db.session.add(location)
        db.session.commit()

        # Create group
        group = Group(name="IT Department")
        group.users.append(user)
        db.session.add(group)
        db.session.commit()

        # Create subscription
        subscription = Subscription(
            name="Cloud Service",
            subscription_type="SaaS",
            supplier_id=supplier.id,
            cost=100.0,
            currency="EUR",
            renewal_date=today() + timedelta(days=30),
            renewal_period_type="monthly",
            renewal_period_value=1
        )
        db.session.add(subscription)

        # Create brands first to avoid autoflush warnings
        brand_dell = _brand("Dell")
        brand_hp = _brand("HP")

        # Create assets
        asset1 = Asset(
            name="Laptop 01",
            brand=brand_dell,
            status="In Use",
            supplier_id=supplier.id,
            user_id=user.id,
            location_id=location.id,
            cost=1500.0,
            currency="EUR",
            purchase_date=today() - timedelta(days=365),
            warranty_length=24
        )
        db.session.add(asset1)

        asset2 = Asset(
            name="Laptop 02",
            brand=brand_hp,
            status="Available",
            cost=1200.0,
            currency="USD",
            purchase_date=today() - timedelta(days=730)
        )
        db.session.add(asset2)
        db.session.commit()

        # Create peripheral
        peripheral = Peripheral(
            name="Monitor",
            brand=brand_dell,
            supplier_id=supplier.id,
            user_id=user.id,
            cost=300.0,
            currency="EUR",
            purchase_date=today() - timedelta(days=180)
        )
        db.session.add(peripheral)
        db.session.commit()

        # Create purchase and license
        purchase = Purchase(
            description="Software Licenses",
            supplier_id=supplier.id,
            purchase_date=today() - timedelta(days=60)
        )
        purchase.users.append(user)
        db.session.add(purchase)
        db.session.commit()

        license_obj = License(
            name="Office 365",
            license_key="XXX-YYY-ZZZ",
            cost=200.0,
            currency="EUR",
            purchase_date=today() - timedelta(days=60),
            user_id=user.id,
            purchase_id=purchase.id
        )
        db.session.add(license_obj)
        db.session.commit()

        yield {
            'supplier_id': supplier.id,
            'user_id': user.id,
            'location_id': location.id,
            'group_id': group.id,
            'asset_id': asset1.id
        }


# --- Subscription Reports ---

def test_subscription_reports_loads(auth_client, reports_data):
    """Test that subscription reports page loads successfully."""
    response = auth_client.get('/reports/subscription-reports')
    assert response.status_code == 200


def test_subscription_reports_with_year_filter(auth_client, reports_data):
    """Test subscription reports with a specific year filter."""
    current_year = today().year
    response = auth_client.get(f'/reports/subscription-reports?year={current_year}')
    assert response.status_code == 200


def test_subscription_reports_previous_year(auth_client, reports_data):
    """Test subscription reports for a previous year."""
    previous_year = today().year - 1
    response = auth_client.get(f'/reports/subscription-reports?year={previous_year}')
    assert response.status_code == 200


# --- Asset Reports ---

def test_asset_reports_loads(auth_client, reports_data):
    """Test that asset reports page loads successfully."""
    response = auth_client.get('/reports/asset-reports')
    assert response.status_code == 200


def test_asset_reports_contains_chart_data(auth_client, reports_data):
    """Test that asset reports page loads and contains chart scripts."""
    response = auth_client.get('/reports/asset-reports')
    assert response.status_code == 200
    # Just verify the page loads with chart.js script
    assert b'chart' in response.data.lower()


# --- Assets Dashboard ---

def test_assets_dashboard_loads(auth_client, reports_data):
    """Test that assets dashboard page loads successfully."""
    response = auth_client.get('/reports/assets-dashboard')
    assert response.status_code == 200
    assert b'Asset Operations Dashboard' in response.data
    assert b'Total Fleet Size' in response.data
    assert b'Dead Stock Rate' in response.data


def test_assets_dashboard_contains_kpis(auth_client, reports_data):
    """Test that assets dashboard contains all KPI cards."""
    response = auth_client.get('/reports/assets-dashboard')
    assert response.status_code == 200
    # Check for KPI labels
    assert b'Total Fleet Size' in response.data
    assert b'Fleet Value' in response.data
    assert b'Average Fleet Age' in response.data
    assert b'Dead Stock Rate' in response.data


def test_assets_dashboard_contains_charts(auth_client, reports_data):
    """Test that assets dashboard includes Chart.js scripts."""
    response = auth_client.get('/reports/assets-dashboard')
    assert response.status_code == 200
    assert b'statusChart' in response.data
    assert b'breakdownChart' in response.data
    assert b'assets_dashboard.js' in response.data


def test_assets_dashboard_pdf_export(auth_client, reports_data):
    """Test PDF export generates successfully."""
    response = auth_client.get('/reports/assets-dashboard/pdf')
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/pdf'
    assert 'attachment' in response.headers['Content-Disposition']
    assert 'assets_dashboard.pdf' in response.headers['Content-Disposition']


def test_assets_dashboard_with_no_assets(auth_client, app):
    """Test dashboard handles empty asset list gracefully."""
    with app.app_context():
        # Archive all assets
        from src.models import Asset
        Asset.query.update({Asset.is_archived: True})
        db.session.commit()
    
    response = auth_client.get('/reports/assets-dashboard')
    assert response.status_code == 200
    # Should still render without errors
    assert b'Asset Operations Dashboard' in response.data


# --- Spend Analysis ---

def test_spend_analysis_loads(auth_client, reports_data):
    """Test that spend analysis page loads successfully."""
    response = auth_client.get('/reports/spend-analysis')
    assert response.status_code == 200


def test_spend_analysis_filter_by_item_type(auth_client, reports_data):
    """Test spend analysis filtered by assets only."""
    response = auth_client.get('/reports/spend-analysis?item_type=assets')
    assert response.status_code == 200


def test_spend_analysis_filter_by_peripherals(auth_client, reports_data):
    """Test spend analysis filtered by peripherals only."""
    response = auth_client.get('/reports/spend-analysis?item_type=peripherals')
    assert response.status_code == 200


def test_spend_analysis_filter_by_licenses(auth_client, reports_data):
    """Test spend analysis filtered by licenses only."""
    response = auth_client.get('/reports/spend-analysis?item_type=licenses')
    assert response.status_code == 200


def test_spend_analysis_filter_by_supplier(auth_client, reports_data):
    """Test spend analysis filtered by supplier."""
    response = auth_client.get(f'/reports/spend-analysis?supplier_id={reports_data["supplier_id"]}')
    assert response.status_code == 200


def test_spend_analysis_filter_by_brand(auth_client, reports_data):
    """Test spend analysis filtered by brand."""
    response = auth_client.get('/reports/spend-analysis?brand=Dell')
    assert response.status_code == 200


def test_spend_analysis_filter_by_user(auth_client, reports_data):
    """Test spend analysis filtered by user."""
    response = auth_client.get(f'/reports/spend-analysis?user_id={reports_data["user_id"]}')
    assert response.status_code == 200


def test_spend_analysis_filter_by_group(auth_client, reports_data):
    """Test spend analysis filtered by group."""
    response = auth_client.get(f'/reports/spend-analysis?group_id={reports_data["group_id"]}')
    assert response.status_code == 200


def test_spend_analysis_filter_by_location(auth_client, reports_data):
    """Test spend analysis filtered by location."""
    response = auth_client.get(f'/reports/spend-analysis?location_id={reports_data["location_id"]}')
    assert response.status_code == 200


def test_spend_analysis_filter_by_date_range(auth_client, reports_data):
    """Test spend analysis filtered by date range."""
    start = (today() - timedelta(days=400)).strftime('%Y-%m-%d')
    end = today().strftime('%Y-%m-%d')
    response = auth_client.get(f'/reports/spend-analysis?start_date={start}&end_date={end}')
    assert response.status_code == 200


def test_spend_analysis_combined_filters(auth_client, reports_data):
    """Test spend analysis with multiple filters combined."""
    response = auth_client.get(
        f'/reports/spend-analysis?item_type=all&supplier_id={reports_data["supplier_id"]}&brand=Dell'
    )
    assert response.status_code == 200


# --- Depreciation Report ---

def test_depreciation_report_loads(auth_client, reports_data):
    """Test that depreciation report page loads successfully."""
    response = auth_client.get('/reports/depreciation')
    assert response.status_code == 200


def test_depreciation_report_linear_algorithm(auth_client, reports_data):
    """Test depreciation with linear algorithm."""
    response = auth_client.get('/reports/depreciation?depreciation_algorithm=linear&depreciation_period=5')
    assert response.status_code == 200


def test_depreciation_report_declining_balance(auth_client, reports_data):
    """Test depreciation with declining balance algorithm."""
    response = auth_client.get('/reports/depreciation?depreciation_algorithm=declining_balance&depreciation_period=5')
    assert response.status_code == 200


def test_depreciation_report_filter_assets_only(auth_client, reports_data):
    """Test depreciation for assets only."""
    response = auth_client.get('/reports/depreciation?item_type=assets')
    assert response.status_code == 200


def test_depreciation_report_filter_peripherals_only(auth_client, reports_data):
    """Test depreciation for peripherals only."""
    response = auth_client.get('/reports/depreciation?item_type=peripherals')
    assert response.status_code == 200


def test_depreciation_report_with_currency_conversion(auth_client, reports_data):
    """Test depreciation with currency conversion."""
    response = auth_client.get('/reports/depreciation?currency=USD')
    assert response.status_code == 200


def test_depreciation_report_filter_by_location(auth_client, reports_data):
    """Test depreciation filtered by location."""
    response = auth_client.get(f'/reports/depreciation?location_id={reports_data["location_id"]}')
    assert response.status_code == 200


def test_depreciation_report_filter_by_supplier(auth_client, reports_data):
    """Test depreciation filtered by supplier."""
    response = auth_client.get(f'/reports/depreciation?supplier_id={reports_data["supplier_id"]}')
    assert response.status_code == 200


def test_depreciation_report_filter_by_brand(auth_client, reports_data):
    """Test depreciation filtered by brand."""
    response = auth_client.get('/reports/depreciation?brand=Dell')
    assert response.status_code == 200


def test_depreciation_report_filter_by_user(auth_client, reports_data):
    """Test depreciation filtered by user."""
    response = auth_client.get(f'/reports/depreciation?user_id={reports_data["user_id"]}')
    assert response.status_code == 200


def test_depreciation_report_filter_by_group(auth_client, reports_data):
    """Test depreciation filtered by group."""
    response = auth_client.get(f'/reports/depreciation?group_id={reports_data["group_id"]}')
    assert response.status_code == 200


def test_depreciation_report_date_range(auth_client, reports_data):
    """Test depreciation with date range filter."""
    start = (today() - timedelta(days=800)).strftime('%Y-%m-%d')
    end = today().strftime('%Y-%m-%d')
    response = auth_client.get(f'/reports/depreciation?start_date={start}&end_date={end}')
    assert response.status_code == 200


def test_depreciation_report_zero_period(auth_client, reports_data):
    """Test depreciation with zero period (edge case)."""
    response = auth_client.get('/reports/depreciation?depreciation_period=0')
    assert response.status_code == 200
