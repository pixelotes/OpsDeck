"""
Roadmaps domain service.

Holds the logic that must not live in the route layer: translating the integer
step grid into calendar dates, validating dependency graphs, propagating
finish-to-start constraints, and assembling the payload the Gantt view consumes.

Step grid recap (see models.roadmaps): an initiative spans ``start_step``..``end_step``
inclusive, 1-based, with ``STEPS_PER_PERIOD`` steps per period. Steps are the source
of truth; ``planned_start_date`` / ``planned_end_date`` are derived from them.

None of these functions commit — callers own the transaction boundary.
"""
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from datetime import date

from ..extensions import db
from ..models.roadmaps import (Roadmap, RoadmapPeriod, RoadmapGoal, RoadmapInitiative,
                               RoadmapDependency, STEPS_PER_PERIOD)


# --- Step ↔ date translation -------------------------------------------------

def step_bounds(step: int, periods: List[RoadmapPeriod]) -> Tuple[Optional[date], Optional[date]]:
    """Calendar range covered by a single step, as ``(start, end)``.

    The step is located in its period and interpolated linearly across that period's
    date range. Steps outside the grid are clamped to the first or last *step*, so an
    initiative dragged past the end of the roadmap still yields usable dates.

    Clamping the whole step rather than just the period index matters: keeping the
    original offset would make the result non-monotonic (step 999 landing mid-period
    while step 1000 lands at its end), so dates would oscillate while dragging right.

    Returns ``(None, None)`` when there are no periods or the target period has no dates.
    """
    if not periods:
        return None, None

    step = max(1, min(step, len(periods) * STEPS_PER_PERIOD))
    index = (step - 1) // STEPS_PER_PERIOD
    period = periods[index]
    if not (period.start_date and period.end_date):
        return None, None

    span = period.end_date - period.start_date
    offset = (step - 1) % STEPS_PER_PERIOD
    start = period.start_date + span * (offset / STEPS_PER_PERIOD)
    end = period.start_date + span * ((offset + 1) / STEPS_PER_PERIOD)
    return start, end


def recompute_dates(roadmap: Roadmap) -> int:
    """Refresh every initiative's denormalised planned dates from its steps.

    Must be called after anything that moves steps or changes a period's dates.
    Returns the number of initiatives whose dates actually changed.
    """
    periods = roadmap.periods.all()
    changed = 0
    for initiative in roadmap.initiatives.all():
        new_start, _ = step_bounds(initiative.start_step, periods)
        _, new_end = step_bounds(initiative.end_step, periods)
        if (initiative.planned_start_date, initiative.planned_end_date) != (new_start, new_end):
            initiative.planned_start_date = new_start
            initiative.planned_end_date = new_end
            changed += 1
    return changed


# --- Dependency graph --------------------------------------------------------

def creates_cycle(predecessor_id: int, successor_id: int) -> bool:
    """True if linking predecessor→successor would close a cycle.

    Walks forward from ``successor_id``; reaching ``predecessor_id`` means the new
    edge would complete a loop. Self-links count as cycles.
    """
    if predecessor_id == successor_id:
        return True

    stack, seen = [successor_id], set()
    while stack:
        current = stack.pop()
        if current == predecessor_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(
            row.successor_id for row in
            RoadmapDependency.query.filter_by(predecessor_id=current).all()
        )
    return False


def _descendants(initiative_id: int) -> List[int]:
    """Every initiative reachable downstream of ``initiative_id`` (excluding itself)."""
    found: List[int] = []
    seen = {initiative_id}
    stack = [initiative_id]
    while stack:
        current = stack.pop()
        for dep in RoadmapDependency.query.filter_by(predecessor_id=current).all():
            if dep.successor_id not in seen:
                seen.add(dep.successor_id)
                found.append(dep.successor_id)
                stack.append(dep.successor_id)
    return found


