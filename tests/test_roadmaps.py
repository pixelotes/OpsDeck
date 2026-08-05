"""
Roadmaps domain service tests.

Covers the step↔date translation, dependency-graph guards, finish-to-start
propagation and the Gantt payload. No routes yet — those arrive with the
blueprint in a later phase.
"""
from datetime import date

import pytest

from src.extensions import db
from src.models.roadmaps import (Roadmap, RoadmapPeriod, RoadmapGoal, RoadmapInitiative,
                                 RoadmapDependency, STEPS_PER_PERIOD)
from src.services.roadmaps_service import (
    step_bounds, recompute_dates, creates_cycle, cascade_reschedule,
    sync_dependency_lags, bundle)


Q1_START, Q1_END = date(2027, 1, 1), date(2027, 3, 31)
Q2_START, Q2_END = date(2027, 4, 1), date(2027, 6, 30)


@pytest.fixture
def roadmap(init_database):
    """A roadmap with two dated quarters and one goal."""
    rm = Roadmap(name='IT & Security 2027', status='active')
    db.session.add(rm)
    db.session.flush()
    db.session.add_all([
        RoadmapPeriod(roadmap_id=rm.id, label='Q1 2027', position=0,
                      start_date=Q1_START, end_date=Q1_END),
        RoadmapPeriod(roadmap_id=rm.id, label='Q2 2027', position=1,
                      start_date=Q2_START, end_date=Q2_END),
    ])
    db.session.add(RoadmapGoal(roadmap_id=rm.id, name='Harden identity', position=0))
    db.session.commit()
    return rm


def _goal(roadmap):
    return roadmap.goals.first()


def _initiative(goal, name, start_step, end_step, **kwargs):
    initiative = RoadmapInitiative(goal_id=goal.id, name=name,
                                   start_step=start_step, end_step=end_step, **kwargs)
    db.session.add(initiative)
    db.session.flush()
    return initiative


def _link(predecessor, successor, lag=1):
    dep = RoadmapDependency(predecessor_id=predecessor.id, successor_id=successor.id, lag=lag)
    db.session.add(dep)
    db.session.flush()
    return dep


# --- step_bounds -------------------------------------------------------------

def test_step_bounds_without_periods_returns_none(init_database):
    assert step_bounds(1, []) == (None, None)


def test_step_bounds_with_undated_period_returns_none(roadmap):
    undated = RoadmapPeriod(roadmap_id=roadmap.id, label='Q3 2027', position=2)
    db.session.add(undated)
    db.session.flush()
    assert step_bounds(1, [undated]) == (None, None)


def test_first_step_starts_on_the_period_start(roadmap):
    periods = roadmap.periods.all()
    start, _ = step_bounds(1, periods)
    assert start == Q1_START


def test_last_step_of_a_period_ends_on_the_period_end(roadmap):
    """The invariant that makes a full-period initiative span exactly that period."""
    periods = roadmap.periods.all()
    _, end = step_bounds(STEPS_PER_PERIOD, periods)
    assert end == Q1_END


def test_steps_roll_over_into_the_next_period(roadmap):
    periods = roadmap.periods.all()
    start, _ = step_bounds(STEPS_PER_PERIOD + 1, periods)
    assert start == Q2_START


def test_steps_past_the_last_period_are_clamped(roadmap):
    """Dragging past the end of the roadmap still yields usable dates."""
    periods = roadmap.periods.all()
    _, end = step_bounds(999, periods)
    assert end == Q2_END


def test_steps_before_the_grid_are_clamped(roadmap):
    periods = roadmap.periods.all()
    start, _ = step_bounds(0, periods)
    assert start == Q1_START


def test_step_bounds_is_monotonic_past_the_end(roadmap):
    """Clamping the step (not just the period index) keeps dragging right monotonic."""
    periods = roadmap.periods.all()
    ends = [step_bounds(s, periods)[1] for s in (998, 999, 1000, 1001)]
    assert ends == sorted(ends)
    assert set(ends) == {Q2_END}


