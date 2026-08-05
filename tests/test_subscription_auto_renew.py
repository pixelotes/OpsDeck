"""
Tests for Subscription auto_renew flag behavior

Verifies that the auto_renew flag is properly respected in renewal calculations.
"""
import pytest
from datetime import timedelta

from src.models.procurement import Subscription, Supplier
from src.extensions import db
from src.utils.timezone_helper import today


@pytest.fixture
def test_supplier(app):
    """Create a test supplier."""
    with app.app_context():
        supplier = Supplier(
            name='Test Supplier',
            website='https://test.com'
        )
        db.session.add(supplier)
        db.session.commit()
        yield supplier
        # Cleanup
        Subscription.query.filter_by(supplier_id=supplier.id).delete()
        db.session.delete(supplier)
        db.session.commit()


class TestSubscriptionAutoRenew:
    """Test suite for auto_renew flag behavior."""

    def test_auto_renew_true_calculates_next_renewal(self, app, test_supplier):
        """Test that subscriptions with auto_renew=True calculate next renewal."""
        with app.app_context():
            # Create subscription with auto_renew=True and past renewal date
            past_date = today() - timedelta(days=30)

            subscription = Subscription(
                name='Auto-Renewing Subscription',
                subscription_type='SaaS',
                renewal_date=past_date,
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,  # ← Auto-renewal enabled
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(subscription)
            db.session.commit()

            # Should calculate next renewal date
            next_renewal = subscription.next_renewal_date
            assert next_renewal is not None, "auto_renew=True should calculate next renewal"
            assert next_renewal >= today(), "Next renewal should be in the future"

    def test_auto_renew_false_returns_none(self, app, test_supplier):
        """Test that subscriptions with auto_renew=False return None for next renewal."""
        with app.app_context():
            # Create subscription with auto_renew=False
            past_date = today() - timedelta(days=30)

            subscription = Subscription(
                name='One-Time Subscription',
                subscription_type='License',
                renewal_date=past_date,
                renewal_period_type='yearly',
                renewal_period_value=1,
                auto_renew=False,  # ← Auto-renewal disabled
                cost=1000.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(subscription)
            db.session.commit()

            # Should NOT calculate next renewal date
            next_renewal = subscription.next_renewal_date
            assert next_renewal is None, "auto_renew=False should return None"

    def test_auto_renew_false_future_date_returns_none(self, app, test_supplier):
        """Test that auto_renew=False returns None even if renewal_date is in future."""
        with app.app_context():
            # Create subscription with future renewal date but auto_renew=False
            future_date = today() + timedelta(days=30)

            subscription = Subscription(
                name='Non-Renewing Future Subscription',
                subscription_type='Service',
                renewal_date=future_date,
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=False,  # ← Auto-renewal disabled
                cost=50.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(subscription)
            db.session.commit()

            # Should still return None (no next renewal after current)
            next_renewal = subscription.next_renewal_date
            assert next_renewal is None, "auto_renew=False should always return None"

    def test_auto_renew_default_is_false(self, app, test_supplier):
        """Test that auto_renew defaults to False."""
        with app.app_context():
            # Create subscription without specifying auto_renew
            subscription = Subscription(
                name='Default Auto-Renew Subscription',
                subscription_type='SaaS',
                renewal_date=today(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id
                # auto_renew not specified - should default to False
            )
            db.session.add(subscription)
            db.session.commit()

            # Default should be False
            assert subscription.auto_renew is False, "auto_renew should default to False"
            assert subscription.next_renewal_date is None, "Default (False) should return None"

    def test_toggling_auto_renew(self, app, test_supplier):
        """Test that toggling auto_renew changes next_renewal_date behavior."""
        with app.app_context():
            past_date = today() - timedelta(days=15)

            subscription = Subscription(
                name='Toggleable Subscription',
                subscription_type='SaaS',
                renewal_date=past_date,
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(subscription)
            db.session.commit()

            # With auto_renew=True, should calculate
            assert subscription.next_renewal_date is not None

            # Toggle to False
            subscription.auto_renew = False
            db.session.commit()

            # Now should return None
            assert subscription.next_renewal_date is None

            # Toggle back to True
            subscription.auto_renew = True
            db.session.commit()

            # Should calculate again
            assert subscription.next_renewal_date is not None

    def test_auto_renew_with_different_periods(self, app, test_supplier):
        """Test auto_renew behavior with different renewal periods."""
        with app.app_context():
            past_date = today() - timedelta(days=90)

            # Test yearly renewal
            yearly_sub = Subscription(
                name='Yearly Subscription',
                subscription_type='License',
                renewal_date=past_date,
                renewal_period_type='yearly',
                renewal_period_value=1,
                auto_renew=True,
                cost=1200.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(yearly_sub)

            # Test custom (90-day) renewal
            custom_sub = Subscription(
                name='Quarterly Subscription',
                subscription_type='Service',
                renewal_date=past_date,
                renewal_period_type='custom',
                renewal_period_value=90,
                auto_renew=True,
                cost=300.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(custom_sub)
            db.session.commit()

            # Both should calculate next renewal
            assert yearly_sub.next_renewal_date is not None
            assert custom_sub.next_renewal_date is not None
            assert yearly_sub.next_renewal_date >= today()
            assert custom_sub.next_renewal_date >= today()

            # Disable both
            yearly_sub.auto_renew = False
            custom_sub.auto_renew = False
            db.session.commit()

            # Both should return None
            assert yearly_sub.next_renewal_date is None
            assert custom_sub.next_renewal_date is None
