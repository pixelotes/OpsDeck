from datetime import date, datetime, timedelta
import pytest
from src import db
from src.models import Budget, Subscription, Supplier, CostHistory
from src.utils.timezone_helper import today

def test_purchase_cost_calculation(auth_client, app):
    """
    Test 12: Purchase.total_cost adds up its assets and peripherals.
    """
    # --- 1. Setup ---
    # auth_client has already created an admin (id 1) and a user (id 2)
    
    # Create a purchase (id 1)
    auth_client.post('/purchases/new', data={
        'description': 'Compra de Portátiles Q4',
        'purchase_date': '2025-11-14'
    }, follow_redirects=True)
    
    # Create an asset (cost=1000) and a peripheral (cost=150)
    # y enlazarlos a la Compra (ID 1)
    auth_client.post('/assets/new', data={
        'name': 'Laptop A',
        'status': 'Stored',
        'cost': 1000,
        'purchase_id': 1
    }, follow_redirects=True)
    
    auth_client.post('/peripherals/new', data={
        'name': 'Monitor A',
        'status': 'Stored',
        'cost': 150,
        'purchase_id': 1
    }, follow_redirects=True)

    # --- 2. Act ---
    # Open the purchase detail page
    response = auth_client.get('/purchases/1')
    
    # --- 3. Verify ---
    assert response.status_code == 200
    # Assumes the template renders the total cost as 1150.00
    assert b'1150.00' in response.data

def test_budget_remaining_calculation(auth_client, app):
    """
    Test 13: Budget.remaining subtracts the cost of the purchases against it.
    """
    # --- 1. Setup ---
    
    # Create a budget (id 1) of 5000
    auth_client.post('/budgets/new', data={
        'name': 'Presupuesto IT 2025',
        'amount': 5000,
        'valid_from': '2025-01-01',
        'valid_until': '2025-12-31'
    }, follow_redirects=True)
    
    # Create a purchase (id 1) enlazada al Presupuesto 1
    auth_client.post('/purchases/new', data={
        'description': 'Compra de Servidor',
        'purchase_date': '2025-11-14',
        'budget_id': 1
    }, follow_redirects=True)
    
    # Create an asset (cost=3000) linked to purchase 1
    auth_client.post('/assets/new', data={
        'name': 'Servidor R740',
        'status': 'Stored',
        'cost': 3000,
        'purchase_id': 1
    }, follow_redirects=True)

    with app.app_context():
        budget = db.session.get(Budget, 1)
        assert budget is not None
        # 5000 (Presupuesto) - 3000 (Coste Activo) = 2000 (Restante)
        assert budget.remaining == 2000.00


def test_budget_is_active_within_period(app):
    """
    Test that Budget.is_active() returns True for dates within the validity period.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # Date in the middle of the period should be active
        assert budget.is_active(date(2024, 6, 15)) is True


def test_budget_is_active_on_first_day(app):
    """
    Test that Budget.is_active() returns True on valid_from date (inclusive).
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # First day should be active (inclusive)
        assert budget.is_active(date(2024, 1, 1)) is True


def test_budget_is_active_on_last_day(app):
    """
    Test that Budget.is_active() returns True on valid_until date (inclusive).
    This is the main edge case mentioned in bug #6.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # Last day should be active (inclusive)
        assert budget.is_active(date(2024, 12, 31)) is True


def test_budget_is_active_before_period(app):
    """
    Test that Budget.is_active() returns False for dates before valid_from.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # Date before period should be inactive
        assert budget.is_active(date(2023, 12, 31)) is False


def test_budget_is_active_after_period(app):
    """
    Test that Budget.is_active() returns False for dates after valid_until.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # Date after period should be inactive
        assert budget.is_active(date(2025, 1, 1)) is False


def test_budget_is_active_with_datetime_object(app):
    """
    Test that Budget.is_active() correctly handles datetime objects by converting to date.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # Datetime object should be converted to date (time component ignored)
        test_datetime = datetime(2024, 6, 15, 14, 30, 0)
        assert budget.is_active(test_datetime) is True

        # Edge case: datetime on last day with late hour should still be valid
        # because it's the same DATE as valid_until
        last_day_evening = datetime(2024, 12, 31, 23, 59, 59)
        assert budget.is_active(last_day_evening) is True


