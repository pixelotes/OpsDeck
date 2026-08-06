# src/services/finance_service.py
"""
Finance service for managing exchange rates.
"""
import logging
import requests

from ..extensions import db
from ..models.finance import FinanceSettings, ExchangeRate
from ..models.core import CURRENCY_RATES
from src.utils.timezone_helper import now


logger = logging.getLogger(__name__)


def update_exchange_rates():
    """
    Fetch exchange rates from the configured API provider and store them.
    Uses Frankfurter API by default (free, no API key required, ECB data).
    """
    settings = FinanceSettings.get_settings()
    
    try:
        # Build the API URL
        url = f"{settings.api_endpoint}?from={settings.base_currency}"
        
        logger.info(f"Fetching exchange rates from {url}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        rates = data.get('rates', {})
        
        if not rates:
            logger.warning("No rates returned from API")
            return False
        
        # Store each rate
        fetched_at = now()
        for currency_code, rate in rates.items():
            # Store as rate to convert TO base currency (inverse of API response)
            # API gives: 1 EUR = X USD, we want conversion rate TO EUR
            conversion_rate = 1.0 / rate if rate != 0 else 1.0
            
            new_rate = ExchangeRate(
                currency_code=currency_code,
                rate=conversion_rate,
                fetched_at=fetched_at
            )
            db.session.add(new_rate)
        
        # Also add the base currency with rate 1.0
        base_rate = ExchangeRate(
            currency_code=settings.base_currency,
            rate=1.0,
            fetched_at=fetched_at
        )
        db.session.add(base_rate)
        
        # Update last sync time
        settings.last_sync_at = fetched_at
        db.session.commit()
        
        logger.info(f"Successfully updated {len(rates) + 1} exchange rates")
        return True
        
    except requests.RequestException as e:
        logger.error(f"Error fetching exchange rates: {e}")
        db.session.rollback()
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating exchange rates: {e}")
        db.session.rollback()
        return False


def get_conversion_rate(currency_code):
    """
    Get the conversion rate to EUR for a currency.
    Falls back to hardcoded rates if DB lookup fails.
    
    Args:
        currency_code: The currency code (e.g., 'USD', 'GBP')
        
    Returns:
        float: The conversion rate to EUR (multiply amount by this to get EUR)
    """
    if not currency_code:
        return 1.0
    
    currency_code = currency_code.upper()
    
    # 1. Try to get the most recent rate from the database
    try:
        latest_rate = ExchangeRate.get_latest_rate(currency_code)
        if latest_rate:
            return latest_rate.rate
    except Exception as e:
        logger.warning(f"Error looking up rate for {currency_code}: {e}")
    
    # 2. Fallback to hardcoded rates
    return CURRENCY_RATES.get(currency_code, 1.0)


def renewal_occurrences_in_range(subscriptions, start_date, end_date):
    """
    Return every subscription renewal occurrence that falls within
    [start_date, end_date] as a list of (renewal_date, subscription) tuples.

    Iterates recurring renewals via ``get_renewal_date_after`` so multiple
    renewals of the same subscription inside the range are all counted.
    Subscriptions without a next renewal (e.g. auto_renew disabled) are skipped.

    Shared by the Ops & Finance dashboard and the Organizational Health
    "Operations Pulse" card so both report the same spend figures.
    """
    occurrences = []
    for subscription in subscriptions:
        next_renewal = subscription.next_renewal_date
        if next_renewal is None:
            continue
        while next_renewal and next_renewal <= end_date:
            if next_renewal >= start_date:
                occurrences.append((next_renewal, subscription))
            next_renewal = subscription.get_renewal_date_after(next_renewal)
    return occurrences


def get_renewal_date_before(subscription, current_renewal):
    """One renewal period BEFORE current_renewal (mirror of get_renewal_date_after)."""
    from dateutil.relativedelta import relativedelta
    from datetime import timedelta
    import calendar

    if subscription.renewal_period_type == 'monthly':
        prev_base = current_renewal - relativedelta(months=subscription.renewal_period_value)
        day = prev_base.day
        if subscription.monthly_renewal_day:
            if subscription.monthly_renewal_day == 'first':
                day = 1
            elif subscription.monthly_renewal_day == 'last':
                day = calendar.monthrange(prev_base.year, prev_base.month)[1]
            else:
                try:
                    last_day = calendar.monthrange(prev_base.year, prev_base.month)[1]
                    day = min(int(subscription.monthly_renewal_day), last_day)
                except (ValueError, TypeError):
                    pass
        return prev_base.replace(day=day)
    elif subscription.renewal_period_type == 'yearly':
        return current_renewal - relativedelta(years=subscription.renewal_period_value)
    else:  # custom (days)
        return current_renewal - timedelta(days=subscription.renewal_period_value)


def subscription_occurrences_in_range(subscriptions, start_date, end_date):
    """Every billing occurrence (charge date) within [start_date, end_date].

    Walks the renewal grid both forward and backward from each subscription's
    renewal_date anchor, so it works for arbitrary past (and future) windows.
    The window itself bounds the result; the cost effective on each occurrence
    is resolved separately (see ``subscription_effective_cost_at``).
    """
    occurrences = []
    for sub in subscriptions:
        anchor = sub.renewal_date
        if not anchor:
            continue

        # Forward from the anchor (inclusive)
        d = anchor
        guard = 0
        while d <= end_date and guard < 5000:
            if d >= start_date:
                occurrences.append((d, sub))
            d = sub.get_renewal_date_after(d)
            guard += 1

        # Backward from the anchor (exclusive)
        d = get_renewal_date_before(sub, anchor)
        guard = 0
        while d and d >= start_date and guard < 5000:
            if d <= end_date:
                occurrences.append((d, sub))
            d = get_renewal_date_before(sub, d)
            guard += 1
    return occurrences


def subscription_effective_cost_at(subscription, on_date):
    """Total cost effective on ``on_date`` as (amount, currency, amount_eur).

    Resolves the cost from the latest CostHistory entry effective on/before the
    date (capturing price and seat changes); falls back to the subscription's
    current cost if no history precedes the date.
    """
    # Pick the most recent entry effective on/before the date. changed_date has
    # day granularity, so several changes can share a day (you may add/remove
    # many users the same day); break ties by id so the LAST change recorded
    # that day wins — the state that stood at the billing date.
    chosen = None
    for h in sorted(subscription.cost_history, key=lambda x: (x.changed_date, x.id or 0)):
        if h.changed_date <= on_date:
            chosen = h
        else:
            break
    if chosen is not None:
        amount = chosen.total_cost
        currency = chosen.currency or 'EUR'
    else:
        amount = subscription.current_cost
        currency = subscription.currency or 'EUR'
    return amount, currency, amount * get_conversion_rate(currency)
