import re
from datetime import datetime
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for, flash,
                   jsonify, current_app)
from werkzeug.exceptions import BadRequest

from ..models import (db, User, Roadmap, RoadmapPeriod, RoadmapGoal, RoadmapInitiative,
                      RoadmapDependency, ROADMAP_STATUSES, INITIATIVE_STATUSES,
                      INITIATIVE_PRIORITIES, DEFAULT_GOAL_COLOR, STEPS_PER_PERIOD)
from .main import login_required
from ..services.permissions_service import (requires_permission, requires_permission_api,
                                            has_write_permission)
from ..services.roadmaps_service import (recompute_dates, creates_cycle, cascade_reschedule,
                                         sync_dependency_lags, bundle)
from src.utils.logger import log_audit

roadmaps_bp = Blueprint('roadmaps', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'roadmaps'
LIST_VIEW = 'roadmaps.list_roadmaps'
WRITE_REQUIRED = 'Write access required to modify roadmaps.'


def _parse_date(value):
    """Parse a YYYY-MM-DD form value, returning None for blanks or garbage."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_period_rows():
    """Read the repeated period rows off the form.

    Returns ``(rows, error)``. Everything is validated before anything is written so a
    bad row cannot leave the roadmap half-updated. Rows with a blank label are dropped,
    which is how the form signals "ignore this row".
    """
    ids = request.form.getlist('period_id')
    labels = request.form.getlist('period_label')
    starts = request.form.getlist('period_start')
    ends = request.form.getlist('period_end')

    rows = []
    for raw_id, label, raw_start, raw_end in zip(ids, labels, starts, ends):
        label = (label or '').strip()
        if not label:
            continue

        start, end = _parse_date(raw_start), _parse_date(raw_end)
        if start and end and end < start:
            return None, f'Period "{label}" ends before it starts.'

        period_id = None
        if raw_id:
            try:
                period_id = int(raw_id)
            except ValueError:
                return None, 'Malformed period reference.'

        rows.append({'id': period_id, 'label': label, 'start': start, 'end': end})

    return rows, None


def _sync_periods(roadmap, rows):
    """Apply parsed period rows: update, create and drop to match what was submitted.

    Existing periods are looked up scoped to this roadmap, so an id belonging to another
    roadmap cannot be hijacked through the form.
    """
    kept = set()
    for position, row in enumerate(rows):
        period = None
        if row['id']:
            period = RoadmapPeriod.query.filter_by(id=row['id'], roadmap_id=roadmap.id).first()
        if period is None:
            period = RoadmapPeriod(roadmap_id=roadmap.id)
            db.session.add(period)

        period.label = row['label']
        period.start_date = row['start']
        period.end_date = row['end']
        period.position = position
        db.session.flush()
        kept.add(period.id)

    for period in roadmap.periods.all():
        if period.id not in kept:
            db.session.delete(period)


def _apply_header(roadmap):
    """Copy the header fields off the form onto the roadmap."""
    roadmap.name = request.form['name'].strip()
    roadmap.description = request.form.get('description', '').strip()

    status = request.form.get('status', 'draft')
    roadmap.status = status if status in ROADMAP_STATUSES else 'draft'

    owner_id = request.form.get('owner_id')
    roadmap.owner_id = int(owner_id) if owner_id else None


def _form_context(roadmap=None):
    return {
        'roadmap': roadmap,
        'users': User.query.filter_by(is_archived=False).order_by(User.name).all(),
        'statuses': ROADMAP_STATUSES,
    }


@roadmaps_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_roadmaps():
    """Lists roadmaps, optionally filtered by status."""
    query = Roadmap.query

    status = request.args.get('status')
    if status:
        query = query.filter(Roadmap.status == status)

    roadmaps = query.order_by(Roadmap.name).all()
    return render_template('roadmaps/list.html', roadmaps=roadmaps,
                           statuses=ROADMAP_STATUSES, current_status=status)


@roadmaps_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_roadmap():
    """Creates a roadmap along with its periods."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash(WRITE_REQUIRED, 'danger')
            return redirect(url_for(LIST_VIEW))

        if not request.form.get('name', '').strip():
            flash('Name is required.', 'danger')
            return redirect(url_for('roadmaps.new_roadmap'))

        rows, error = _parse_period_rows()
        if error:
            flash(error, 'danger')
            return redirect(url_for('roadmaps.new_roadmap'))

        roadmap = Roadmap()
        _apply_header(roadmap)
        db.session.add(roadmap)
        db.session.flush()

        _sync_periods(roadmap, rows)
        db.session.commit()

        log_audit('roadmap.created', 'create', target_object=f'Roadmap:{roadmap.id}')
        flash('Roadmap created successfully.', 'success')
        # Straight to the Gantt: the next step is adding goals, which happens there.
        return redirect(url_for('roadmaps.detail', id=roadmap.id))

    return render_template('roadmaps/form.html', **_form_context())


@roadmaps_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def detail(id):
    """The interactive Gantt view. Goals and initiatives are managed from here."""
    roadmap = db.get_or_404(Roadmap, id)

    # Derived from url_for rather than hardcoded, so it survives a change of prefix.
    api_base = url_for('roadmaps.api_data', roadmap_id=roadmap.id)[:-len('/data')]

    return render_template('roadmaps/detail.html', roadmap=roadmap, api_base=api_base,
                           steps_per_period=STEPS_PER_PERIOD,
                           default_goal_color=DEFAULT_GOAL_COLOR)


@roadmaps_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_roadmap(id):
    """Edits a roadmap's header and periods."""
    roadmap = db.get_or_404(Roadmap, id)

    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash(WRITE_REQUIRED, 'danger')
            return redirect(url_for('roadmaps.edit_roadmap', id=id))

        if not request.form.get('name', '').strip():
            flash('Name is required.', 'danger')
            return redirect(url_for('roadmaps.edit_roadmap', id=id))

        rows, error = _parse_period_rows()
        if error:
            flash(error, 'danger')
            return redirect(url_for('roadmaps.edit_roadmap', id=id))

        _apply_header(roadmap)
        _sync_periods(roadmap, rows)

        # Period dates define the step→date mapping, so planned dates must follow.
        recompute_dates(roadmap)
        db.session.commit()

        log_audit('roadmap.updated', 'update', target_object=f'Roadmap:{roadmap.id}')
        flash('Roadmap updated successfully.', 'success')
        return redirect(url_for('roadmaps.edit_roadmap', id=roadmap.id))

    return render_template('roadmaps/form.html', **_form_context(roadmap))


@roadmaps_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_roadmap(id):
    """Deletes a roadmap and everything under it."""
    roadmap = db.get_or_404(Roadmap, id)

    if not has_write_permission(MODULE):
        flash(WRITE_REQUIRED, 'danger')
        return redirect(url_for(LIST_VIEW))

    name = roadmap.name
    db.session.delete(roadmap)
    db.session.commit()

    log_audit('roadmap.deleted', 'delete', target_object=f'Roadmap:{id}')
    flash(f'Roadmap "{name}" deleted.', 'success')
    return redirect(url_for(LIST_VIEW))


# ---------------------------------------------------------------------------
# JSON API consumed by the Gantt view
#
# Every route is nested under its roadmap (/<roadmap_id>/api/...) so that each
# child object can be looked up scoped to it. Without the roadmap in the path
# there is nothing to check ownership against, and an id from another roadmap
# would be editable by anyone holding write access to any roadmap.
# ---------------------------------------------------------------------------

HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')

CYCLE_ERROR = 'That link would create a dependency cycle.'
NOT_IN_ROADMAP = 'Not found in this roadmap.'


def _json_error(message, status):
    return jsonify({'error': message}), status


def api_endpoint(f):
    """Make a handler fail as JSON instead of as an HTML error page.

    ValueError/TypeError are treated as client errors because the only place they
    can surface here is coercing request data (int('abc') and friends); anything
    else is a bug, so it rolls back, logs with a stack trace, and returns 500.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except BadRequest:
            return _json_error('Malformed request body.', 400)
        except (ValueError, TypeError):
            return _json_error('Invalid field value.', 400)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Unhandled error in the roadmaps API')
            return _json_error('Internal error.', 500)
    return wrapper


def _body():
    """The parsed JSON body, or an empty dict when there is none.

    A body that is present but unparseable is an error rather than an empty dict:
    treating garbage as "no fields supplied" would make a broken client look like a
    successful no-op. A missing body stays valid, since DELETE and some POSTs have none.
    """
    parsed = request.get_json(silent=True)
    if parsed is None:
        if request.get_data():
            raise BadRequest('Body is not valid JSON.')
        return {}
    if not isinstance(parsed, dict):
        raise BadRequest('Body must be a JSON object.')
    return parsed


def _as_int(value, default=None):
    """Coerce a JSON value to int, mapping blanks to `default`."""
    if value is None or value == '':
        return default
    return int(value)


def _clean_text(value, limit):
    return (value or '').strip()[:limit]


def _scoped_period(roadmap_id, period_id):
    return RoadmapPeriod.query.filter_by(id=period_id, roadmap_id=roadmap_id).first()


def _scoped_goal(roadmap_id, goal_id):
    return RoadmapGoal.query.filter_by(id=goal_id, roadmap_id=roadmap_id).first()


def _scoped_initiative(roadmap_id, initiative_id):
    return (RoadmapInitiative.query
            .join(RoadmapGoal, RoadmapInitiative.goal_id == RoadmapGoal.id)
            .filter(RoadmapInitiative.id == initiative_id,
                    RoadmapGoal.roadmap_id == roadmap_id)
            .first())


def _scoped_dependency(roadmap_id, dependency_id):
    """A dependency belongs to a roadmap when its predecessor does."""
    dep = db.session.get(RoadmapDependency, dependency_id)
    if dep and _scoped_initiative(roadmap_id, dep.predecessor_id):
        return dep
    return None


def _validate_steps(start, end):
    if start < 1:
        return 'start_step must be 1 or greater.'
    if end < start:
        return 'end_step cannot be before start_step.'
    return None


def _validate_owner(owner_id):
    if owner_id is not None and db.session.get(User, owner_id) is None:
        return 'Unknown owner.'
    return None


def _apply_period_fields(period, body):
    """Apply the editable subset of `body`. Returns an error string, or None.

    Only keys present in the body are touched, so this serves create and partial
    update alike.
    """
    if 'label' in body:
        label = _clean_text(body['label'], 50)
        if not label:
            return 'Period label is required.'
        period.label = label

    start, end = period.start_date, period.end_date
    if 'start_date' in body:
        start = _parse_date(body['start_date'])
    if 'end_date' in body:
        end = _parse_date(body['end_date'])
    if start and end and end < start:
        return 'A period cannot end before it starts.'
    period.start_date, period.end_date = start, end

    if 'position' in body:
        period.position = _as_int(body['position'], period.position)
    return None


def _apply_goal_fields(goal, body):
    """Apply the editable subset of `body`. Returns an error string, or None."""
    if 'name' in body:
        name = _clean_text(body['name'], 255)
        if not name:
            return 'Goal name is required.'
        goal.name = name

    if 'description' in body:
        goal.description = (body['description'] or '').strip()

    if 'color' in body:
        color = _clean_text(body['color'], 7)
        if not HEX_COLOR.match(color):
            return 'Colour must be a hex value like #2E5F9E.'
        goal.color = color

    if 'owner_id' in body:
        owner_id = _as_int(body['owner_id'])
        error = _validate_owner(owner_id)
        if error:
            return error
        goal.owner_id = owner_id

    if 'position' in body:
        goal.position = _as_int(body['position'], goal.position)
    return None


def _apply_initiative_fields(initiative, body):
    """Apply the editable subset of `body`. Returns an error string, or None.

    planned_start_date / planned_end_date are deliberately absent: they are derived
    from the steps and are only ever written by the service layer.
    """
    if 'name' in body:
        name = _clean_text(body['name'], 255)
        if not name:
            return 'Initiative name is required.'
        initiative.name = name

    if 'description' in body:
        initiative.description = (body['description'] or '').strip()

    if 'status' in body:
        if body['status'] not in INITIATIVE_STATUSES:
            return f"Status must be one of: {', '.join(INITIATIVE_STATUSES)}."
        initiative.status = body['status']

    if 'priority' in body:
        if body['priority'] not in INITIATIVE_PRIORITIES:
            return f"Priority must be one of: {', '.join(INITIATIVE_PRIORITIES)}."
        initiative.priority = body['priority']

    if 'progress' in body:
        initiative.progress = max(0, min(100, _as_int(body['progress'], 0)))

    if 'points' in body:
        points = _as_int(body['points'])
        if points is not None and points < 0:
            return 'Points cannot be negative.'
        initiative.points = points

    if 'is_new' in body:
        initiative.is_new = bool(body['is_new'])

    if 'external_ref' in body:
        initiative.external_ref = _clean_text(body['external_ref'], 100)

    if 'external_url' in body:
        initiative.external_url = _clean_text(body['external_url'], 500) or None

    if 'owner_id' in body:
        owner_id = _as_int(body['owner_id'])
        error = _validate_owner(owner_id)
        if error:
            return error
        initiative.owner_id = owner_id

    if 'position' in body:
        initiative.position = _as_int(body['position'], initiative.position)

    # Steps last, so they are validated as a pair against the final values.
    start = _as_int(body.get('start_step'), initiative.start_step)
    end = _as_int(body.get('end_step'), initiative.end_step)
    error = _validate_steps(start, end)
    if error:
        return error
    initiative.start_step, initiative.end_step = start, end
    return None


def _next_position(model, **filters):
    rows = model.query.filter_by(**filters).all()
    return max((row.position for row in rows), default=-1) + 1


# --- read --------------------------------------------------------------------

@roadmaps_bp.route('/<int:roadmap_id>/api/data', methods=['GET'])
@requires_permission_api(MODULE)
@api_endpoint
def api_data(roadmap_id):
    """The whole roadmap, as the Gantt view needs it."""
    payload = bundle(roadmap_id)
    if payload is None:
        return _json_error('Roadmap not found.', 404)
    return jsonify(payload)


# --- periods -----------------------------------------------------------------

@roadmaps_bp.route('/<int:roadmap_id>/api/periods', methods=['POST'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_create_period(roadmap_id):
    roadmap = db.session.get(Roadmap, roadmap_id)
    if not roadmap:
        return _json_error('Roadmap not found.', 404)

    period = RoadmapPeriod(roadmap_id=roadmap_id,
                           position=_next_position(RoadmapPeriod, roadmap_id=roadmap_id))
    error = _apply_period_fields(period, _body())
    if error:
        return _json_error(error, 400)

    db.session.add(period)
    db.session.flush()
    recompute_dates(roadmap)
    db.session.commit()

    log_audit('roadmap.period_created', 'create', target_object=f'RoadmapPeriod:{period.id}')
    return jsonify({'id': period.id}), 201


@roadmaps_bp.route('/<int:roadmap_id>/api/periods/<int:period_id>', methods=['PATCH'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_update_period(roadmap_id, period_id):
    period = _scoped_period(roadmap_id, period_id)
    if not period:
        return _json_error(NOT_IN_ROADMAP, 404)

    error = _apply_period_fields(period, _body())
    if error:
        return _json_error(error, 400)

    # Period dates define the step→date mapping, so planned dates must follow.
    recompute_dates(period.roadmap)
    db.session.commit()

    log_audit('roadmap.period_updated', 'update', target_object=f'RoadmapPeriod:{period_id}')
    return jsonify({'ok': True})


@roadmaps_bp.route('/<int:roadmap_id>/api/periods/<int:period_id>', methods=['DELETE'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_delete_period(roadmap_id, period_id):
    period = _scoped_period(roadmap_id, period_id)
    if not period:
        return _json_error(NOT_IN_ROADMAP, 404)

    roadmap = period.roadmap
    db.session.delete(period)
    db.session.flush()
    recompute_dates(roadmap)
    db.session.commit()

    log_audit('roadmap.period_deleted', 'delete', target_object=f'RoadmapPeriod:{period_id}')
    return jsonify({'ok': True})


# --- goals -------------------------------------------------------------------

@roadmaps_bp.route('/<int:roadmap_id>/api/goals', methods=['POST'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_create_goal(roadmap_id):
    if not db.session.get(Roadmap, roadmap_id):
        return _json_error('Roadmap not found.', 404)

    goal = RoadmapGoal(roadmap_id=roadmap_id, color=DEFAULT_GOAL_COLOR,
                       position=_next_position(RoadmapGoal, roadmap_id=roadmap_id))
    error = _apply_goal_fields(goal, _body())
    if error:
        return _json_error(error, 400)

    db.session.add(goal)
    db.session.commit()

    log_audit('roadmap.goal_created', 'create', target_object=f'RoadmapGoal:{goal.id}')
    return jsonify({'id': goal.id}), 201


@roadmaps_bp.route('/<int:roadmap_id>/api/goals/<int:goal_id>', methods=['PATCH'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_update_goal(roadmap_id, goal_id):
    goal = _scoped_goal(roadmap_id, goal_id)
    if not goal:
        return _json_error(NOT_IN_ROADMAP, 404)

    error = _apply_goal_fields(goal, _body())
    if error:
        return _json_error(error, 400)

    db.session.commit()
    log_audit('roadmap.goal_updated', 'update', target_object=f'RoadmapGoal:{goal_id}')
    return jsonify({'ok': True})


@roadmaps_bp.route('/<int:roadmap_id>/api/goals/<int:goal_id>', methods=['DELETE'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_delete_goal(roadmap_id, goal_id):
    goal = _scoped_goal(roadmap_id, goal_id)
    if not goal:
        return _json_error(NOT_IN_ROADMAP, 404)

    db.session.delete(goal)
    db.session.commit()

    log_audit('roadmap.goal_deleted', 'delete', target_object=f'RoadmapGoal:{goal_id}')
    return jsonify({'ok': True})


# --- initiatives -------------------------------------------------------------

@roadmaps_bp.route('/<int:roadmap_id>/api/initiatives', methods=['POST'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_create_initiative(roadmap_id):
    body = _body()

    goal = _scoped_goal(roadmap_id, _as_int(body.get('goal_id')))
    if not goal:
        return _json_error('Goal not found in this roadmap.', 404)

    initiative = RoadmapInitiative(goal_id=goal.id, name='', start_step=1,
                                   end_step=STEPS_PER_PERIOD,
                                   position=_next_position(RoadmapInitiative, goal_id=goal.id))
    error = _apply_initiative_fields(initiative, body)
    if error:
        return _json_error(error, 400)
    if not initiative.name:
        return _json_error('Initiative name is required.', 400)

    db.session.add(initiative)
    db.session.flush()
    recompute_dates(goal.roadmap)
    db.session.commit()

    log_audit('roadmap.initiative_created', 'create',
              target_object=f'RoadmapInitiative:{initiative.id}')
    return jsonify({'id': initiative.id}), 201


@roadmaps_bp.route('/<int:roadmap_id>/api/initiatives/<int:initiative_id>', methods=['PATCH'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_update_initiative(roadmap_id, initiative_id):
    initiative = _scoped_initiative(roadmap_id, initiative_id)
    if not initiative:
        return _json_error(NOT_IN_ROADMAP, 404)

    body = _body()

    # Moving between goals is a reparent, so the target goal needs checking too.
    if 'goal_id' in body:
        goal = _scoped_goal(roadmap_id, _as_int(body['goal_id']))
        if not goal:
            return _json_error('Goal not found in this roadmap.', 404)
        initiative.goal_id = goal.id

    moved = 'start_step' in body or 'end_step' in body
    error = _apply_initiative_fields(initiative, body)
    if error:
        return _json_error(error, 400)

    if moved:
        # The drag defines the intended gap to each predecessor, then dependents
        # follow. cascade_reschedule refreshes the planned dates on its way out.
        sync_dependency_lags(initiative.id)
        cascade_reschedule(initiative.id)

    db.session.commit()

    log_audit('roadmap.initiative_updated', 'update',
              target_object=f'RoadmapInitiative:{initiative_id}')
    return jsonify({'ok': True})


@roadmaps_bp.route('/<int:roadmap_id>/api/initiatives/<int:initiative_id>', methods=['DELETE'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_delete_initiative(roadmap_id, initiative_id):
    initiative = _scoped_initiative(roadmap_id, initiative_id)
    if not initiative:
        return _json_error(NOT_IN_ROADMAP, 404)

    db.session.delete(initiative)
    db.session.commit()

    log_audit('roadmap.initiative_deleted', 'delete',
              target_object=f'RoadmapInitiative:{initiative_id}')
    return jsonify({'ok': True})


@roadmaps_bp.route('/<int:roadmap_id>/api/initiatives/reorder', methods=['POST'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_reorder_initiatives(roadmap_id):
    """Bulk reposition, and optionally reparent, after a drag of the label column."""
    items = _body().get('items') or []

    for item in items:
        initiative = _scoped_initiative(roadmap_id, _as_int(item.get('id')))
        if not initiative:
            return _json_error(NOT_IN_ROADMAP, 404)

        goal_id = _as_int(item.get('goal_id'), initiative.goal_id)
        if not _scoped_goal(roadmap_id, goal_id):
            return _json_error('Goal not found in this roadmap.', 404)

        initiative.goal_id = goal_id
        initiative.position = _as_int(item.get('position'), initiative.position)

    db.session.commit()
    log_audit('roadmap.initiatives_reordered', 'update', target_object=f'Roadmap:{roadmap_id}')
    return jsonify({'ok': True, 'count': len(items)})


# --- dependencies ------------------------------------------------------------

@roadmaps_bp.route('/<int:roadmap_id>/api/dependencies', methods=['POST'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_create_dependency(roadmap_id):
    body = _body()

    predecessor = _scoped_initiative(roadmap_id, _as_int(body.get('predecessor_id')))
    successor = _scoped_initiative(roadmap_id, _as_int(body.get('successor_id')))
    if not predecessor or not successor:
        return _json_error('Initiative not found in this roadmap.', 404)

    if creates_cycle(predecessor.id, successor.id):
        return _json_error(CYCLE_ERROR, 400)

    if RoadmapDependency.query.filter_by(predecessor_id=predecessor.id,
                                         successor_id=successor.id).first():
        return _json_error('That dependency already exists.', 409)

    # Default the lag to the gap the user already drew on screen, so creating a link
    # does not jump the successor somewhere unexpected.
    lag = _as_int(body.get('lag'), successor.start_step - predecessor.end_step)
    dependency = RoadmapDependency(predecessor_id=predecessor.id,
                                   successor_id=successor.id, lag=lag)
    db.session.add(dependency)
    db.session.flush()
    cascade_reschedule(predecessor.id)
    db.session.commit()

    log_audit('roadmap.dependency_created', 'create',
              target_object=f'RoadmapDependency:{dependency.id}')
    return jsonify({'id': dependency.id, 'lag': lag}), 201


@roadmaps_bp.route('/<int:roadmap_id>/api/dependencies/<int:dependency_id>', methods=['DELETE'])
@requires_permission_api(MODULE, 'WRITE')
@api_endpoint
def api_delete_dependency(roadmap_id, dependency_id):
    dependency = _scoped_dependency(roadmap_id, dependency_id)
    if not dependency:
        return _json_error(NOT_IN_ROADMAP, 404)

    db.session.delete(dependency)
    db.session.commit()

    log_audit('roadmap.dependency_deleted', 'delete',
              target_object=f'RoadmapDependency:{dependency_id}')
    return jsonify({'ok': True})