def test_budget_is_active_defaults_to_today(app):
    """
    Test that Budget.is_active() defaults to today's date when no parameter is provided.
    """
    with app.app_context():
        current_date = today()

        # Create budget that includes today
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=current_date - timedelta(days=30),
            valid_until=current_date + timedelta(days=30)
        )
        db.session.add(budget)
        db.session.commit()

        # No parameter should default to today and be active
        assert budget.is_active() is True

        # Create budget that expired yesterday
        expired_budget = Budget(
            name='Expired Budget',
            amount=1000,
            valid_from=current_date - timedelta(days=60),
            valid_until=current_date - timedelta(days=1)
        )
        db.session.add(expired_budget)
        db.session.commit()

        # Should be inactive when checking with default (today)
        assert expired_budget.is_active() is False


def test_budget_negative_amount_validation(app):
    """
    Test that Budget.amount validates against negative values (Bug #7).
    """
    with app.app_context():
        with pytest.raises(ValueError, match="must be greater than 0"):
            budget = Budget(
                name='Invalid Budget',
                amount=-1000,  # Negative amount should raise ValueError
                valid_from=date(2024, 1, 1),
                valid_until=date(2024, 12, 31)
            )
            db.session.add(budget)
            db.session.flush()  # Force validation


def test_budget_zero_amount_validation(app):
    """
    Test that Budget.amount validates against zero value (Bug #7).
    """
    with app.app_context():
        with pytest.raises(ValueError, match="must be greater than 0"):
            budget = Budget(
                name='Invalid Budget',
                amount=0,  # Zero amount should raise ValueError
                valid_from=date(2024, 1, 1),
                valid_until=date(2024, 12, 31)
            )
            db.session.add(budget)
            db.session.flush()  # Force validation


