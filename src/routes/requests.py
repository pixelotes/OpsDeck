from flask import Blueprint, render_template, request, flash, redirect, url_for, session, current_app
from ..extensions import db
from ..models import (Request, User, BusinessService, Asset, Software, Tag, Attachment)
from ..services.permissions_service import requires_permission, has_write_permission
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from src.utils.timezone_helper import now


requests_bp = Blueprint('requests', __name__)


def _form_context(req=None):
    """Common context for the create/edit form (active records only)."""
    return dict(
        users=User.query.filter_by(is_archived=False).all(),
        services=BusinessService.query.filter(BusinessService.status != 'Retired').all(),
        assets=Asset.query.filter_by(is_archived=False).all(),
        software=Software.query.filter_by(is_archived=False).all(),
        tags=Tag.query.filter_by(is_archived=False).all(),
        req=req,
    )


@requests_bp.route('/', methods=['GET'])
@requires_permission('operations')
def list_requests():
    """List all requests with filtering."""
    status = request.args.get('status')
    request_type = request.args.get('type')
    priority = request.args.get('priority')

    query = Request.query

    if status:
        query = query.filter(Request.status == status)
    if request_type:
        query = query.filter(Request.request_type == request_type)
    if priority:
        query = query.filter(Request.priority == priority)

    requests = query.order_by(Request.created_at.desc()).all()

    return render_template('requests/list.html', requests=requests)


@requests_bp.route('/new', methods=['GET', 'POST'])
@requires_permission('operations')
def new_request():
    """Create a new service request."""
    if request.method == 'POST':
        if not has_write_permission('operations'):
            flash('Write access required to create requests.', 'danger')
            return redirect(url_for('requests.list_requests'))
        user_id = session.get('user_id')
        if not user_id:
            flash('You must be logged in to create a request.', 'danger')
            return redirect(url_for('main.login'))

        req = Request(
            title=request.form.get('title'),
            request_type=request.form.get('request_type'),
            priority=request.form.get('priority'),
            status='Pending',  # Initial status
            description=request.form.get('description'),
            justification=request.form.get('justification'),
            requester_id=user_id,
            assignee_id=request.form.get('assignee_id') or None,
        )

        # Due date (optional)
        due = request.form.get('due_date')
        if due:
            req.due_date = datetime.strptime(due, '%Y-%m-%dT%H:%M')

        # Handle Target
        target_type = request.form.get('target_type')
        if target_type == 'service':
            req.service_id = request.form.get('service_id') or None
        elif target_type == 'asset':
            req.asset_id = request.form.get('asset_id') or None
        elif target_type == 'software':
            req.software_id = request.form.get('software_id') or None

        # Handle Tags
        for tag_id in request.form.getlist('tag_ids'):
            tag = db.session.get(Tag, tag_id)
            if tag:
                req.tags.append(tag)

        db.session.add(req)
        db.session.commit()

        flash('Request created successfully.', 'success')
        return redirect(url_for('requests.detail_request', id=req.id))

    return render_template('requests/form.html', today=now(), **_form_context())


