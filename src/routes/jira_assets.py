"""Jira Assets sync: profiles, preview -> confirm, and run history (Settings module)."""
import logging
from collections import Counter

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from ..models import User, db
from ..models.connectors import ConnectorTask
from ..models.jira_assets import (
    DEFAULT_FIELDS, DEFAULT_STATUS_ATTRIBUTE, TARGET_ACTIONS, TARGET_LABELS, TARGETS,
    JiraAssetsProfile, JiraAssetsRun,
)
from ..services import jira_assets_service as svc
from ..services.jira_assets_client import JiraAssetsError
from ..services.permissions_service import requires_permission, requires_permission_api
from ..utils.json_api import json_endpoint
from ..utils.logger import log_audit
from .main import login_required

jira_assets_bp = Blueprint('jira_assets', __name__)
logger = logging.getLogger(__name__)

MODULE = 'settings'
HOME = 'jira_assets.index'
TEMPLATE_FORM = 'jira_assets/profile_form.html'
TEMPLATE_PLAN = 'jira_assets/plan.html'


def _current_email():
    user = db.session.get(User, session.get('user_id'))
    return user.email if user else None


def _connector_ready():
    task = ConnectorTask.query.filter_by(service='atlassian').first()
    return bool(task and task.auth_config)


@jira_assets_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def index():
    profiles = JiraAssetsProfile.query.order_by(JiraAssetsProfile.name).all()
    runs = JiraAssetsRun.query.order_by(JiraAssetsRun.started_at.desc()).limit(20).all()
    return render_template('jira_assets/index.html', profiles=profiles, runs=runs,
                           connector_ready=_connector_ready())


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #

def _form_context(profile, target):
    return {'profile': profile, 'target': target, 'targets': TARGETS, 'target_labels': TARGET_LABELS,
            'target_actions': TARGET_ACTIONS, 'default_fields': DEFAULT_FIELDS,
            'default_status_attribute': DEFAULT_STATUS_ATTRIBUTE}


def _parse_form(profile, form):
    """Validate the form into ``profile``. Returns a list of errors."""
    errors = []
    target = form.get('target')
    if profile.id is None:
        if target not in TARGETS:
            return ['Choose what the Jira objects become in OpsDeck.']
        profile.target = target
    name = (form.get('name') or '').strip()
    object_type = (form.get('object_type') or '').strip()
    if not name:
        errors.append('The profile needs a name.')
    if not object_type:
        errors.append('Enter the Jira object type (its id, e.g. 260, or its name, e.g. Laptop).')

    status_map, allowed = {}, TARGET_ACTIONS[profile.target]
    for value, action in zip(form.getlist('map_value'), form.getlist('map_action')):
        value = value.strip()
        if not value or not action:
            continue
        if action not in allowed:
            errors.append(f'"{action}" is not a valid state here.')
            continue
        status_map[value] = action
    if not status_map:
        errors.append('Map at least one Jira status value.')

    overrides = {}
    for key in DEFAULT_FIELDS[profile.target]:
        value = form.get(f'field_{key}')
        if value is None:
            continue
        value = value.strip()
        if value != DEFAULT_FIELDS[profile.target][key]:
            overrides[key] = value

    try:
        interval = int(form.get('interval_hours') or 0)
        threshold = int(form.get('archive_threshold_percent') or 10)
    except ValueError:
        return errors + ['Interval and threshold must be whole numbers.']
    if not 0 <= interval <= 168:
        errors.append('The interval must be between 0 (manual only) and 168 hours.')
    if not 0 <= threshold <= 100:
        errors.append('The safety threshold must be between 0 and 100%.')
    if errors:
        return errors

    profile.name = name[:120]
    profile.object_type = object_type[:120]
    profile.aql_filter = (form.get('aql_filter') or '').strip() or None
    profile.status_attribute = (form.get('status_attribute') or '').strip()[:120] \
        or DEFAULT_STATUS_ATTRIBUTE[profile.target]
    profile.status_map = status_map
    profile.field_overrides = overrides
    profile.create_missing = form.get('create_missing') == 'on'
    was_scheduled = profile.enabled and profile.interval_hours
    profile.enabled = form.get('enabled') == 'on'
    profile.interval_hours = interval
    profile.archive_threshold_percent = threshold
    if not (profile.enabled and interval):
        profile.next_run_at = None
    elif not was_scheduled or profile.next_run_at is None:
        svc.schedule_next(profile)
    return []