# --- recompute_dates ---------------------------------------------------------

def test_recompute_dates_derives_planned_dates_from_steps(roadmap):
    initiative = _initiative(_goal(roadmap), 'MFA rollout', 1, STEPS_PER_PERIOD)

    assert recompute_dates(roadmap) == 1
    assert initiative.planned_start_date == Q1_START
    assert initiative.planned_end_date == Q1_END


def test_recompute_dates_is_idempotent(roadmap):
    _initiative(_goal(roadmap), 'MFA rollout', 1, STEPS_PER_PERIOD)

    assert recompute_dates(roadmap) == 1
    assert recompute_dates(roadmap) == 0


def test_recompute_dates_follows_a_period_date_change(roadmap):
    """Moving a period's dates must drag its initiatives' planned dates along."""
    initiative = _initiative(_goal(roadmap), 'MFA rollout', 1, STEPS_PER_PERIOD)
    recompute_dates(roadmap)

    q1 = roadmap.periods.first()
    q1.end_date = date(2027, 4, 15)
    db.session.flush()

    assert recompute_dates(roadmap) == 1
    assert initiative.planned_end_date == date(2027, 4, 15)


def test_recompute_dates_clears_dates_when_periods_are_undated(roadmap):
    initiative = _initiative(_goal(roadmap), 'MFA rollout', 1, STEPS_PER_PERIOD)
    recompute_dates(roadmap)
    assert initiative.planned_start_date is not None

    for period in roadmap.periods.all():
        period.start_date = None
        period.end_date = None
    db.session.flush()

    recompute_dates(roadmap)
    assert initiative.planned_start_date is None
    assert initiative.planned_end_date is None


# --- creates_cycle -----------------------------------------------------------

def test_self_dependency_is_a_cycle(roadmap):
    a = _initiative(_goal(roadmap), 'A', 1, 4)
    assert creates_cycle(a.id, a.id) is True


def test_direct_back_edge_is_a_cycle(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b)

    assert creates_cycle(b.id, a.id) is True


def test_indirect_back_edge_is_a_cycle(roadmap):
    goal = _goal(roadmap)
    a, b, c = (_initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8),
               _initiative(goal, 'C', 9, 12))
    _link(a, b)
    _link(b, c)

    assert creates_cycle(c.id, a.id) is True


def test_shortcut_edge_is_not_a_cycle(roadmap):
    """A→C alongside A→B→C converges, it does not loop."""
    goal = _goal(roadmap)
    a, b, c = (_initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8),
               _initiative(goal, 'C', 9, 12))
    _link(a, b)
    _link(b, c)

    assert creates_cycle(a.id, c.id) is False


# --- cascade_reschedule ------------------------------------------------------

def test_cascade_pushes_a_linear_chain_forward(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b, lag=1)

    a.end_step = 8            # user stretched A
    db.session.flush()
    moved = cascade_reschedule(a.id)

    assert [m.id for m in moved] == [b.id]
    assert (b.start_step, b.end_step) == (9, 12)


def test_cascade_preserves_duration(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 12)
    _link(a, b, lag=1)
    original_duration = b.end_step - b.start_step

    a.end_step = 8
    db.session.flush()
    cascade_reschedule(a.id)

    assert b.end_step - b.start_step == original_duration


def test_cascade_pulls_a_successor_back(roadmap):
    """The finish-to-start constraint is exact, so slack is closed too."""
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 20, 23)
    _link(a, b, lag=1)

    cascade_reschedule(a.id)

    assert (b.start_step, b.end_step) == (5, 8)


