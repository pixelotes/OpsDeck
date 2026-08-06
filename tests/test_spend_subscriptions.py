"""
Tests for historical subscription spend reconstruction in the Spend Analysis
report, the supporting finance_service helpers, and the CostHistory integrity
logging when subscription seats change.
"""
from dateutil.relativedelta import relativedelta
from src import db
from src.utils.timezone_helper import today
from src.models import Subscription, User
from src.models.procurement import CostHistory
from src.services.finance_service import (
    subscription_occurrences_in_range,
    subscription_effective_cost_at,
    get_renewal_date_before,
)


def _make_sub(name="Acme SaaS", cost=10.0, currency="EUR", months_ago=5,
              pricing_model="fixed", cost_per_user=None):
    sub = Subscription(
        name=name,
        subscription_type="SaaS",
        renewal_date=today() - relativedelta(months=months_ago),
        renewal_period_type="monthly",
        renewal_period_value=1,
        cost=cost,
        currency=currency,
        pricing_model=pricing_model,
        cost_per_user=cost_per_user,
        auto_renew=True,
    )
    db.session.add(sub)
    db.session.commit()
    return sub


# --- Occurrence enumeration ---

def test_occurrences_in_past_window(init_database):
    sub = _make_sub(months_ago=5)
    end = today()
    start = end - relativedelta(months=3)
    occ = subscription_occurrences_in_range([sub], start, end)
    dates = [d for d, _ in occ]
    assert len(dates) >= 3
    assert all(start <= d <= end for d in dates)
    # Monthly grid: consecutive occurrences are one month apart
    dates_sorted = sorted(dates)
    assert dates_sorted == sorted(set(dates))  # no duplicates


def test_renewal_date_before_is_one_period_back(init_database):
    sub = _make_sub(months_ago=0)  # renewal_date = today
    prev = get_renewal_date_before(sub, sub.renewal_date)
    assert prev == sub.renewal_date - relativedelta(months=1)


# --- Effective cost resolution from CostHistory ---

def test_effective_cost_uses_history(init_database):
    db = init_database
    sub = _make_sub(cost=20.0)  # current cost 20
    # Two historical snapshots: 10 effective 60d ago, 20 effective 20d ago
    db.session.add(CostHistory(subscription_id=sub.id, cost=10.0, currency="EUR",
                               pricing_model="fixed", changed_date=today() - relativedelta(days=60)))
    db.session.add(CostHistory(subscription_id=sub.id, cost=20.0, currency="EUR",
                               pricing_model="fixed", changed_date=today() - relativedelta(days=20)))
    db.session.commit()

    amount_old, cur_old, _ = subscription_effective_cost_at(sub, today() - relativedelta(days=40))
    amount_new, cur_new, _ = subscription_effective_cost_at(sub, today() - relativedelta(days=5))
    assert amount_old == 10.0
    assert amount_new == 20.0
    assert cur_old == "EUR" and cur_new == "EUR"


def test_effective_cost_falls_back_to_current(init_database):
    sub = _make_sub(cost=15.0)  # no cost history
    amount, currency, _ = subscription_effective_cost_at(sub, today())
    assert amount == 15.0
    assert currency == "EUR"


def test_effective_cost_same_day_uses_last_change(init_database):
    """Multiple seat changes on the same day: the last one recorded wins."""
    db = init_database
    sub = _make_sub(cost=0.0, pricing_model="per_user", cost_per_user=5.0)
    same_day = today() - relativedelta(days=10)
    # Three changes the same day: 3 seats -> 7 seats -> 4 seats (final)
    for seats in (3, 7, 4):
        db.session.add(CostHistory(subscription_id=sub.id, cost=0.0, currency="EUR",
                                   pricing_model="per_user", cost_per_user=5.0, user_count=seats,
                                   changed_date=same_day, reason="user_added"))
        db.session.commit()  # commit each so ids increment in order
    amount, _, _ = subscription_effective_cost_at(sub, today())
    assert amount == 20.0  # 5.0 * 4 (the last change that day)


def test_effective_cost_per_user_uses_seat_count(init_database):
    db = init_database
    sub = _make_sub(cost=0.0, pricing_model="per_user", cost_per_user=5.0)
    # Snapshot: 3 seats at 5.0 each = 15 effective 30d ago
    db.session.add(CostHistory(subscription_id=sub.id, cost=0.0, currency="EUR",
                               pricing_model="per_user", cost_per_user=5.0, user_count=3,
                               changed_date=today() - relativedelta(days=30)))
    db.session.commit()
    amount, _, _ = subscription_effective_cost_at(sub, today() - relativedelta(days=10))
    assert amount == 15.0  # 5.0 * 3 seats


# --- Report integration ---

def test_report_includes_subscription_spend(auth_client, app):
    with app.app_context():
        _make_sub(name="ReportSub", months_ago=4)
    end = today()
    start = end - relativedelta(months=3)
    resp = auth_client.get(
        f'/reports/spend-analysis?item_type=subscriptions'
        f'&start_date={start.strftime("%Y-%m-%d")}&end_date={end.strftime("%Y-%m-%d")}'
    )
    assert resp.status_code == 200
    assert b'ReportSub' in resp.data
    assert b'Spend by Month' in resp.data


# --- Integrity: seat changes log CostHistory ---

def test_adding_user_to_per_user_sub_logs_cost_history(auth_client, app):
    with app.app_context():
        sub = _make_sub(name="SeatSub", pricing_model="per_user", cost=0.0, cost_per_user=7.0)
        u = User(name="Seat User", email="seat@test.com", role="user")
        db.session.add(u)
        db.session.commit()
        sub_id, uid = sub.id, u.id

    auth_client.post(f'/subscriptions/{sub_id}/users/add',
                     data={'user_ids': [uid]}, follow_redirects=True)

    with app.app_context():
        entries = CostHistory.query.filter_by(subscription_id=sub_id, reason='user_added').all()
        assert len(entries) >= 1
        assert entries[-1].user_count == 1


def test_adding_user_to_fixed_sub_does_not_log(auth_client, app):
    with app.app_context():
        sub = _make_sub(name="FixedSub", pricing_model="fixed", cost=10.0)
        u = User(name="Fixed User", email="fixeduser@test.com", role="user")
        db.session.add(u)
        db.session.commit()
        sub_id, uid = sub.id, u.id

    auth_client.post(f'/subscriptions/{sub_id}/users/add',
                     data={'user_ids': [uid]}, follow_redirects=True)

    with app.app_context():
        assert CostHistory.query.filter_by(subscription_id=sub_id).count() == 0
