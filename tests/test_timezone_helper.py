"""
Tests for timezone helper module

Verifies that timezone-aware datetime functions work correctly
and handle DST transitions properly.
"""
from datetime import datetime, date, time
import pytz
import os

# Set timezone for testing
os.environ['TIMEZONE'] = 'Europe/Madrid'

from src.utils.timezone_helper import (
    now, today, current_time, to_local, to_utc,
    naive_to_aware, aware_to_naive, get_timezone_name,
    get_timezone_offset, is_dst, APP_TIMEZONE
)


class TestTimezoneHelper:
    """Test suite for timezone helper functions."""

    def test_timezone_loaded_correctly(self):
        """Test that timezone is loaded from environment."""
        assert get_timezone_name() == 'Europe/Madrid'
        assert APP_TIMEZONE.zone == 'Europe/Madrid'

    def test_now_returns_aware_datetime(self):
        """Test that now() returns timezone-aware datetime."""
        current = now()
        assert isinstance(current, datetime)
        assert current.tzinfo is not None
        assert current.tzinfo.zone == 'Europe/Madrid'

    def test_today_returns_date(self):
        """Test that today() returns date object."""
        current_date = today()
        assert isinstance(current_date, date)
        # Should match the date from now()
        assert current_date == now().date()

    def test_current_time_returns_time(self):
        """Test that current_time() returns time object."""
        current_t = current_time()
        assert isinstance(current_t, time)

    def test_to_local_from_utc_naive(self):
        """Test converting naive UTC datetime to local timezone."""
        # Winter time: 13:00 UTC = 14:00 Madrid (UTC+1)
        utc_dt = datetime(2026, 1, 15, 13, 0, 0)
        local_dt = to_local(utc_dt, from_tz='UTC')

        assert local_dt.tzinfo is not None
        assert local_dt.hour == 14  # UTC+1 in winter

    def test_to_local_from_utc_aware(self):
        """Test converting aware UTC datetime to local timezone."""
        # Create timezone-aware UTC datetime
        utc_dt = pytz.UTC.localize(datetime(2026, 1, 15, 13, 0, 0))
        local_dt = to_local(utc_dt)

        assert local_dt.tzinfo is not None
        assert local_dt.hour == 14  # UTC+1 in winter

    def test_to_local_dst_transition(self):
        """Test that DST transition is handled correctly."""
        # Summer time: 13:00 UTC = 15:00 Madrid (UTC+2)
        utc_dt = datetime(2026, 7, 15, 13, 0, 0)
        local_dt = to_local(utc_dt, from_tz='UTC')

        assert local_dt.tzinfo is not None
        assert local_dt.hour == 15  # UTC+2 in summer

    def test_to_utc_from_local(self):
        """Test converting local datetime to UTC."""
        # Create local datetime (winter)
        madrid_tz = pytz.timezone('Europe/Madrid')
        local_dt = madrid_tz.localize(datetime(2026, 1, 15, 14, 0, 0))

        utc_dt = to_utc(local_dt)
        assert utc_dt.tzinfo == pytz.UTC
        assert utc_dt.hour == 13  # 14:00 Madrid = 13:00 UTC in winter

    def test_to_utc_naive_datetime(self):
        """Test converting naive datetime to UTC (assumes app timezone)."""
        naive_dt = datetime(2026, 1, 15, 14, 0, 0)
        utc_dt = to_utc(naive_dt)

        assert utc_dt.tzinfo == pytz.UTC
        assert utc_dt.hour == 13  # Assumes Madrid timezone

    def test_naive_to_aware(self):
        """Test converting naive datetime to aware."""
        naive_dt = datetime(2026, 1, 15, 14, 30, 0)
        aware_dt = naive_to_aware(naive_dt)

        assert aware_dt.tzinfo is not None
        assert aware_dt.tzinfo.zone == 'Europe/Madrid'
        assert aware_dt.hour == 14
        assert aware_dt.minute == 30

    def test_naive_to_aware_already_aware(self):
        """Test that naive_to_aware returns aware datetime unchanged."""
        aware_dt = now()
        result = naive_to_aware(aware_dt)
        assert result == aware_dt

    def test_aware_to_naive(self):
        """Test converting aware datetime to naive."""
        aware_dt = now()
        naive_dt = aware_to_naive(aware_dt)

        assert naive_dt.tzinfo is None
        # Should preserve hour/minute in local timezone
        assert naive_dt.hour == aware_dt.hour
        assert naive_dt.minute == aware_dt.minute

    def test_get_timezone_offset_format(self):
        """Test that timezone offset is formatted correctly."""
        offset = get_timezone_offset()
        # Should be in format +HH:MM or -HH:MM
        assert len(offset) == 6
        assert offset[0] in ['+', '-']
        assert offset[3] == ':'

    def test_is_dst_returns_boolean(self):
        """Test that is_dst returns boolean."""
        dst_status = is_dst()
        assert isinstance(dst_status, bool)

    def test_to_local_with_none(self):
        """Test that to_local handles None gracefully."""
        result = to_local(None)
        assert result is None

    def test_to_utc_with_none(self):
        """Test that to_utc handles None gracefully."""
        result = to_utc(None)
        assert result is None

    def test_winter_summer_time_difference(self):
        """Test that the same UTC time maps to different local times in winter/summer."""
        # 12:00 UTC in January (winter)
        winter_utc = datetime(2026, 1, 15, 12, 0, 0)
        winter_local = to_local(winter_utc, from_tz='UTC')

        # 12:00 UTC in July (summer)
        summer_utc = datetime(2026, 7, 15, 12, 0, 0)
        summer_local = to_local(summer_utc, from_tz='UTC')

        # Should differ by 1 hour due to DST
        hour_diff = summer_local.hour - winter_local.hour
        assert hour_diff == 1, "Summer time should be 1 hour ahead due to DST"

    def test_different_source_timezone(self):
        """Test converting from non-UTC timezone."""
        # 12:00 in New York
        ny_dt = datetime(2026, 1, 15, 12, 0, 0)
        local_dt = to_local(ny_dt, from_tz='America/New_York')

        assert local_dt.tzinfo is not None
        # New York is UTC-5 in winter, Madrid is UTC+1
        # So 12:00 NY = 17:00 UTC = 18:00 Madrid
        assert local_dt.hour == 18
