import os
import uuid
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from datetime import datetime
from ..models import db, SecurityActivity, ActivityExecution, User, Group, Tag, Attachment, ActivityRelatedObject
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..utils.json_api import json_endpoint
from src.utils.timezone_helper import today


activities_bp = Blueprint('activities', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'operations'
ACTIVITY_DETAIL = 'activities.activity_detail'
EXECUTION_DETAIL = 'activities.execution_detail'

@activities_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_activities():
    """Displays a list of all security activities."""
    activities = SecurityActivity.query.order_by(SecurityActivity.name).all()
    
    # Attach latest execution to each activity for display
    for activity in activities:
        activity.latest_execution = activity.executions.first()
    
    return render_template('activities/list.html', activities=activities)

@activities_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_activity():
    """Creates a new security activity."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create activities.', 'danger')
            return redirect(url_for('activities.list_activities'))
        activity = SecurityActivity(
            name=request.form['name'],
            description=request.form.get('description'),
            frequency=request.form.get('frequency')
        )
        
        # Handle polymorphic owner
        owner_type = request.form.get('owner_type')
        if owner_type == 'User':
            activity.owner_id = request.form.get('user_owner_id')
            activity.owner_type = 'User'
        elif owner_type == 'Group':
            activity.owner_id = request.form.get('group_owner_id')
            activity.owner_type = 'Group'
        
        # Handle participants (M2M)
        participant_ids = request.form.getlist('participant_ids')
        if participant_ids:
            activity.participants = User.query.filter(User.id.in_(participant_ids)).all()
        
        # Handle tags (M2M)
        tag_ids = request.form.getlist('tag_ids')
        if tag_ids:
            activity.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        
        db.session.add(activity)
        db.session.commit()
        
        flash('Security Activity created successfully.', 'success')
        return redirect(url_for(ACTIVITY_DETAIL, id=activity.id))
    
    # GET request - render form
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    
    return render_template('activities/form.html', users=users, groups=groups, tags=tags)

@activities_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def activity_detail(id):
    """Displays details of a specific security activity."""
    activity = db.get_or_404(SecurityActivity, id)
    executions = activity.executions.all()
    
    return render_template('activities/detail.html', activity=activity, executions=executions)

@activities_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_activity(id):
    """Edits an existing security activity."""
    activity = db.get_or_404(SecurityActivity, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update activities.', 'danger')
            return redirect(url_for(ACTIVITY_DETAIL, id=id))
        activity.name = request.form['name']
        activity.description = request.form.get('description')
        activity.frequency = request.form.get('frequency')
        
        # Handle polymorphic owner
        owner_type = request.form.get('owner_type')
        if owner_type == 'User':
            activity.owner_id = request.form.get('user_owner_id')
            activity.owner_type = 'User'
        elif owner_type == 'Group':
            activity.owner_id = request.form.get('group_owner_id')
            activity.owner_type = 'Group'
        
        # Handle participants (M2M)
        participant_ids = request.form.getlist('participant_ids')
        activity.participants = User.query.filter(User.id.in_(participant_ids)).all() if participant_ids else []
        
        # Handle tags (M2M)
        tag_ids = request.form.getlist('tag_ids')
        activity.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        
        db.session.commit()
        
        flash('Security Activity updated successfully.', 'success')
        return redirect(url_for(ACTIVITY_DETAIL, id=activity.id))
    
    # GET request - render form with existing data
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    
    return render_template('activities/form.html', activity=activity, users=users, groups=groups, tags=tags)

@activities_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_activity(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete activities.', 'danger')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    """Deletes a security activity."""
    activity = db.get_or_404(SecurityActivity, id)
    activity_name = activity.name
    
    db.session.delete(activity)
    db.session.commit()
    
    flash(f'Security Activity "{activity_name}" has been deleted.', 'success')
    return redirect(url_for('activities.list_activities'))

@activities_bp.route('/<int:id>/execute', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def execute_activity(id):
    """Records a new execution for a security activity."""
    activity = db.get_or_404(SecurityActivity, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to record executions.', 'danger')
            return redirect(url_for(ACTIVITY_DETAIL, id=id))
        execution = ActivityExecution(
            activity_id=activity.id,
            executor_id=request.form.get('executor_id') or session.get('user_id'),
            execution_date=datetime.strptime(request.form['execution_date'], '%Y-%m-%d').date(),
            status=request.form['status'],
            outcome_notes=request.form.get('outcome_notes')
        )
        
        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             execution.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

        db.session.add(execution)
        db.session.commit() # Commit to get execution.id
        
        # Handle file uploads (evidence)
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file.filename != '':
                    original_filename = secure_filename(file.filename)
                    file_ext = os.path.splitext(original_filename)[1]
                    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                    
                    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                    
                    attachment = Attachment(
                        filename=original_filename,
                        secure_filename=unique_filename,
                        linkable_type='ActivityExecution',
                        linkable_id=execution.id
                    )
                    db.session.add(attachment)
            
            db.session.commit()
        
        flash('Execution recorded successfully.', 'success')
        return redirect(url_for(EXECUTION_DETAIL, id=execution.id))
    
    # GET request - render form
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    current_user = db.session.get(User,session.get('user_id'))
    today_date = today().strftime('%Y-%m-%d')
    
    return render_template('activities/execution_form.html', 
                         activity=activity, 
                         users=users, 
                         current_user=current_user,
                         today_date=today_date)

@activities_bp.route('/execution/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def execution_detail(id):
    """Displays details of a specific execution."""
    execution = db.get_or_404(ActivityExecution, id)
    return render_template('activities/execution_detail.html', execution=execution)

@activities_bp.route('/execution/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_execution(id):
    """Edits an existing execution."""
    execution = db.get_or_404(ActivityExecution, id)
    activity = execution.activity
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update executions.', 'danger')
            return redirect(url_for(EXECUTION_DETAIL, id=id))
        execution.executor_id = request.form.get('executor_id')
        execution.execution_date = datetime.strptime(request.form['execution_date'], '%Y-%m-%d').date()
        execution.status = request.form['status']
        execution.outcome_notes = request.form.get('outcome_notes')
        
        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             execution.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        else:
             execution.tags = []

        # Handle new file uploads
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file.filename != '':
                    original_filename = secure_filename(file.filename)
                    file_ext = os.path.splitext(original_filename)[1]
                    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                    
                    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                    
                    attachment = Attachment(
                        filename=original_filename,
                        secure_filename=unique_filename,
                        linkable_type='ActivityExecution',
                        linkable_id=execution.id
                    )
                    db.session.add(attachment)
        
        db.session.commit()
        
        flash('Execution updated successfully.', 'success')
        return redirect(url_for(EXECUTION_DETAIL, id=execution.id))
    
    # GET request
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    
    return render_template('activities/execution_form.html', 
                         activity=activity, 
                         execution=execution,
                         users=users,
                         today_date=execution.execution_date.strftime('%Y-%m-%d'))

@activities_bp.route('/get-objects-by-type', methods=['GET'])
@json_endpoint
@login_required
@requires_permission(MODULE)
def get_objects_by_type():
    """AJAX endpoint to get objects of a specific type."""
    object_type = request.args.get('type')
    
    if not object_type:
        return jsonify({'error': 'No type specified'}), 400
    
    # Import models dynamically to avoid circular imports
    from ..models.assets import Asset, Software
    from ..models.procurement import Supplier, Subscription
    from ..models.policy import Policy
    from ..models.core import Documentation
    from ..models.training import Course
    from ..models.bcdr import BCDRPlan
    from ..models.security import SecurityIncident, Risk
    
    model_map = {
        'Asset': Asset,
        'Software': Software,
        'Subscription': Subscription,
        'Supplier': Supplier,
        'Policy': Policy,
        'Documentation': Documentation,
        'Course': Course,
        'BCDRPlan': BCDRPlan,
        'SecurityIncident': SecurityIncident,
        'Risk': Risk,
    }
    
    model = model_map.get(object_type)
    if not model:
        return jsonify({'error': 'Invalid object type'}), 400
    
    # Query objects - handle different model structures
    try:
        if hasattr(model, 'is_archived'):
            objects = model.query.filter_by(is_archived=False).order_by(model.name).all()
        else:
            objects = model.query.order_by(model.name).all()
        
        # Convert to JSON-serializable format
        objects_data = [{'id': obj.id, 'name': obj.name} for obj in objects]
        
        return jsonify({'objects': objects_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@activities_bp.route('/<int:id>/link-object', methods=['POST'])
@login_required
@requires_permission(MODULE)
def link_object(id):
    if not has_write_permission(MODULE):
        flash('Write access required to link objects.', 'danger')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    """Links an object to a security activity."""
    db.get_or_404(SecurityActivity, id)
    
    object_type = request.form.get('object_type')
    object_id = request.form.get('object_id')
    
    if not object_type or not object_id:
        flash('Please select both object type and object.', 'danger')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    
    # Check if link already exists
    existing_link = ActivityRelatedObject.query.filter_by(
        activity_id=id,
        related_object_type=object_type,
        related_object_id=object_id
    ).first()
    
    if existing_link:
        flash('This object is already linked to this activity.', 'warning')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    
    # Create new link
    link = ActivityRelatedObject(
        activity_id=id,
        related_object_type=object_type,
        related_object_id=object_id
    )
    
    db.session.add(link)
    db.session.commit()
    
    flash(f'{object_type} linked successfully.', 'success')
    return redirect(url_for(ACTIVITY_DETAIL, id=id))

@activities_bp.route('/<int:id>/unlink-object/<int:link_id>', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unlink_object(id, link_id):
    if not has_write_permission(MODULE):
        flash('Write access required to unlink objects.', 'danger')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    """Removes a link between an activity and an object."""
    db.get_or_404(SecurityActivity, id)
    link = db.get_or_404(ActivityRelatedObject, link_id)
    
    # Verify the link belongs to this activity
    if link.activity_id != id:
        flash('Invalid link.', 'danger')
        return redirect(url_for(ACTIVITY_DETAIL, id=id))
    
    db.session.delete(link)
    db.session.commit()
    
    flash('Object unlinked successfully.', 'success')
    return redirect(url_for(ACTIVITY_DETAIL, id=id))
