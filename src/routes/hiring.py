import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models.hiring import HiringStage, Candidate
from ..models.onboarding import OnboardingProcess
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now, today, to_utc
from ..utils.redirects import safe_redirect_target


hiring_bp = Blueprint('hiring', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'hr_people'
BOARD = 'hiring.board'
EDIT_CANDIDATE = 'hiring.edit_candidate'
MANAGE_STAGES = 'hiring.manage_stages'

# ==========================================
# KANBAN BOARD
# ==========================================

@hiring_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def board():
    """Main Kanban board view for hiring pipeline."""
    stages = HiringStage.query.order_by(HiringStage.order).all()

    # Filter 'Hired' and 'Rejected' candidates > 15 days
    from datetime import timedelta
    cutoff_date = now() - timedelta(days=15)

    for stage in stages:
        if stage.name in ['Hired', 'Rejected']:
            # Filter logic: Keep if updated recently AND not archived
            # Convert naive updated_at to timezone-aware before comparison
            stage.display_candidates = [c for c in stage.candidates if not c.is_archived and c.updated_at and to_utc(c.updated_at) >= cutoff_date]
        else:
            # Filter archived
            stage.display_candidates = [c for c in stage.candidates if not c.is_archived]
            
    return render_template('hiring/board.html', stages=stages)

@hiring_bp.route('/list', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_candidates():
    """List view of all candidates with search and pagination."""
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '')
    status_filter = request.args.get('status', 'active') # active, archived, all
    
    query = Candidate.query
    
    # Search
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(
            db.or_(
                Candidate.name.ilike(search),
                Candidate.email.ilike(search),
                Candidate.position.ilike(search)
            )
        )
    
    # Filter
    if status_filter == 'active':
        query = query.filter(Candidate.is_archived == False)
    elif status_filter == 'archived':
        query = query.filter(Candidate.is_archived == True)
        
    # Sort by updated decreasing
    pagination = query.order_by(Candidate.updated_at.desc()).paginate(page=page, per_page=20)
    
    return render_template(
        'hiring/list.html', 
        candidates=pagination.items, 
        pagination=pagination,
        search_query=search_query,
        status_filter=status_filter
    )

# ==========================================
# CANDIDATE MANAGEMENT
# ==========================================

@hiring_bp.route('/candidate/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_candidate():
    """Create a new candidate."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create candidates.', 'danger')
            return redirect(url_for(BOARD))
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        position = request.form.get('position')
        expected_salary = request.form.get('expected_salary')
        currency = request.form.get('currency', 'EUR')
        stage_id = request.form.get('stage_id')
        stage_id = request.form.get('stage_id')
        
        # File Upload Handling
        resume_filename = None
        if 'resume' in request.files:
            file = request.files['resume']
            if file and file.filename != '':
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                resume_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(resume_path)
                resume_filename = unique_filename
        
        # Fallback to existing logic if it was a text link (UI might allow both or transition)
        # But for now, we prioritize the file upload. 
        # If no file uploaded, check if there's a manual link provided (legacy support)
        if not resume_filename:
             resume_filename = request.form.get('resume_link')

        notes = request.form.get('notes')
        
        # Validation
        if not name or not email or not stage_id:
            flash('Name, email, and stage are required.', 'danger')
            return redirect(url_for('hiring.new_candidate'))
        
        # Create candidate
        candidate = Candidate(
            name=name,
            email=email,
            phone=phone,
            position=position,
            expected_salary=float(expected_salary) if expected_salary else None,
            currency=currency,
            stage_id=int(stage_id),
            resume_link=resume_filename,
            notes=notes
        )
        db.session.add(candidate)
        db.session.commit()
        
        flash(f'Candidate "{name}" added successfully.', 'success')
        return redirect(url_for(BOARD))
    
    # GET: Show form
    stages = HiringStage.query.order_by(HiringStage.order).all()
    return render_template('hiring/candidate_form.html', stages=stages, candidate=None)

@hiring_bp.route('/candidate/<int:id>', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_candidate(id):
    """View/Edit a candidate."""
    candidate = db.get_or_404(Candidate, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update candidates.', 'danger')
            return redirect(url_for(EDIT_CANDIDATE, id=id))
        candidate.name = request.form.get('name')
        candidate.email = request.form.get('email')
        candidate.phone = request.form.get('phone')
        candidate.position = request.form.get('position')
        
        salary_str = request.form.get('expected_salary')
        candidate.expected_salary = float(salary_str) if salary_str else None
        candidate.currency = request.form.get('currency', 'EUR')
        candidate.stage_id = int(request.form.get('stage_id'))
        
        # File Upload Handling (Edit)
        if 'resume' in request.files:
            file = request.files['resume']
            if file and file.filename != '':
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                resume_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(resume_path)
                
                # Delete old file if it exists and looks like a local file (no http prefix)
                if candidate.resume_link and not candidate.resume_link.startswith('http'):
                    try:
                        old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], candidate.resume_link)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    except Exception as e:
                        current_app.logger.error(f"Error deleting old resume: {e}")
                
                candidate.resume_link = unique_filename

        # If user explicitly cleared it or put a link (optional, if we keep the text input hidden/alternative)
        # For this task, we assume the file input is primary. We verify if 'resume_link' text field 
        # is even submitted. API might still send it.
        # We preserve existing if no new file is uploaded.
        
        candidate.notes = request.form.get('notes')
        
        db.session.commit()
        flash(f'Candidate "{candidate.name}" updated.', 'success')
        return redirect(url_for(BOARD))
    
    stages = HiringStage.query.order_by(HiringStage.order).all()
    return render_template('hiring/candidate_form.html', stages=stages, candidate=candidate)

@hiring_bp.route('/candidate/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_candidate(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete candidates.', 'danger')
        return redirect(url_for(BOARD))
    """Delete a candidate."""
    candidate = db.get_or_404(Candidate, id)
    name = candidate.name
    db.session.delete(candidate)
    db.session.commit()
    flash(f'Candidate "{name}" deleted.', 'warning')
    return redirect(url_for(BOARD))

@hiring_bp.route('/candidate/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def archive_candidate(id):
    if not has_write_permission(MODULE):
        flash('Write access required to archive candidates.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(BOARD)))
    """Archive a candidate."""
    candidate = db.get_or_404(Candidate, id)
    candidate.is_archived = True
    db.session.commit()
    flash(f'Candidate "{candidate.name}" archived.', 'success')
    return redirect(safe_redirect_target(request.referrer, url_for(BOARD)))

@hiring_bp.route('/candidate/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unarchive_candidate(id):
    if not has_write_permission(MODULE):
        flash('Write access required to unarchive candidates.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for('hiring.list_candidates')))
    """Unarchive a candidate."""
    candidate = db.get_or_404(Candidate, id)
    candidate.is_archived = False
    db.session.commit()
    flash(f'Candidate "{candidate.name}" unarchived.', 'success')
    return redirect(safe_redirect_target(request.referrer, url_for('hiring.list_candidates')))

@hiring_bp.route('/candidate/<int:id>/resume', methods=['GET'])
@login_required
@requires_permission(MODULE)
def download_resume(id):
    """Download the candidate's resume."""
    candidate = db.get_or_404(Candidate, id)
    
    if not candidate.resume_link:
        flash('No resume attached.', 'warning')
        return redirect(url_for(EDIT_CANDIDATE, id=id))
        
    # Check if it's an external link
    if candidate.resume_link.startswith('http') or candidate.resume_link.startswith('www'):
        return redirect(candidate.resume_link)
        
    # Otherwise treat as file in UPLOAD_FOLDER
    try:
        return send_from_directory(
            current_app.config['UPLOAD_FOLDER'],
            candidate.resume_link,
            as_attachment=True,
            download_name=f"Resume_{candidate.name.replace(' ', '_')}{os.path.splitext(candidate.resume_link)[1]}"
        )
    except FileNotFoundError:
        flash('Resume file not found on server.', 'danger')
        return redirect(url_for(EDIT_CANDIDATE, id=id))

# ==========================================
# KANBAN DRAG & DROP API
# ==========================================

@hiring_bp.route('/move', methods=['POST'])
@login_required
@requires_permission(MODULE)
def move_candidate():
    if not has_write_permission(MODULE):
        return jsonify({'status': 'error', 'message': 'Write access required to move candidates.'}), 403
    """API endpoint for moving candidates between stages (drag & drop).
    Note: CSRF is disabled for JSON requests in Flask-WTF by default."""
    data = request.json
    candidate_id = data.get('id')
    new_stage_id = data.get('stage_id')
    
    if not candidate_id or not new_stage_id:
        return jsonify({'status': 'error', 'message': 'Missing parameters'}), 400
    
    candidate = db.get_or_404(Candidate, candidate_id)
    new_stage = db.get_or_404(HiringStage, new_stage_id)
    
    # Validation: Prevent moving out/within if already hired (frontend should block, but safer here)
    if candidate.stage.is_hired_stage:
        return jsonify({'status': 'error', 'message': 'Candidate is already hired and locked.'}), 400

    # Update stage
    candidate.stage_id = new_stage.id
    db.session.commit()
    
    # Check for "Hired" trigger
    if new_stage.is_hired_stage:
        company_email = data.get('company_email')
        pack_id = data.get('pack_id')
        
        # New fields
        personal_email = data.get('personal_email') or candidate.email # Use modal input or fallback
        manager_id = data.get('manager_id')
        buddy_id = data.get('buddy_id')

        # Check if onboarding already exists to avoid duplicates (chk by personal_email)
        existing_onboarding = OnboardingProcess.query.filter_by(personal_email=personal_email).first()
        
        if not existing_onboarding:
            new_onboarding = OnboardingProcess(
                new_hire_name=candidate.name,
                personal_email=personal_email,
                target_email=company_email,
                pack_id=int(pack_id) if pack_id else None,
                start_date=today(),
                status='Pending',
                assigned_manager_id=int(manager_id) if manager_id else None,
                assigned_buddy_id=int(buddy_id) if buddy_id else None
            )
            db.session.add(new_onboarding)
            db.session.commit()
            
            # --- Generate Checklist Items (Mirrors logic in onboarding logic) ---
            from ..models.onboarding import ProcessItem, ProcessTemplate, OnboardingPack
            
            # 0. Create User
            db.session.add(ProcessItem(
                onboarding_process_id=new_onboarding.id,
                description="👤 Create user account (Automated)",
                item_type='CreateUser'
            ))

            # 1. Global Tasks
            global_tasks = ProcessTemplate.query.filter_by(process_type='onboarding', is_active=True).all()
            for task in global_tasks:
                db.session.add(ProcessItem(
                    onboarding_process_id=new_onboarding.id,
                    description=task.name,
                    item_type='StaticTask'
                ))
            
            # 2. Pack Items
            if pack_id:
                pack = db.session.get(OnboardingPack,pack_id)
                if pack:
                    for p_item in pack.items:
                         # Handle linking logic simplistically here (link IDs, not user yet)
                        linked_obj_id = None
                        if p_item.item_type == 'ServiceAccess' and p_item.service_id:
                            linked_obj_id = p_item.service_id
                        elif p_item.item_type == 'Software' and p_item.software_id:
                            linked_obj_id = p_item.software_id
                        elif p_item.item_type == 'Subscription' and p_item.subscription_id:
                            linked_obj_id = p_item.subscription_id
                        elif p_item.item_type == 'Course' and p_item.course_id:
                            linked_obj_id = p_item.course_id

                        db.session.add(ProcessItem(
                            onboarding_process_id=new_onboarding.id,
                            description=p_item.description,
                            item_type=p_item.item_type,
                            linked_object_id=linked_obj_id
                        ))
                    
                    # Trigger Communications
                    from ..utils.communications_manager import trigger_workflow_communications
                    trigger_workflow_communications(new_onboarding, pack)
            
            # 3. Social Logic (Manager/Buddy Tasks)
            if new_onboarding.assigned_manager_id:
                from ..models import User
                manager = db.session.get(User,new_onboarding.assigned_manager_id)
                if manager:
                     db.session.add(ProcessItem(
                        onboarding_process_id=new_onboarding.id,
                        description=f"📅 Schedule 1:1 meeting with {manager.name} (Manager)",
                        item_type='SocialTask',
                        linked_object_id=manager.id
                    ))
            
            if new_onboarding.assigned_buddy_id:
                from ..models import User
                buddy = db.session.get(User,new_onboarding.assigned_buddy_id)
                if buddy:
                    db.session.add(ProcessItem(
                        onboarding_process_id=new_onboarding.id,
                        description=f"☕ Schedule welcome coffee with buddy: {buddy.name}",
                        item_type='SocialTask',
                        linked_object_id=buddy.id
                    ))

            db.session.commit()
            
            flash(f'🎉 Candidate "{candidate.name}" hired! Onboarding process initiated.', 'success')
            return jsonify({'status': 'success', 'action': 'onboarding_started'})
        else:
            flash('Candidate moved to Hired. (Onboarding already exists)', 'info')
    
    return jsonify({'status': 'success'})

# ==========================================
# STAGE MANAGEMENT
# ==========================================

@hiring_bp.route('/stages', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def manage_stages():
    """Admin view to manage hiring stages."""
    stages = HiringStage.query.order_by(HiringStage.order).all()
    return render_template('hiring/stages.html', stages=stages)

@hiring_bp.route('/stages/new', methods=['POST'])
@login_required
@requires_permission(MODULE)
def new_stage():
    """Create a new hiring stage."""
    if not has_write_permission(MODULE):
        flash('Write access required to create stages.', 'danger')
        return redirect(url_for(MANAGE_STAGES))

    name = request.form.get('name', '').strip()
    is_hired_stage = 'is_hired_stage' in request.form

    if not name:
        flash('Stage name is required.', 'danger')
        return redirect(url_for(MANAGE_STAGES))
    
    # Auto-assign order (last + 1)
    max_order = db.session.query(db.func.max(HiringStage.order)).scalar() or 0
    
    stage = HiringStage(
        name=name,
        order=max_order + 1,
        is_hired_stage=is_hired_stage
    )
    db.session.add(stage)
    db.session.commit()
    
    flash(f'Stage "{name}" created.', 'success')
    return redirect(url_for(MANAGE_STAGES))

@hiring_bp.route('/stages/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_stage(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete stages.', 'danger')
        return redirect(url_for(MANAGE_STAGES))
    """Delete a hiring stage."""
    stage = db.get_or_404(HiringStage, id)
    
    # Protected stages
    PROTECTED_STAGES = ['Applied', 'Offer', 'Hired', 'Rejected']
    if stage.name in PROTECTED_STAGES:
        flash(f'Cannot delete system stage "{stage.name}".', 'danger')
        return redirect(url_for(MANAGE_STAGES))

    # Check if stage has candidates
    if stage.candidates:
        flash(f'Cannot delete stage "{stage.name}" - it still has {len(stage.candidates)} candidates.', 'danger')
        return redirect(url_for(MANAGE_STAGES))
    
    name = stage.name
    db.session.delete(stage)
    db.session.commit()
    
    flash(f'Stage "{name}" deleted.', 'success')
    return redirect(url_for(MANAGE_STAGES))

@hiring_bp.route('/stages/reorder', methods=['POST'])
@login_required
@requires_permission(MODULE)
def update_stage_order():
    if not has_write_permission(MODULE):
        return jsonify({'status': 'error', 'message': 'Write access required to reorder stages.'}), 403
    """API to update the order of stages."""
    data = request.json
    ordered_ids = data.get('ordered_ids', [])
    
    if not ordered_ids:
        return jsonify({'status': 'error', 'message': 'No IDs provided'}), 400
        
    for index, stage_id in enumerate(ordered_ids):
        stage = db.session.get(HiringStage,stage_id)
        if stage:
            stage.order = index
            
    db.session.commit()
    return jsonify({'status': 'success'})

@hiring_bp.route('/stages/<int:id>/update', methods=['POST'])
@login_required
@requires_permission(MODULE)
def update_stage(id):
    if not has_write_permission(MODULE):
        flash('Write access required to update stages.', 'danger')
        return redirect(url_for(MANAGE_STAGES))
    """Update a hiring stage (rename)."""
    stage = db.get_or_404(HiringStage, id)
    
    name = request.form.get('name')
    if not name:
        flash('Stage name is required.', 'danger')
        return redirect(url_for(MANAGE_STAGES))
        
    stage.name = name
    db.session.commit()
    
    flash(f'Stage renamed to "{name}".', 'success')
    return redirect(url_for(MANAGE_STAGES))
