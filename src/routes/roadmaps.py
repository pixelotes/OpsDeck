from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..models import db, User, Roadmap, RoadmapPeriod, ROADMAP_STATUSES
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..services.roadmaps_service import recompute_dates
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
        return redirect(url_for('roadmaps.edit_roadmap', id=roadmap.id))

    return render_template('roadmaps/form.html', **_form_context())


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
