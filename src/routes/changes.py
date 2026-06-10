from flask import Blueprint, render_template, request, flash, redirect, url_for, session, current_app
from ..extensions import db
from ..models import (Change, User, BusinessService, Asset, Software, Tag, Attachment, Configuration, ConfigurationVersion)
from ..services.permissions_service import requires_permission, has_write_permission
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from src.utils.timezone_helper import now


changes_bp = Blueprint('changes', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'operations'
DETAIL_CHANGE = 'changes.detail_change'

@changes_bp.route('/', methods=['GET'])
@requires_permission(MODULE)
def list_changes():
    """List all changes with filtering."""
    status = request.args.get('status')
    change_type = request.args.get('type')
    priority = request.args.get('priority')
    
    query = Change.query
    
    if status:
        query = query.filter(Change.status == status)
    if change_type:
        query = query.filter(Change.change_type == change_type)
    if priority:
        query = query.filter(Change.priority == priority)
        
    changes = query.order_by(Change.created_at.desc()).all()
    
    return render_template('changes/list.html', changes=changes)

@changes_bp.route('/new', methods=['GET', 'POST'])
@requires_permission(MODULE)
def new_change():
    """Create a new change request."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create change requests.', 'danger')
            return redirect(url_for('changes.list_changes'))
        user_id = session.get('user_id')
        if not user_id:
            flash('You must be logged in to create a change.', 'danger')
            return redirect(url_for('main.login'))
            
        title = request.form.get('title')
        change_type = request.form.get('change_type')
        priority = request.form.get('priority')
        
        # Quality Gate: Check mandatory planning fields for higher risks
        if change_type in ['Normal', 'Emergency']:
            if not request.form.get('implementation_plan') or not request.form.get('rollback_plan') or not request.form.get('test_plan'):
                flash('Change request failed: Implementation, Rollback, and Test Plans are mandatory for Normal and Emergency changes.', 'danger')
                return redirect(url_for('changes.new_change'))

        # Handle Requires Approval
        requires_approval = True if request.form.get('requires_approval') else False
        
        change = Change(
            title=title,
            change_type=change_type,
            priority=priority,
            risk_impact=request.form.get('risk_impact'),
            status='Draft', # Initial status
            requires_approval=requires_approval,
            description=request.form.get('description'),
            implementation_plan=request.form.get('implementation_plan'),
            rollback_plan=request.form.get('rollback_plan'),
            test_plan=request.form.get('test_plan'),
            requester_id=user_id,
            assignee_id=request.form.get('assignee_id'),
            estimated_duration=request.form.get('estimated_duration') # in minutes
        )
        
        # Handle Date fields which might be empty
        start = request.form.get('scheduled_start')
        end = request.form.get('scheduled_end')
        if start:
            change.scheduled_start = datetime.strptime(start, '%Y-%m-%dT%H:%M')
        if end:
            change.scheduled_end = datetime.strptime(end, '%Y-%m-%dT%H:%M')
            
        # Handle Target
        target_type = request.form.get('target_type')
        
        if target_type == 'service':
            change.service_id = request.form.get('service_id')
        elif target_type == 'asset':
            change.asset_id = request.form.get('asset_id')
        elif target_type == 'software':
            change.software_id = request.form.get('software_id')
        elif target_type == 'configuration':
            change.configuration_id = request.form.get('configuration_id')
            change.configuration_version_id = request.form.get('configuration_version_id')
            
        # Handle Tags
        tag_ids = request.form.getlist('tag_ids')
        for tag_id in tag_ids:
            tag = db.session.get(Tag,tag_id)
            if tag:
                change.tags.append(tag)
                
        db.session.add(change)
        db.session.commit()
        
        # Workflow Logic
        if not requires_approval:
            # Skip approval step
            change.status = 'Approved'
            change.approved_at = now()
            change.approved_by_id = user_id # Auto-approval by creator for Standards
            flash('Change created and auto-approved (Standard/No Approval Required).', 'success')
        else:
            # Normal workflow
            change.status = 'Pending Approval'
            flash('Change request created successfully.', 'success')
            
        db.session.commit()
        return redirect(url_for(DETAIL_CHANGE, id=change.id))
        
    # GET: Prepare data for form - FILTER ACTIVE ONLY
    users = User.query.filter_by(is_archived=False).all()
    services = BusinessService.query.filter(BusinessService.status != 'Retired').all()
    assets = Asset.query.filter_by(is_archived=False).all()
    software = Software.query.filter_by(is_archived=False).all()
    configurations = Configuration.query.all() # No archive flag on Configs yet
    tags = Tag.query.filter_by(is_archived=False).all()
    
    return render_template('changes/form.html', 
                          users=users, 
                          services=services, 
                          assets=assets, 
                          software=software,
                          configurations=configurations,
                          tags=tags,
                          today=now(),
                          change=None)

@changes_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE)
def edit_change(id):
    """Edit an existing change request."""
    change = db.get_or_404(Change, id)
    
    # Allow editing only if not final (you might want to restrict this further based on policy)
    if change.status in ['Completed', 'Cancelled', 'Failed']:
        flash('Cannot edit a closed change.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
        
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update change requests.', 'danger')
            return redirect(url_for(DETAIL_CHANGE, id=id))
        change.title = request.form.get('title')
        change.description = request.form.get('description')
        change.change_type = request.form.get('change_type')
        change.priority = request.form.get('priority')
        change.risk_impact = request.form.get('risk_impact')
        
        change.implementation_plan = request.form.get('implementation_plan')
        change.rollback_plan = request.form.get('rollback_plan')
        change.test_plan = request.form.get('test_plan')
        change.assignee_id = request.form.get('assignee_id') or None
        change.estimated_duration = request.form.get('estimated_duration')
        
        # Handle Date fields
        start = request.form.get('scheduled_start')
        end = request.form.get('scheduled_end')
        if start:
            change.scheduled_start = datetime.strptime(start, '%Y-%m-%dT%H:%M')
        if end:
            change.scheduled_end = datetime.strptime(end, '%Y-%m-%dT%H:%M')
            
        # Handle Target
        target_type = request.form.get('target_type')
        
        if target_type == 'service':
            change.service_id = request.form.get('service_id')
            change.asset_id = None
            change.software_id = None
            change.configuration_id = None
            change.configuration_version_id = None
        elif target_type == 'asset':
            change.asset_id = request.form.get('asset_id')
            change.service_id = None
            change.software_id = None
            change.configuration_id = None
            change.configuration_version_id = None
        elif target_type == 'software':
            change.software_id = request.form.get('software_id')
            change.service_id = None
            change.asset_id = None
            change.configuration_id = None
            change.configuration_version_id = None
        elif target_type == 'configuration':
            change.configuration_id = request.form.get('configuration_id')
            change.configuration_version_id = request.form.get('configuration_version_id')
            change.service_id = None
            change.asset_id = None
            change.software_id = None
            
        # Handle Tags
        tag_ids = request.form.getlist('tag_ids')
        change.tags = [] # Reset tags
        for tag_id in tag_ids:
            tag = db.session.get(Tag,tag_id)
            if tag:
                change.tags.append(tag)
                
        db.session.commit()
        flash('Change updated successfully.', 'success')
        return redirect(url_for(DETAIL_CHANGE, id=change.id))

    # GET: Prepare data for form - FILTER ACTIVE ONLY
    users = User.query.filter_by(is_archived=False).all()
    services = BusinessService.query.filter(BusinessService.status != 'Retired').all()
    assets = Asset.query.filter_by(is_archived=False).all()
    software = Software.query.filter_by(is_archived=False).all()
    configurations = Configuration.query.all()
    tags = Tag.query.filter_by(is_archived=False).all()
    
    return render_template('changes/form.html', 
                          users=users, 
                          services=services, 
                          assets=assets, 
                          software=software,
                          configurations=configurations,
                          tags=tags,
                          change=change)

@changes_bp.route('/<int:id>', methods=['GET'])
@requires_permission(MODULE)
def detail_change(id):
    change = db.get_or_404(Change, id)
    return render_template('changes/detail.html', change=change)

@changes_bp.route('/<int:id>/approve', methods=['POST'])
@requires_permission(MODULE)
def approve_change(id):
    if not has_write_permission(MODULE):
        flash('Write access required to approve changes.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
    change = db.get_or_404(Change, id)
    user_id = session.get('user_id')
    user = db.session.get(User,user_id)
    
    # SEGREGATION OF DUTIES:
    # Requester cannot approve their own change unless they are admin
    if change.requester_id == user_id and user.role != 'admin':
        flash('Security Violation: You cannot approve your own change request. Segregation of duties required.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
        
    change.status = 'Approved'
    change.approved_by_id = user_id
    change.approved_at = now()
    db.session.commit()
    
    flash('Change approved successfully.', 'success')
    return redirect(url_for(DETAIL_CHANGE, id=id))

@changes_bp.route('/<int:id>/start', methods=['POST'])
@requires_permission(MODULE)
def start_change(id):
    if not has_write_permission(MODULE):
        flash('Write access required to start changes.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
    change = db.get_or_404(Change, id)
    if change.status != 'Approved':
        flash('Change must be approved before starting.', 'warning')
        return redirect(url_for(DETAIL_CHANGE, id=id))
        
    change.status = 'In Progress'
    change.executed_at = now()
    db.session.commit()
    
    flash('Change execution started.', 'info')
    return redirect(url_for(DETAIL_CHANGE, id=id))

@changes_bp.route('/<int:id>/complete', methods=['POST'])
@requires_permission(MODULE)
def complete_change(id):
    if not has_write_permission(MODULE):
        flash('Write access required to complete changes.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
    change = db.get_or_404(Change, id)
    
    change.status = 'Completed'
    change.closed_at = now()
    db.session.commit()
    
    flash('Change marked as completed.', 'success')
    return redirect(url_for(DETAIL_CHANGE, id=id))

@changes_bp.route('/<int:id>/cancel', methods=['POST'])
@requires_permission(MODULE)
def cancel_change(id):
    if not has_write_permission(MODULE):
        flash('Write access required to cancel changes.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
    change = db.get_or_404(Change, id)
    change.status = 'Cancelled'
    change.closed_at = now()
    db.session.commit()
    
    flash('Change cancelled.', 'secondary')
    return redirect(url_for(DETAIL_CHANGE, id=id))

@changes_bp.route('/<int:id>/add_evidence', methods=['POST'])
@requires_permission(MODULE)
def add_evidence(id):
    if not has_write_permission(MODULE):
        flash('Write access required to add evidence.', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
    change = db.get_or_404(Change, id)
    
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
        
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for(DETAIL_CHANGE, id=id))
        
    if file:
        filename = secure_filename(file.filename)
        # Unique filename
        unique_filename = f"{now().strftime('%Y%m%d%H%M%S')}_{filename}"
        
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        # Create attachment record
        attachment = Attachment(
            filename=filename,
            secure_filename=unique_filename,
            linkable_id=change.id,
            linkable_type='Change'
        )
        db.session.add(attachment)
        db.session.commit()
        
        flash('Evidence uploaded successfully.', 'success')
        
    return redirect(url_for(DETAIL_CHANGE, id=id))