def _topological_order(node_ids: List[int]) -> List[int]:
    """Kahn ordering over the subgraph induced by ``node_ids``.

    Only edges with both ends inside the set constrain the ordering — edges coming
    from outside are constraints on the schedule, not on the traversal, because
    those predecessors are already in their final position.

    Nodes left over (only possible if a cycle slipped past ``creates_cycle``) are
    dropped rather than looping forever.
    """
    if not node_ids:
        return []

    nodes = set(node_ids)
    indegree = {n: 0 for n in node_ids}
    adjacency: Dict[int, List[int]] = {n: [] for n in node_ids}

    edges = RoadmapDependency.query.filter(
        RoadmapDependency.predecessor_id.in_(nodes),
        RoadmapDependency.successor_id.in_(nodes),
    ).all()
    for edge in edges:
        adjacency[edge.predecessor_id].append(edge.successor_id)
        indegree[edge.successor_id] += 1

    queue = [n for n in node_ids if indegree[n] == 0]
    order: List[int] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for neighbour in adjacency[current]:
            indegree[neighbour] -= 1
            if indegree[neighbour] == 0:
                queue.append(neighbour)
    return order


class RescheduleResult(NamedTuple):
    """Outcome of a cascade: what moved, and what could not be placed properly.

    ``clamped`` matters to the caller because a clamped initiative is the one case where
    the schedule stops being truthful — see cascade_reschedule.
    """
    moved: List[RoadmapInitiative]
    clamped: List[RoadmapInitiative]


def cascade_reschedule(initiative_id: int) -> RescheduleResult:
    """Propagate finish-to-start constraints downstream after an initiative moved.

    Each dependent is placed so that ``start_step == max(pred.end_step + lag)`` over
    *all* its predecessors, preserving its duration. Taking the maximum is what makes
    converging (diamond-shaped) dependency graphs deterministic: with two predecessors
    the later one wins, regardless of traversal order.

    Descendants are visited in topological order so a node is only moved once its own
    predecessors are final.

    Positions are kept inside the roadmap's grid: at least step 1, since negative lags
    would otherwise push a chain off the start, and at most far enough left that the bar
    still ends on the last step. Duration is always preserved, which is what makes the
    upper clamp lossy: an initiative that cannot start where its predecessors demand
    ends up earlier than the constraint requires, possibly overlapping them. That is a
    schedule which looks valid and is not, so those initiatives come back in
    ``clamped`` for the caller to report — the roadmap needs another period.

    Also refreshes planned dates, because they must never drift from the steps.
    Does not commit.
    """
    root = db.session.get(RoadmapInitiative, initiative_id)
    if not root:
        return RescheduleResult([], [])

    roadmap = root.roadmap
    # Zero periods means no grid to clamp against; leave the steps alone in that case.
    total_steps = (roadmap.periods.count() * STEPS_PER_PERIOD) if roadmap else 0

    moved: List[RoadmapInitiative] = []
    clamped: List[RoadmapInitiative] = []

    for node_id in _topological_order(_descendants(initiative_id)):
        initiative = db.session.get(RoadmapInitiative, node_id)
        if not initiative:
            continue

        incoming = RoadmapDependency.query.filter_by(successor_id=node_id).all()
        if not incoming:
            continue

        required = []
        for dep in incoming:
            predecessor = db.session.get(RoadmapInitiative, dep.predecessor_id)
            if predecessor:
                required.append(predecessor.end_step + dep.lag)
        if not required:
            continue

        duration = initiative.end_step - initiative.start_step
        wanted = max(required)
        new_start = wanted

        if total_steps:
            # Latest start that still leaves room for the whole bar. Negative when the
            # initiative is longer than the entire roadmap, hence the max(1, ...) below:
            # nothing can make that one fit, so it starts at the beginning.
            latest_start = total_steps - duration
            new_start = min(new_start, latest_start)
        new_start = max(1, new_start)

        if new_start < wanted:
            clamped.append(initiative)

        if initiative.start_step != new_start:
            initiative.start_step = new_start
            initiative.end_step = new_start + duration
            moved.append(initiative)

    if roadmap:
        recompute_dates(roadmap)
    return RescheduleResult(moved, clamped)