def _save(profile, is_new):
    errors = _parse_form(profile, request.form)
    if errors:
        db.session.rollback()
        for e in errors:
            flash(e, 'danger')
        target = profile.target or request.form.get('target')
        return render_template(TEMPLATE_FORM, **_form_context(profile if not is_new else None, target),
                               form=request.form), 400
    if is_new:
        db.session.add(profile)
    db.session.commit()
    log_audit(event_type='integration.jira_assets', action='create' if is_new else 'configure',
              target_object=f'JiraAssetsProfile:{profile.id}',
              target_info=(f'{profile.name}: {profile.target} from {profile.object_type}, '
                           f'enabled={profile.enabled}, every {profile.interval_hours}h'))
    flash(f'Profile "{profile.name}" saved.', 'success')
    return redirect(url_for(HOME))


@jira_assets_bp.route('/profiles/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def new_profile():
    if request.method == 'POST':
        return _save(JiraAssetsProfile(), is_new=True)
    target = request.args.get('target')
    if target not in TARGETS:
        target = None
    return render_template(TEMPLATE_FORM, **_form_context(None, target), form=None)


@jira_assets_bp.route('/profiles/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def edit_profile(id):
    profile = db.get_or_404(JiraAssetsProfile, id)
    if request.method == 'POST':
        return _save(profile, is_new=False)
    return render_template(TEMPLATE_FORM, **_form_context(profile, profile.target), form=None)


@jira_assets_bp.route('/profiles/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_profile(id):
    profile = db.get_or_404(JiraAssetsProfile, id)
    name = profile.name
    db.session.delete(profile)
    db.session.commit()
    log_audit(event_type='integration.jira_assets', action='delete',
              target_object=f'JiraAssetsProfile:{id}', target_info=name)
    flash(f'Profile "{name}" deleted. Records it imported keep their link to Jira.', 'success')
    return redirect(url_for(HOME))


@jira_assets_bp.route('/profiles/<int:id>/status-values', methods=['GET'])
@json_endpoint
@login_required
@requires_permission_api(MODULE, access_level='WRITE')
def status_values(id):
    """Distinct values of the profile's status attribute in Jira, with counts (JSON)."""
    profile = db.get_or_404(JiraAssetsProfile, id)
    attribute = request.args.get('attribute') or profile.status_attribute
    try:
        objects = svc.fetch(profile)
    except JiraAssetsError:
        # The details may include API responses: log them, answer with a fixed message.
        logger.exception('Loading Jira status values for profile %s failed', profile.id)
        return jsonify({'error': 'Jira Assets could not be queried. Check the Atlassian connector '
                                 'credentials and the object type; the server log has the details.'}), 502
    counts = Counter((o['attrs'].get(attribute) or ['(empty)'])[0] for o in objects)
    return jsonify({'attribute': attribute, 'total': len(objects),
                    'values': [{'value': v, 'count': c} for v, c in counts.most_common()]})


# --------------------------------------------------------------------------- #
# Preview -> apply, history
# --------------------------------------------------------------------------- #

@jira_assets_bp.route('/profiles/<int:id>/preview', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def preview(id):
    profile = db.get_or_404(JiraAssetsProfile, id)
    try:
        plan = svc.preview(profile)
    except (JiraAssetsError, svc.JiraAssetsSyncError) as exc:
        flash(f'Could not build the preview: {exc}', 'danger')
        return redirect(url_for(HOME))
    over_brake = False
    try:
        svc.check_archive_brake(plan, profile.archive_threshold_percent)
    except svc.SyncAborted:
        over_brake = True
    return render_template(TEMPLATE_PLAN, profile=profile, plan=plan, run=None, over_brake=over_brake)


@jira_assets_bp.route('/profiles/<int:id>/apply', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def apply(id):
    profile = db.get_or_404(JiraAssetsProfile, id)
    try:
        run = svc.run_sync(profile, 'manual', triggered_by=_current_email(),
                           expected_fingerprint=request.form.get('fingerprint') or None)
    except svc.JiraAssetsSyncError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for(HOME))
    if run.status == 'success':
        flash(f'"{profile.name}" applied: {run.created_count} created, {run.linked_count} linked, '
              f'{run.updated_count} updated, {run.archived_count} archived, '
              f'{run.unarchived_count} unarchived.', 'success')
    else:
        flash(f'"{profile.name}" {run.status}: {run.error}', 'danger')
    return redirect(url_for('jira_assets.view_run', id=run.id))


@jira_assets_bp.route('/runs/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def view_run(id):
    run = db.get_or_404(JiraAssetsRun, id)
    recorded = run.changes
    plan = {
        'changes': recorded['changes'], 'warnings': recorded['warnings'], 'fetched': run.fetched_count,
        'counts': {'create': run.created_count, 'link': run.linked_count, 'update': run.updated_count,
                   'archive': run.archived_count, 'unarchive': run.unarchived_count},
    }
    return render_template(TEMPLATE_PLAN, profile=run.profile, plan=plan, run=run, over_brake=False)
