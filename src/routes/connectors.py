"""Settings > API Connectors: configure, run and inspect the external-service syncs."""
import json
import re
from datetime import timedelta

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm.attributes import flag_modified

from ..extensions import db
from ..models.connectors import ConnectorReport, ConnectorSubtask, ConnectorTask
from ..services import connector_service
from ..services.permissions_service import requires_permission, requires_permission_api
from ..utils.json_api import json_endpoint
from ..utils.differ import get_semantic_diff
from ..utils.timezone_helper import now
from .main import login_required

connectors_bp = Blueprint('connectors', __name__)

MODULE = 'settings'
TASK_DETAIL = 'connectors.task_detail'


def _back_to(task_id):
    return redirect(url_for(TASK_DETAIL, task_id=task_id))


@connectors_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def dashboard():
    tasks = ConnectorTask.query.order_by(ConnectorTask.name).all()
    return render_template('connectors/dashboard.html', tasks=tasks)


@connectors_bp.route('/task/<int:task_id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def task_detail(task_id):
    task = db.get_or_404(ConnectorTask, task_id)
    return render_template('connectors/task_detail.html', task=task)


@connectors_bp.route('/task/<int:task_id>/run', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def run_task(task_id):
    """Run a task now, regardless of its schedule."""
    task = db.get_or_404(ConnectorTask, task_id)

    if not any(s.enabled for s in task.subtasks):
        flash(f'Task "{task.name}" has no enabled subtasks', 'warning')
        return _back_to(task_id)
    if not task.auth_config:
        flash(f'Configure the credentials of "{task.name}" before running it', 'danger')
        return _back_to(task_id)

    try:
        result = connector_service.execute_task(task)
    except Exception as e:
        current_app.logger.exception("Connector task %s failed", task.id)
        flash(f'Error running task: {e}', 'danger')
        return _back_to(task_id)

    if result['success']:
        changed = sum(1 for r in result['results'] if r.get('has_changes'))
        records = sum(r.get('record_count', 0) for r in result['results'])
        flash(f'Task "{task.name}" finished: {len(result["results"])} subtasks, '
              f'{records} records, {changed} with changes', 'success')
    else:
        flash(f'Task "{task.name}" finished with {len(result["errors"])} errors', 'warning')
        for error in result['errors']:
            flash(f'Error in {error["subtask_name"]}: {error["error"]}', 'danger')
    return _back_to(task_id)


@connectors_bp.route('/task/<int:task_id>/update', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def update_task(task_id):
    """Rename, enable/disable or change the polling interval of a task."""
    task = db.get_or_404(ConnectorTask, task_id)

    try:
        if 'name' in request.form and request.form['name'].strip():
            task.name = request.form['name'].strip()
        if 'enabled' in request.form:
            task.enabled = request.form['enabled'] == 'true'
        if 'polling_interval' in request.form:
            interval = int(request.form['polling_interval'])
            if interval < connector_service.MIN_POLLING_INTERVAL:
                flash('Minimum interval is 5 minutes (300 seconds)', 'warning')
                return _back_to(task_id)
            if interval > connector_service.MAX_POLLING_INTERVAL:
                flash('Maximum interval is 7 days (604800 seconds)', 'warning')
                return _back_to(task_id)
            task.polling_interval = interval

        if task.enabled and not task.next_run:
            task.next_run = now() + timedelta(seconds=task.polling_interval)

        db.session.commit()
    except ValueError:
        db.session.rollback()
        flash('The polling interval must be a number of seconds', 'danger')
        return _back_to(task_id)

    hours, minutes = task.polling_interval // 3600, (task.polling_interval % 3600) // 60
    interval_display = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    flash(f'Task "{task.name}" updated: interval={interval_display}, '
          f'status={"Active" if task.enabled else "Inactive"}', 'success')
    return _back_to(task_id)


def _form(name, default=''):
    return (request.form.get(name) or default).strip()


def _configure_google(task, cfg):
    service_account_json = _form('service_account_json')
    delegated_user = _form('delegated_user')
    if not delegated_user:
        return 'You must provide the delegated user email'
    if service_account_json:
        try:
            cfg['service_account_json'] = json.loads(service_account_json)
        except json.JSONDecodeError:
            return 'Invalid JSON format for service account'
    elif not cfg.get('service_account_json'):
        return 'You must provide both the Service Account JSON and the delegated user'
    cfg['delegated_user'] = delegated_user
    return None


def _configure_microsoft(task, cfg):
    tenant_id, client_id, client_secret = _form('tenant_id'), _form('client_id'), _form('client_secret')
    if not tenant_id or not client_id:
        return 'Tenant ID and Client ID are required'
    if not client_secret and 'client_secret' not in cfg:
        return 'Client Secret is required for the initial configuration'
    cfg['tenant_id'], cfg['client_id'] = tenant_id, client_id
    if client_secret:
        cfg['client_secret'] = client_secret
    return None


def _configure_atlassian(task, cfg):
    site_url, email, api_token = _form('site_url'), _form('email'), _form('api_token')
    if not site_url or not email or (not api_token and 'api_token' not in cfg):
        return 'You must provide Site URL, Email and API Token'
    cfg['site_url'], cfg['email'] = site_url, email
    if api_token:
        cfg['api_token'] = api_token
    return None


def _configure_github(task, cfg):
    access_token, organization = _form('access_token'), _form('organization')
    if not access_token and 'access_token' not in cfg:
        return 'You must provide a Personal Access Token'
    if not organization:
        return 'You must provide your organization name'
    if access_token:
        cfg['access_token'] = access_token
    cfg['organization'] = organization
    # Endpoints are seeded with a YOUR_ORG placeholder; point them at the organization.
    for subtask in task.subtasks:
        if 'YOUR_ORG' in subtask.endpoint:
            subtask.endpoint = subtask.endpoint.replace('YOUR_ORG', organization)
        elif '/orgs/' in subtask.endpoint:
            subtask.endpoint = re.sub(r'/orgs/[^/]+/', f'/orgs/{organization}/', subtask.endpoint)
    return None


def _configure_jumpcloud(task, cfg):
    api_key, org_id = _form('api_key'), _form('org_id')
    if not api_key and 'api_key' not in cfg:
        return 'You must provide a valid API Key'
    if api_key:
        cfg['api_key'] = api_key
    if org_id:
        cfg['org_id'] = org_id
    else:
        cfg.pop('org_id', None)
    return None


def _configure_aws(task, cfg):
    access_key, secret_key = _form('aws_access_key'), _form('aws_secret_key')
    region = _form('aws_region', 'us-east-1')
    if not access_key:
        return 'Access Key ID is required'
    if not region:
        return 'Region is required'
    if not secret_key and 'aws_secret_key' not in cfg:
        return 'Secret Access Key is required for the initial configuration'
    cfg['aws_access_key'], cfg['aws_region'] = access_key, region
    if secret_key:
        cfg['aws_secret_key'] = secret_key
    return None


CREDENTIAL_HANDLERS = {
    'google': _configure_google,
    'microsoft': _configure_microsoft,
    'atlassian': _configure_atlassian,
    'github': _configure_github,
    'jumpcloud': _configure_jumpcloud,
    'aws': _configure_aws,
}


@connectors_bp.route('/task/<int:task_id>/configure-credentials', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def configure_credentials(task_id):
    """Store the credentials of a task. Blank secret fields keep the stored secret."""
    task = db.get_or_404(ConnectorTask, task_id)
    handler = CREDENTIAL_HANDLERS.get(task.service)
    if handler is None:
        flash(f'Service "{task.service}" is not supported', 'warning')
        return _back_to(task_id)

    cfg = dict(task.auth_config or {})
    error = handler(task, cfg)
    if error:
        db.session.rollback()
        flash(error, 'warning')
        return _back_to(task_id)

    task.auth_config = cfg
    flag_modified(task, 'auth_config')
    db.session.commit()
    flash(f'{task.service_label} credentials saved', 'success')
    return _back_to(task_id)


@connectors_bp.route('/subtask/<int:subtask_id>/reports', methods=['GET'])
@login_required
@requires_permission(MODULE)
def subtask_reports(subtask_id):
    """All reports of a subtask, with diffs between them."""
    subtask = db.get_or_404(ConnectorSubtask, subtask_id)
    page = request.args.get('page', 1, type=int)
    per_page = max(10, min(100, request.args.get('per_page', 20, type=int)))
    pagination = (ConnectorReport.query.filter_by(subtask_id=subtask_id)
                  .order_by(ConnectorReport.created_at.desc())
                  .paginate(page=page, per_page=per_page, error_out=False))
    return render_template('connectors/reports.html', subtask=subtask,
                           reports=pagination.items, pagination=pagination)


@connectors_bp.route('/report/<int:report_id>/fullscreen', methods=['GET'])
@login_required
@requires_permission(MODULE)
def report_fullscreen(report_id):
    report = db.get_or_404(ConnectorReport, report_id)
    view_type = 'json' if request.args.get('view') == 'json' else 'table'
    return render_template('connectors/fullscreen_report.html', report=report,
                           report_data=json.loads(report.data), view_type=view_type)


@connectors_bp.route('/api/diff/<int:subtask_id>', methods=['GET'])
@json_endpoint
@login_required
@requires_permission_api(MODULE)
def get_diff(subtask_id):
    """Diff two reports of a subtask.

    ?report=<id> compares that report with the one fetched just before it;
    ?report1=<older>&report2=<newer> compares two given reports; with neither,
    the two most recent reports are compared.
    """
    of_subtask = ConnectorReport.query.filter_by(subtask_id=subtask_id)
    report_id = request.args.get('report', type=int)
    report_id_1 = request.args.get('report1', type=int)
    report_id_2 = request.args.get('report2', type=int)

    if report_id:
        newer = db.get_or_404(ConnectorReport, report_id)
        if newer.subtask_id != subtask_id:
            return jsonify({'error': 'Report does not belong to this subtask'}), 400
        older = (of_subtask.filter(ConnectorReport.id < newer.id)
                 .order_by(ConnectorReport.id.desc()).first())
        reports = [newer, older] if older else [newer]
    elif report_id_1 and report_id_2:
        older = db.get_or_404(ConnectorReport, report_id_1)
        newer = db.get_or_404(ConnectorReport, report_id_2)
        if older.subtask_id != subtask_id or newer.subtask_id != subtask_id:
            return jsonify({'error': 'Reports do not belong to this subtask'}), 400
        reports = [newer, older]
    else:
        reports = of_subtask.order_by(ConnectorReport.id.desc()).limit(2).all()

    if len(reports) < 2:
        return jsonify({'error': 'Not enough reports to compare'}), 404

    diff = get_semantic_diff(json.loads(reports[1].data), json.loads(reports[0].data))
    return jsonify({
        'subtask_id': subtask_id,
        'report_new_id': reports[0].id,
        'report_new_date': reports[0].created_at.isoformat(),
        'report_old_id': reports[1].id,
        'report_old_date': reports[1].created_at.isoformat(),
        'diff': diff,
        'has_changes': bool(diff.get('added') or diff.get('removed') or diff.get('changed')),
    })


@connectors_bp.route('/api/report/<int:report_id>', methods=['GET'])
@json_endpoint
@login_required
@requires_permission_api(MODULE)
def get_report(report_id):
    report = db.get_or_404(ConnectorReport, report_id)
    return jsonify({
        'id': report.id,
        'subtask_id': report.subtask_id,
        'created_at': report.created_at.isoformat(),
        'record_count': report.record_count,
        'fetch_duration_ms': report.fetch_duration_ms,
        'checksum': report.checksum,
        'data': report.data,
    })