def test_cascade_takes_the_latest_predecessor_on_a_diamond(roadmap):
    """Converging paths must resolve to the *latest* constraint, not the last one walked.

    X fans out to A (short) and B (long), and both feed D. A naive implementation
    that writes D once per predecessor lands it at 13 or 17 depending on traversal
    order; taking the maximum makes it deterministically 17.
    """
    goal = _goal(roadmap)
    x = _initiative(goal, 'X', 1, 4)
    a = _initiative(goal, 'A', 5, 8)
    b = _initiative(goal, 'B', 5, 12)
    d = _initiative(goal, 'D', 13, 16)
    _link(x, a, lag=1)
    _link(x, b, lag=1)
    _link(a, d, lag=1)
    _link(b, d, lag=1)

    x.end_step = 8            # push the root out by four steps
    db.session.flush()
    cascade_reschedule(x.id)

    assert (a.start_step, a.end_step) == (9, 12)
    assert (b.start_step, b.end_step) == (9, 16)
    # D is bound by B (ends at 16), not by A (ends at 12).
    assert (d.start_step, d.end_step) == (17, 20)


def test_cascade_is_stable_when_nothing_needs_moving(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b, lag=1)

    assert cascade_reschedule(a.id) == []


def test_cascade_clamps_to_the_first_step(roadmap):
    """A large negative lag must not push a successor off the start of the grid."""
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b, lag=-10)

    cascade_reschedule(a.id)

    assert (b.start_step, b.end_step) == (1, 4)


def test_cascade_refreshes_planned_dates(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b, lag=1)
    recompute_dates(roadmap)
    assert b.planned_start_date == Q2_START

    a.end_step = 8
    db.session.flush()
    cascade_reschedule(a.id)

    # B now starts at step 9, i.e. beyond the last period, so its date clamps into
    # Q2 — the point being that it moved rather than keeping the stale Q2_START.
    assert b.start_step == 9
    assert b.planned_start_date != Q2_START
    assert b.planned_start_date == step_bounds(9, roadmap.periods.all())[0]


def test_cascade_on_unknown_initiative_is_a_noop(init_database):
    assert cascade_reschedule(999999) == []


# --- sync_dependency_lags ----------------------------------------------------

def test_sync_lags_follows_a_direct_drag(roadmap):
    """Dragging a successor redefines its intended gap instead of fighting the lag."""
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    dep = _link(a, b, lag=1)

    b.start_step, b.end_step = 9, 12
    db.session.flush()
    sync_dependency_lags(b.id)

    assert dep.lag == 5       # 9 - 4


# --- bundle ------------------------------------------------------------------

def test_bundle_of_unknown_roadmap_is_none(init_database):
    assert bundle(999999) is None


def test_bundle_shape(roadmap):
    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8, position=1)
    _link(a, b, lag=1)
    recompute_dates(roadmap)
    db.session.commit()

    payload = bundle(roadmap.id)

    assert payload['roadmap']['name'] == 'IT & Security 2027'
    assert payload['roadmap']['steps_per_period'] == STEPS_PER_PERIOD
    assert len(payload['periods']) == 2
    assert len(payload['goals']) == 1
    assert len(payload['initiatives']) == 2
    assert len(payload['dependencies']) == 1

    first = payload['initiatives'][0]
    assert first['name'] == 'A'
    assert first['planned_start_date'] == Q1_START.isoformat()
    assert first['is_overdue'] is False
    assert payload['dependencies'][0]['lag'] == 1


def test_bundle_excludes_other_roadmaps_dependencies(roadmap):
    """Guards against leaking another roadmap's graph into the payload."""
    other = Roadmap(name='Other', status='draft')
    db.session.add(other)
    db.session.flush()
    other_goal = RoadmapGoal(roadmap_id=other.id, name='Other goal', position=0)
    db.session.add(other_goal)
    db.session.flush()
    c, d = _initiative(other_goal, 'C', 1, 4), _initiative(other_goal, 'D', 5, 8)
    _link(c, d, lag=1)

    goal = _goal(roadmap)
    a, b = _initiative(goal, 'A', 1, 4), _initiative(goal, 'B', 5, 8)
    _link(a, b, lag=1)
    db.session.commit()

    payload = bundle(roadmap.id)

    assert {i['name'] for i in payload['initiatives']} == {'A', 'B'}
    assert len(payload['dependencies']) == 1
    assert payload['dependencies'][0]['predecessor_id'] == a.id