def sync_dependency_lags(initiative_id: int) -> None:
    """Re-derive the lag of incoming dependencies from current positions.

    Called when an initiative is dragged directly: the user's new position defines
    the intended gap to each predecessor, so the stored lag follows the drag rather
    than fighting it. Downstream dependents are handled by ``cascade_reschedule``.
    """
    initiative = db.session.get(RoadmapInitiative, initiative_id)
    if not initiative:
        return
    for dep in RoadmapDependency.query.filter_by(successor_id=initiative_id).all():
        predecessor = db.session.get(RoadmapInitiative, dep.predecessor_id)
        if predecessor:
            dep.lag = initiative.start_step - predecessor.end_step


# --- Gantt payload -----------------------------------------------------------

def _period_payload(period: RoadmapPeriod) -> Dict[str, Any]:
    return {
        'id': period.id,
        'label': period.label,
        'start_date': period.start_date.isoformat() if period.start_date else None,
        'end_date': period.end_date.isoformat() if period.end_date else None,
        'position': period.position,
    }


def _goal_payload(goal: RoadmapGoal) -> Dict[str, Any]:
    return {
        'id': goal.id,
        'name': goal.name,
        'description': goal.description or '',
        'color': goal.color,
        'owner_id': goal.owner_id,
        'position': goal.position,
    }


def _initiative_payload(initiative: RoadmapInitiative) -> Dict[str, Any]:
    return {
        'id': initiative.id,
        'goal_id': initiative.goal_id,
        'name': initiative.name,
        'description': initiative.description or '',
        'start_step': initiative.start_step,
        'end_step': initiative.end_step,
        'planned_start_date': (initiative.planned_start_date.isoformat()
                               if initiative.planned_start_date else None),
        'planned_end_date': (initiative.planned_end_date.isoformat()
                             if initiative.planned_end_date else None),
        'status': initiative.status,
        'priority': initiative.priority,
        'progress': initiative.progress,
        'points': initiative.points,
        'is_new': initiative.is_new,
        'external_ref': initiative.external_ref or '',
        'external_url': initiative.external_url,
        'owner_id': initiative.owner_id,
        'position': initiative.position,
        'is_overdue': initiative.is_overdue,
    }


def _dependency_payload(dep: RoadmapDependency) -> Dict[str, Any]:
    return {
        'id': dep.id,
        'predecessor_id': dep.predecessor_id,
        'successor_id': dep.successor_id,
        'lag': dep.lag,
    }


def bundle(roadmap_id: int) -> Optional[Dict[str, Any]]:
    """The whole roadmap as a JSON-ready dict, one query per table.

    Returns None when the roadmap does not exist. Text fields are returned raw —
    escaping is the renderer's job, and the Gantt escapes on insertion.
    """
    roadmap = db.session.get(Roadmap, roadmap_id)
    if not roadmap:
        return None

    periods = roadmap.periods.all()
    goals = roadmap.goals.all()

    goal_ids = [g.id for g in goals]
    initiatives = []
    if goal_ids:
        initiatives = (RoadmapInitiative.query
                       .filter(RoadmapInitiative.goal_id.in_(goal_ids))
                       .order_by(RoadmapInitiative.position, RoadmapInitiative.id)
                       .all())

    initiative_ids = [i.id for i in initiatives]
    dependencies = []
    if initiative_ids:
        dependencies = (RoadmapDependency.query
                        .filter(RoadmapDependency.predecessor_id.in_(initiative_ids),
                                RoadmapDependency.successor_id.in_(initiative_ids))
                        .all())

    return {
        'roadmap': {
            'id': roadmap.id,
            'name': roadmap.name,
            'description': roadmap.description or '',
            'status': roadmap.status,
            'owner_id': roadmap.owner_id,
            'progress': roadmap.progress,
            'steps_per_period': STEPS_PER_PERIOD,
        },
        'periods': [_period_payload(p) for p in periods],
        'goals': [_goal_payload(g) for g in goals],
        'initiatives': [_initiative_payload(i) for i in initiatives],
        'dependencies': [_dependency_payload(d) for d in dependencies],
    }
