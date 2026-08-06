"""
Tests for timezone edge cases

Verifies that timezone handling works correctly around midnight and DST transitions.
Specifically tests the bug where subscriptions created on Jan 1st appeared as Dec 31st.
"""
import pytest
from datetime import datetime
import pytz
import os

# Set timezone for testing
os.environ['TIMEZONE'] = 'Europe/Madrid'

from src.models.procurement import Subscription, Supplier
from src.extensions import db


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


class TestTimezoneEdgeCases:
    """Test suite for timezone edge cases."""

    def test_subscription_created_jan_1st_shows_correct_date(self, app, test_supplier):
        """
        Test that a subscription created on Jan 1st at 00:30 AM local time
        shows the correct date (Jan 1st, not Dec 31st).

        This was the reported bug: subscriptions created on Jan 1st appeared
        as Dec 31st of the previous year due to UTC/local timezone confusion.
        """
        with app.app_context():
            madrid_tz = pytz.timezone('Europe/Madrid')

            # Simulate creating subscription on Jan 1st at 00:30 AM Madrid time
            jan_1_local = madrid_tz.localize(datetime(2026, 1, 1, 0, 30, 0))

            # Create subscription with this timestamp
            subscription = Subscription(
                name='New Year Subscription',
                subscription_type='SaaS',
                renewal_date=jan_1_local.date(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id
            )

            # Set created_at manually to simulate the edge case time
            subscription.created_at = jan_1_local

            db.session.add(subscription)
            db.session.commit()

            # Verify renewal_date is Jan 1st (not Dec 31st)
            assert subscription.renewal_date.year == 2026
            assert subscription.renewal_date.month == 1
            assert subscription.renewal_date.day == 1, \
                "Renewal date should be Jan 1st, not Dec 31st"

            # Verify created_at is also Jan 1st
            assert subscription.created_at.year == 2026
            assert subscription.created_at.month == 1
            assert subscription.created_at.day == 1, \
                "Created_at should be Jan 1st, not Dec 31st"

            # Verify that when converted to date, it's still Jan 1st
            created_date = subscription.created_at.date()
            assert created_date.day == 1
            assert created_date.month == 1

    def test_midnight_utc_vs_local_comparison(self, app, test_supplier):
        """
        Test that date comparisons work correctly around midnight.

        In Europe/Madrid (UTC+1), midnight local time is 23:00 UTC previous day.
        Ensure comparisons use local time, not UTC.
        """
        with app.app_context():
            madrid_tz = pytz.timezone('Europe/Madrid')

            # Jan 1st 00:15 AM Madrid time = Dec 31st 23:15 UTC
            jan_1_midnight_madrid = madrid_tz.localize(datetime(2026, 1, 1, 0, 15, 0))

            subscription = Subscription(
                name='Midnight Subscription',
                subscription_type='SaaS',
                renewal_date=jan_1_midnight_madrid.date(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id,
                created_at=jan_1_midnight_madrid
            )
            db.session.add(subscription)
            db.session.commit()

            # When comparing dates, should use local date not UTC date
            # renewal_date should be Jan 1st
            assert subscription.renewal_date.day == 1
            assert subscription.renewal_date.month == 1

            # created_at.date() should also be Jan 1st
            created_as_date = subscription.created_at.date()
            assert created_as_date.day == 1
            assert created_as_date.month == 1

    def test_dst_transition_spring(self, app, test_supplier):
        """
        Test behavior during spring DST transition (clock moves forward).

        In Europe/Madrid, clocks move from 2:00 AM to 3:00 AM on last Sunday of March.
        2:30 AM doesn't exist on that day.
        """
        with app.app_context():
            madrid_tz = pytz.timezone('Europe/Madrid')

            # In 2026, DST starts on March 29th at 2:00 AM
            # Times between 2:00 and 3:00 don't exist
            # pytz will handle this by moving to 3:00 AM

            # Create subscription on DST transition day
            dst_day = madrid_tz.localize(datetime(2026, 3, 29, 1, 30, 0))

            subscription = Subscription(
                name='DST Spring Subscription',
                subscription_type='SaaS',
                renewal_date=dst_day.date(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id,
                created_at=dst_day
            )
            db.session.add(subscription)
            db.session.commit()

            # Date should still be correct (March 29th)
            assert subscription.renewal_date.day == 29
            assert subscription.renewal_date.month == 3

    def test_dst_transition_fall(self, app, test_supplier):
        """
        Test behavior during fall DST transition (clock moves backward).

        In Europe/Madrid, clocks move from 3:00 AM to 2:00 AM on last Sunday of October.
        2:30 AM happens twice on that day.
        """
        with app.app_context():
            madrid_tz = pytz.timezone('Europe/Madrid')

            # In 2026, DST ends on October 25th at 3:00 AM
            # Times between 2:00 and 3:00 happen twice

            # Create subscription on DST transition day
            dst_day = madrid_tz.localize(datetime(2026, 10, 25, 2, 30, 0), is_dst=True)

            subscription = Subscription(
                name='DST Fall Subscription',
                subscription_type='SaaS',
                renewal_date=dst_day.date(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id,
                created_at=dst_day
            )
            db.session.add(subscription)
            db.session.commit()

            # Date should still be correct (October 25th)
            assert subscription.renewal_date.day == 25
            assert subscription.renewal_date.month == 10

    def test_comparison_with_today_uses_local_date(self, app, test_supplier):
        """
        Test that comparisons with today() use local date, not UTC date.
        """
        with app.app_context():
            from src.utils.timezone_helper import today

            # Get today in local timezone
            local_today = today()

            # Create subscription with today's date
            subscription = Subscription(
                name='Today Subscription',
                subscription_type='SaaS',
                renewal_date=local_today,
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id
            )
            db.session.add(subscription)
            db.session.commit()

            # Verify that renewal_date == today (local)
            assert subscription.renewal_date == local_today

            # If we were using UTC incorrectly, this might fail near midnight
            assert subscription.renewal_date.day == local_today.day
            assert subscription.renewal_date.month == local_today.month
            assert subscription.renewal_date.year == local_today.year

    def test_year_boundary_backward(self, app, test_supplier):
        """
        Test creating subscription on Dec 31st doesn't appear as Jan 1st.
        (Reverse of the original bug)
        """
        with app.app_context():
            madrid_tz = pytz.timezone('Europe/Madrid')

            # Dec 31st at 23:30 Madrid time
            dec_31_late = madrid_tz.localize(datetime(2025, 12, 31, 23, 30, 0))

            subscription = Subscription(
                name='New Year Eve Subscription',
                subscription_type='SaaS',
                renewal_date=dec_31_late.date(),
                renewal_period_type='monthly',
                renewal_period_value=1,
                auto_renew=True,
                cost=100.0,
                currency='USD',
                supplier_id=test_supplier.id,
                created_at=dec_31_late
            )
            db.session.add(subscription)
            db.session.commit()

            # Should be Dec 31st, not Jan 1st
            assert subscription.renewal_date.year == 2025
            assert subscription.renewal_date.month == 12
            assert subscription.renewal_date.day == 31

            assert subscription.created_at.year == 2025
            assert subscription.created_at.month == 12
            assert subscription.created_at.day == 31