def test_budget_positive_amount_validation(app):
    """
    Test that Budget.amount accepts positive values.
    """
    with app.app_context():
        budget = Budget(
            name='Valid Budget',
            amount=1000,  # Positive amount should be accepted
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        assert budget.amount == 1000


def test_subscription_negative_cost_validation(app):
    """
    Test that Subscription.cost validates against negative values (Bug #8).
    """
    with app.app_context():
        # Create a supplier first (required FK)
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.commit()

        with pytest.raises(ValueError, match="must not be negative"):
            subscription = Subscription(
                name='Invalid Subscription',
                subscription_type='SaaS',
                renewal_date=date(2024, 6, 15),
                renewal_period_type='monthly',
                cost=-100,  # Negative cost should raise ValueError
                supplier_id=supplier.id
            )
            db.session.add(subscription)
            db.session.flush()  # Force validation


def test_subscription_zero_cost_allowed(app):
    """
    Test that Subscription.cost allows zero value (for per_user pricing).
    """
    with app.app_context():
        # Create a supplier first (required FK)
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.commit()

        # Zero cost is valid (used for per_user pricing model)
        subscription = Subscription(
            name='Zero Cost Subscription',
            subscription_type='SaaS',
            renewal_date=date(2024, 6, 15),
            renewal_period_type='monthly',
            cost=0,
            supplier_id=supplier.id
        )
        db.session.add(subscription)
        db.session.flush()
        assert subscription.cost == 0


def test_subscription_positive_cost_validation(app):
    """
    Test that Subscription.cost accepts positive values.
    """
    with app.app_context():
        # Create a supplier first (required FK)
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.commit()

        subscription = Subscription(
            name='Valid Subscription',
            subscription_type='SaaS',
            renewal_date=date(2024, 6, 15),
            renewal_period_type='monthly',
            cost=99.99,  # Positive cost should be accepted
            supplier_id=supplier.id
        )
        db.session.add(subscription)
        db.session.commit()

        assert subscription.cost == 99.99


# === Bug fix regression tests ===


def test_budget_remaining_ignores_non_renewable_subscriptions(app):
    """
    Bug 1: Budget.remaining must NOT project future renewals for
    subscriptions with auto_renew=False.
    """
    with app.app_context():
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.flush()

        budget = Budget(
            name='2024 Budget',
            amount=10000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.flush()

        # Non-renewable subscription with renewal_date outside budget period
        sub = Subscription(
            name='Expiring SaaS',
            subscription_type='SaaS',
            renewal_date=date(2025, 3, 15),  # Outside budget period
            renewal_period_type='yearly',
            renewal_period_value=1,
            auto_renew=False,
            cost=1200,
            currency='EUR',
            supplier_id=supplier.id,
            budget_id=budget.id
        )
        db.session.add(sub)
        db.session.commit()

        # Non-renewable + renewal_date outside period = 0 spent
        assert budget.remaining == 10000


def test_budget_remaining_counts_renewable_subscriptions(app):
    """
    Bug 1: Budget.remaining MUST count all renewals for auto_renew=True
    subscriptions within the budget period.
    """
    with app.app_context():
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.flush()

        budget = Budget(
            name='2024 Budget',
            amount=10000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.flush()

        # Auto-renewing monthly subscription: 12 renewals in 2024
        sub = Subscription(
            name='Monthly SaaS',
            subscription_type='SaaS',
            renewal_date=date(2024, 1, 1),
            renewal_period_type='monthly',
            renewal_period_value=1,
            auto_renew=True,
            cost=100,
            currency='EUR',
            supplier_id=supplier.id,
            budget_id=budget.id
        )
        db.session.add(sub)
        db.session.commit()

        # 12 monthly renewals × €100 = €1200 spent
        assert budget.remaining == 10000 - 1200


def test_budget_remaining_non_renewable_counts_once_if_in_period(app):
    """
    Bug 1: A non-renewable subscription whose renewal_date falls within
    the budget period should be counted exactly once.
    """
    with app.app_context():
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.flush()

        budget = Budget(
            name='2024 Budget',
            amount=5000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.flush()

        sub = Subscription(
            name='One-off License',
            subscription_type='SaaS',
            renewal_date=date(2024, 6, 15),  # Inside budget period
            renewal_period_type='yearly',
            renewal_period_value=1,
            auto_renew=False,
            cost=500,
            currency='EUR',
            supplier_id=supplier.id,
            budget_id=budget.id
        )
        db.session.add(sub)
        db.session.commit()

        # Counted exactly once: 5000 - 500 = 4500
        assert budget.remaining == 4500


def test_count_renewals_zero_period_value(app):
    """
    Bug 2: _count_renewals_in_period must return 0 when period_value
    is 0 or negative, preventing an infinite loop.
    """
    with app.app_context():
        budget = Budget(
            name='Test Budget',
            amount=1000,
            valid_from=date(2024, 1, 1),
            valid_until=date(2024, 12, 31)
        )
        db.session.add(budget)
        db.session.commit()

        # period_value=0 should return 0 (not infinite loop)
        assert budget._count_renewals_in_period(
            date(2024, 1, 1), 'monthly', 0
        ) == 0

        # Negative period_value should also return 0
        assert budget._count_renewals_in_period(
            date(2024, 1, 1), 'yearly', -1
        ) == 0

        # None period_value should also return 0
        assert budget._count_renewals_in_period(
            date(2024, 1, 1), 'monthly', None
        ) == 0


def test_subscription_renewal_period_value_validation(app):
    """
    Bug 2: Subscription must reject renewal_period_value <= 0
    at the model level to prevent bad data from entering the DB.
    """
    with app.app_context():
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.commit()

        with pytest.raises(ValueError, match="greater than 0"):
            Subscription(
                name='Bad Sub',
                subscription_type='SaaS',
                renewal_date=date(2024, 1, 1),
                renewal_period_type='monthly',
                renewal_period_value=0,  # Should raise ValueError
                cost=100,
                supplier_id=supplier.id
            )

        with pytest.raises(ValueError, match="greater than 0"):
            Subscription(
                name='Bad Sub 2',
                subscription_type='SaaS',
                renewal_date=date(2024, 1, 1),
                renewal_period_type='monthly',
                renewal_period_value=-5,  # Should also raise
                cost=100,
                supplier_id=supplier.id
            )


def test_cost_history_per_user_zero_users(app):
    """
    Bug 5: CostHistory.total_cost must return 0 (not None) when
    pricing_model='per_user' and user_count=0.
    """
    with app.app_context():
        supplier = Supplier(name='Test Supplier')
        db.session.add(supplier)
        db.session.flush()

        sub = Subscription(
            name='Per User SaaS',
            subscription_type='SaaS',
            renewal_date=date(2024, 1, 1),
            renewal_period_type='monthly',
            cost=10,
            supplier_id=supplier.id,
            pricing_model='per_user',
            cost_per_user=10.0
        )
        db.session.add(sub)
        db.session.flush()

        # user_count=0 should yield total_cost=0, not None or error
        history = CostHistory(
            subscription_id=sub.id,
            cost=0,
            currency='EUR',
            pricing_model='per_user',
            cost_per_user=10.0,
            user_count=0,
            reason='manual'
        )
        db.session.add(history)
        db.session.commit()

        assert history.total_cost == 0

        # user_count=None should also yield 0
        history2 = CostHistory(
            subscription_id=sub.id,
            cost=0,
            currency='EUR',
            pricing_model='per_user',
            cost_per_user=10.0,
            user_count=None,
            reason='manual'
        )
        db.session.add(history2)
        db.session.commit()

        assert history2.total_cost == 0