@requests_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission('operations')
def edit_request(id):
    """Edit an existing request."""
    req = db.get_or_404(Request, id)

    if req.status in ['Completed', 'Closed', 'Cancelled']:
        flash('Cannot edit a closed request.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))

    if request.method == 'POST':
        if not has_write_permission('operations'):
            flash('Write access required to update requests.', 'danger')
            return redirect(url_for('requests.detail_request', id=id))

        req.title = request.form.get('title')
        req.request_type = request.form.get('request_type')
        req.priority = request.form.get('priority')
        req.description = request.form.get('description')
        req.justification = request.form.get('justification')
        req.resolution_notes = request.form.get('resolution_notes')
        req.assignee_id = request.form.get('assignee_id') or None

        due = request.form.get('due_date')
        req.due_date = datetime.strptime(due, '%Y-%m-%dT%H:%M') if due else None

        # Handle Target (reset others)
        target_type = request.form.get('target_type')
        req.service_id = None
        req.asset_id = None
        req.software_id = None
        if target_type == 'service':
            req.service_id = request.form.get('service_id') or None
        elif target_type == 'asset':
            req.asset_id = request.form.get('asset_id') or None
        elif target_type == 'software':
            req.software_id = request.form.get('software_id') or None

        # Handle Tags
        req.tags = []
        for tag_id in request.form.getlist('tag_ids'):
            tag = db.session.get(Tag, tag_id)
            if tag:
                req.tags.append(tag)

        db.session.commit()
        flash('Request updated successfully.', 'success')
        return redirect(url_for('requests.detail_request', id=req.id))

    return render_template('requests/form.html', **_form_context(req))


@requests_bp.route('/<int:id>')
@requires_permission('operations')
def detail_request(id):
    req = db.get_or_404(Request, id)
    return render_template('requests/detail.html', req=req)


@requests_bp.route('/<int:id>/triage', methods=['POST'])
@requires_permission('operations')
def triage_request(id):
    if not has_write_permission('operations'):
        flash('Write access required to triage requests.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)
    if req.status != 'Pending':
        flash('Only pending requests can be sent to triage.', 'warning')
        return redirect(url_for('requests.detail_request', id=id))

    req.status = 'Triage'
    req.triaged_at = now()
    req.triaged_by_id = session.get('user_id')
    db.session.commit()

    flash('Request moved to triage.', 'info')
    return redirect(url_for('requests.detail_request', id=id))


@requests_bp.route('/<int:id>/start', methods=['POST'])
@requires_permission('operations')
def start_request(id):
    if not has_write_permission('operations'):
        flash('Write access required to start requests.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)
    if req.status != 'Triage':
        flash('Request must be in triage before work can start.', 'warning')
        return redirect(url_for('requests.detail_request', id=id))

    req.status = 'In Progress'
    req.started_at = now()
    db.session.commit()

    flash('Request is now in progress.', 'info')
    return redirect(url_for('requests.detail_request', id=id))


@requests_bp.route('/<int:id>/complete', methods=['POST'])
@requires_permission('operations')
def complete_request(id):
    if not has_write_permission('operations'):
        flash('Write access required to complete requests.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)
    if req.status != 'In Progress':
        flash('Only in-progress requests can be completed.', 'warning')
        return redirect(url_for('requests.detail_request', id=id))

    # Optional resolution notes submitted along with completion
    resolution = request.form.get('resolution_notes')
    if resolution:
        req.resolution_notes = resolution

    req.status = 'Completed'
    req.completed_at = now()
    db.session.commit()

    flash('Request marked as completed.', 'success')
    return redirect(url_for('requests.detail_request', id=id))


@requests_bp.route('/<int:id>/close', methods=['POST'])
@requires_permission('operations')
def close_request(id):
    if not has_write_permission('operations'):
        flash('Write access required to close requests.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)
    if req.status != 'Completed':
        flash('Only completed requests can be closed.', 'warning')
        return redirect(url_for('requests.detail_request', id=id))

    req.status = 'Closed'
    req.closed_at = now()
    db.session.commit()

    flash('Request closed.', 'success')
    return redirect(url_for('requests.detail_request', id=id))


@requests_bp.route('/<int:id>/cancel', methods=['POST'])
@requires_permission('operations')
def cancel_request(id):
    if not has_write_permission('operations'):
        flash('Write access required to cancel requests.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)
    if req.status in ['Completed', 'Closed', 'Cancelled']:
        flash('This request can no longer be cancelled.', 'warning')
        return redirect(url_for('requests.detail_request', id=id))

    req.status = 'Cancelled'
    req.closed_at = now()
    db.session.commit()

    flash('Request cancelled.', 'secondary')
    return redirect(url_for('requests.detail_request', id=id))


@requests_bp.route('/<int:id>/add_evidence', methods=['POST'])
@requires_permission('operations')
def add_evidence(id):
    if not has_write_permission('operations'):
        flash('Write access required to add evidence.', 'danger')
        return redirect(url_for('requests.detail_request', id=id))
    req = db.get_or_404(Request, id)

    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('requests.detail_request', id=id))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('requests.detail_request', id=id))

    if file:
        filename = secure_filename(file.filename)
        unique_filename = f"{now().strftime('%Y%m%d%H%M%S')}_{filename}"

        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)

        attachment = Attachment(
            filename=filename,
            secure_filename=unique_filename,
            linkable_id=req.id,
            linkable_type='Request'
        )
        db.session.add(attachment)
        db.session.commit()

        flash('Evidence uploaded successfully.', 'success')

    return redirect(url_for('requests.detail_request', id=id))
