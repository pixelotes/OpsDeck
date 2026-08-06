from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, jsonify
from .main import login_required
from ..extensions import db
from ..models.audits import ComplianceAudit, AuditControlItem, AuditControlLink
from ..models.security import Framework
from ..models.auth import User
from ..models.onboarding import OnboardingProcess, OffboardingProcess
from ..models.crm import Contact
from ..models.core import Attachment
from weasyprint import HTML
import io
import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now


audits_bp = Blueprint('audits', __name__, url_prefix='/security/audits')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'compliance'
LIST_AUDITS = 'audits.list_audits'
NEW_AUDIT = 'audits.new_audit'
VIEW_AUDIT = 'audits.view_audit'
MSG_AUDIT_LOCKED_CANNOT_MODIFIED = 'Audit is locked and cannot be modified.'
MSG_FILE_SELECTED = 'No file selected.'

# ============================================================================
# LIST & CRUD
# ============================================================================

@audits_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_audits():
    # IMPORTANT: Show ALL audits regardless of framework.is_active status
    # Audits are historical evidence snapshots and remain valid even if framework is deactivated
    # This allows companies to maintain audit history when frameworks are no longer in use
    # Filter out drift_snapshots - those are internal data for compliance drift detection, not real audits
    audits = ComplianceAudit.query.filter(
        ComplianceAudit.audit_type != 'drift_snapshot'
    ).order_by(ComplianceAudit.created_at.desc()).all()
    return render_template('audits/list.html', audits=audits)

@audits_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_audit():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create audits.', 'danger')
            return redirect(url_for(LIST_AUDITS))
        creation_strategy = request.form.get('creation_strategy', 'scratch')
        
        # Common fields
        internal_lead_id = request.form.get('internal_lead_id')
        
        if not internal_lead_id:
            flash('Internal Lead is required.', 'danger')
            return redirect(url_for(NEW_AUDIT))
        
        # Automated Evidence Configuration (applies to both strategies)
        evidence_months = int(request.form.get('evidence_months', 6))
        enable_sampling = request.form.get('enable_sampling') == 'on'
        sample_size = int(request.form.get('sample_size', 3)) if enable_sampling else None

        try:
            audit = None
            if creation_strategy == 'scratch':
                name = request.form.get('name')
                framework_id = request.form.get('framework_id')
                auditor_contact_id = request.form.get('auditor_contact_id') or None
                copy_links = request.form.get('copy_links') == 'on'

                if not name or not framework_id:
                    flash('Audit Name and Framework are required for fresh starts.', 'danger')
                    return redirect(url_for(NEW_AUDIT))

                audit = ComplianceAudit.create_snapshot(
                    framework_id=int(framework_id),
                    name=name,
                    auditor_contact_id=int(auditor_contact_id) if auditor_contact_id else None,
                    internal_lead_id=int(internal_lead_id),
                    copy_links=copy_links,
                    evidence_months=evidence_months,
                    sample_size=sample_size
                )
            
            elif creation_strategy == 'clone':
                source_audit_id = request.form.get('source_audit_id')
                target_date_str = request.form.get('target_date')
                copy_audit_extras = request.form.get('copy_audit_extras') == 'on'
                
                if not source_audit_id:
                    flash('Source Audit is required for renewal.', 'danger')
                    return redirect(url_for(NEW_AUDIT))
                
                target_date = None
                if target_date_str:
                    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

                audit = ComplianceAudit.clone(
                    source_id=int(source_audit_id),
                    new_owner_id=int(internal_lead_id),
                    target_date=target_date,
                    copy_audit_extras=copy_audit_extras,
                    evidence_months=evidence_months,
                    sample_size=sample_size
                )
            
            flash('Audit created successfully.', 'success')
            return redirect(url_for(VIEW_AUDIT, id=audit.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating audit: {str(e)}', 'danger')
            return redirect(url_for(NEW_AUDIT))

    frameworks = Framework.query.filter_by(is_active=True).all()
    users = User.query.filter_by(is_archived=False).all()
    contacts = Contact.query.filter_by(is_archived=False).all()
    # Fetch previous audits for the clone dropdown (exclude drift snapshots)
    previous_audits = ComplianceAudit.query.filter(
        ComplianceAudit.audit_type != 'drift_snapshot'
    ).order_by(ComplianceAudit.created_at.desc()).all()
    
    return render_template('audits/new.html', 
                         frameworks=frameworks, 
                         users=users, 
                         contacts=contacts,
                         previous_audits=previous_audits)

# ============================================================================
# DETAIL & UPDATE
# ============================================================================

@audits_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def view_audit(id):
    audit = db.get_or_404(ComplianceAudit, id)
    users = User.query.filter_by(is_archived=False).all()
    
    # Calculate progress stats
    total_items = audit.audit_items.count()
    compliant_count = audit.audit_items.filter(AuditControlItem.status == 'Compliant').count()
    gap_count = audit.audit_items.filter(AuditControlItem.status == 'Gap').count()
    observation_count = audit.audit_items.filter(AuditControlItem.status == 'Observation').count()
    
    progress = (compliant_count / total_items * 100) if total_items > 0 else 0
    
    # Fetch completed processes for evidence linking
    completed_onboardings = OnboardingProcess.query.filter_by(status='Completed').order_by(OnboardingProcess.created_at.desc()).all()
    # Offboarding status is 'Completed' (based on model default 'In Progress', assuming 'Completed' is final)
    completed_offboardings = OffboardingProcess.query.filter_by(status='Completed').order_by(OffboardingProcess.created_at.desc()).all()
    
    return render_template('audits/detail.html', 
                         audit=audit, 
                         progress=round(progress),
                         total_items=total_items,
                         compliant_count=compliant_count,
                         gap_count=gap_count,
                         observation_count=observation_count,
                         users=users,
                         completed_onboardings=completed_onboardings,
                         completed_offboardings=completed_offboardings)

@audits_bp.route('/<int:id>/header', methods=['POST'])
@login_required
@requires_permission(MODULE)
def update_audit_header(id):
    if not has_write_permission(MODULE):
        flash('Write access required to update audit header.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    audit.status = request.form.get('status', audit.status)
    audit.outcome = request.form.get('outcome') or None
    
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')
    
    if start_date:
        audit.start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if end_date:
        audit.end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    db.session.commit()
    flash('Audit details updated.', 'success')
    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/update', methods=['POST'])
@login_required
@requires_permission(MODULE)
def update_audit_items(id):
    if not has_write_permission(MODULE):
        flash('Write access required to update audit items.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    for item in audit.audit_items:
        item_id = str(item.id)
        
        is_applicable = request.form.get(f'item_{item_id}_applicable') == 'on'
        item.is_applicable = is_applicable
        item.justification = request.form.get(f'item_{item_id}_justification')
        item.internal_comments = request.form.get(f'item_{item_id}_internal_comments')
        item.auditor_findings = request.form.get(f'item_{item_id}_auditor_findings')
        
        status = request.form.get(f'item_{item_id}_status')
        if status:
            item.status = status
        
    try:
        db.session.commit()
        flash('Audit updated successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating audit: {str(e)}', 'danger')
        
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# PARTICIPANTS
# ============================================================================

@audits_bp.route('/<int:id>/participants/add', methods=['POST'])
@login_required
@requires_permission(MODULE)
def add_participant(id):
    if not has_write_permission(MODULE):
        flash('Write access required to add participants.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    user_id = request.form.get('user_id')
    
    if user_id:
        user = db.session.get(User,int(user_id))
        if user and user not in audit.participants:
            audit.participants.append(user)
            db.session.commit()
            flash(f'{user.name} added to the team.', 'success')
    
    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/participants/<int:user_id>/remove', methods=['POST'])
@login_required
@requires_permission(MODULE)
def remove_participant(id, user_id):
    if not has_write_permission(MODULE):
        flash('Write access required to remove participants.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    user = db.get_or_404(User, user_id)
    
    if user in audit.participants:
        audit.participants.remove(user)
        db.session.commit()
        flash(f'{user.name} removed from the team.', 'success')
    
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# ATTACHMENTS (Global Audit Attachments)
# ============================================================================

@audits_bp.route('/<int:id>/attachments/upload', methods=['POST'])
@login_required
@requires_permission(MODULE)
def upload_audit_attachment(id):
    if not has_write_permission(MODULE):
        flash('Write access required to upload attachments.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    from flask import current_app
    
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    if 'file' not in request.files:
        flash(MSG_FILE_SELECTED, 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    file = request.files['file']
    if file.filename == '':
        flash(MSG_FILE_SELECTED, 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    original_filename = file.filename
    unique_filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file.save(os.path.join(upload_folder, unique_filename))
    
    attachment = Attachment(
        filename=original_filename,
        secure_filename=unique_filename,
        linkable_type='ComplianceAudit',
        linkable_id=audit.id
    )
    db.session.add(attachment)
    db.session.commit()
    
    flash('File uploaded successfully.', 'success')
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# ITEM ATTACHMENTS
# ============================================================================

@audits_bp.route('/<int:id>/item/<int:item_id>/upload', methods=['POST'])
@login_required
@requires_permission(MODULE)
def upload_item_attachment(id, item_id):
    if not has_write_permission(MODULE):
        flash('Write access required to upload evidence.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    from flask import current_app
    
    audit = db.get_or_404(ComplianceAudit, id)
    item = db.get_or_404(AuditControlItem, item_id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    if 'file' not in request.files:
        flash(MSG_FILE_SELECTED, 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    file = request.files['file']
    if file.filename == '':
        flash(MSG_FILE_SELECTED, 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    original_filename = file.filename
    unique_filename = f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"
    
    upload_folder = current_app.config['UPLOAD_FOLDER']
    file.save(os.path.join(upload_folder, unique_filename))
    
    attachment = Attachment(
        filename=original_filename,
        secure_filename=unique_filename,
        linkable_type='AuditControlItem',
        linkable_id=item.id
    )
    db.session.add(attachment)
    db.session.commit()
    
    flash('Evidence uploaded.', 'success')
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# LINKED OBJECTS (Polymorphic Links)
# ============================================================================

@audits_bp.route('/<int:id>/item/<int:item_id>/link', methods=['POST'])
@login_required
@requires_permission(MODULE)
def add_item_link(id, item_id):
    if not has_write_permission(MODULE):
        flash('Write access required to link evidence.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    item = db.get_or_404(AuditControlItem, item_id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    linkable_type = request.form.get('linkable_type')
    
    linkable_id = request.form.get('linkable_id_dynamic') 
    
    description = request.form.get('description')
    
    if linkable_type and linkable_id:
        link = AuditControlLink(
            audit_item_id=item.id,
            linkable_type=linkable_type,
            linkable_id=int(linkable_id),
            description=description
        )
        db.session.add(link)
        db.session.commit()
        flash('Evidence linked.', 'success')
    else:
        flash('Failed to link object: Missing type or ID.', 'warning')
    
    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/item/<int:item_id>/link/<int:link_id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_item_link(id, item_id, link_id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete links.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash(MSG_AUDIT_LOCKED_CANNOT_MODIFIED, 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))
    
    link = db.get_or_404(AuditControlLink, link_id)
    db.session.delete(link)
    db.session.commit()
    flash('Link removed.', 'success')
    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/link_evidence', methods=['POST'])
@login_required
@requires_permission(MODULE)
def link_evidence(id):
    if not has_write_permission(MODULE):
        flash('Write access required to link evidence.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    # Lock check
    if audit.is_locked:
        flash('Audit is locked.', 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))

    ev_type = request.form.get('type') # 'onboarding' or 'offboarding'
    ev_id = request.form.get('process_id')
    
    if not ev_id:
        flash('No process selected.', 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))

    if ev_type == 'onboarding':
        proc = db.session.get(OnboardingProcess,ev_id)
        if proc and proc not in audit.onboardings:
            audit.onboardings.append(proc)
            db.session.commit()
            flash('Onboarding evidence linked.', 'success')
    elif ev_type == 'offboarding':
        proc = db.session.get(OffboardingProcess,ev_id)
        if proc and proc not in audit.offboardings:
            audit.offboardings.append(proc)
            db.session.commit()
            flash('Offboarding evidence linked.', 'success')

    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/unlink_evidence', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unlink_evidence(id):
    if not has_write_permission(MODULE):
        flash('Write access required to unlink evidence.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    audit = db.get_or_404(ComplianceAudit, id)
    
    if audit.is_locked:
        flash('Audit is locked.', 'warning')
        return redirect(url_for(VIEW_AUDIT, id=id))

    ev_type = request.form.get('type')
    ev_id = request.form.get('process_id')
    
    if ev_type == 'onboarding':
        proc = db.session.get(OnboardingProcess,ev_id)
        if proc and proc in audit.onboardings:
            audit.onboardings.remove(proc)
            db.session.commit()
            flash('Onboarding evidence removed.', 'success')
    elif ev_type == 'offboarding':
        proc = db.session.get(OffboardingProcess,ev_id)
        if proc and proc in audit.offboardings:
            audit.offboardings.remove(proc)
            db.session.commit()
            flash('Offboarding evidence removed.', 'success')
            
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# API: AJAX Status Update
# ============================================================================

@audits_bp.route('/api/control/<int:id>/status', methods=['POST'])
@login_required
@requires_permission(MODULE)
def api_update_control_status(id):
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'error': 'Write access required'}), 403
    """AJAX endpoint for instant status updates on audit controls."""
    item = db.get_or_404(AuditControlItem, id)
    
    # Security: Check if the audit is locked
    if item.audit.is_locked:
        return jsonify({'success': False, 'error': 'Audit is locked'}), 403
    
    data = request.get_json()
    if not data or 'status' not in data:
        return jsonify({'success': False, 'error': 'Status is required'}), 400
    
    new_status = data['status']
    valid_statuses = ['Pending', 'Compliant', 'Observation', 'Gap', 'Not Applicable']
    
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400
    
    item.status = new_status
    db.session.commit()
    
    return jsonify({'success': True, 'new_status': new_status})

# ============================================================================
# LOCK/UNLOCK AUDIT
# ============================================================================

@audits_bp.route('/<int:id>/lock', methods=['POST'])
@login_required
@requires_permission(MODULE)
def lock_audit(id):
    if not has_write_permission(MODULE):
        flash('Write access required to lock audits.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    """Lock the audit to prevent further modifications."""
    audit = db.get_or_404(ComplianceAudit, id)
    
    if audit.is_locked:
        flash('Audit is already locked.', 'info')
    else:
        audit.locked_at = now()
        db.session.commit()
        flash('Audit has been locked. No further modifications are allowed.', 'success')
    
    return redirect(url_for(VIEW_AUDIT, id=id))

@audits_bp.route('/<int:id>/unlock', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unlock_audit(id):
    if not has_write_permission(MODULE):
        flash('Write access required to unlock audits.', 'danger')
        return redirect(url_for(VIEW_AUDIT, id=id))
    """Unlock the audit to allow modifications again."""
    audit = db.get_or_404(ComplianceAudit, id)
    
    if not audit.is_locked:
        flash('Audit is not locked.', 'info')
    else:
        audit.locked_at = None
        db.session.commit()
        flash('Audit has been unlocked. Modifications are now allowed.', 'success')
    
    return redirect(url_for(VIEW_AUDIT, id=id))

# ============================================================================
# EXPORT
# ============================================================================

@audits_bp.route('/<int:id>/export', methods=['GET'])
@login_required
@requires_permission(MODULE)
def export_audit(id):
    audit = db.get_or_404(ComplianceAudit, id)
    
    html = render_template('audits/export_pdf.html', audit=audit, now=now())
    pdf = HTML(string=html).write_pdf()
    
    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'defense_pack_{audit.id}.pdf'
    )

@audits_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_audit(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete audits.', 'danger')
        return redirect(url_for(LIST_AUDITS))
    audit = db.get_or_404(ComplianceAudit, id)
    db.session.delete(audit)
    db.session.commit()
    flash('Audit deleted.', 'success')
    return redirect(url_for(LIST_AUDITS))

# ============================================================================
# API: Search Linkable Objects
# ============================================================================

@audits_bp.route('/api/search-linkable', methods=['GET'])
@login_required
@requires_permission(MODULE)
def search_linkable_api():
    """Search for linkable objects by type and query.
       If query is empty, returns all non-archived objects of that type.
    """
    object_type = request.args.get('type', '').strip()
    query = request.args.get('q', '').strip()
    
    if not object_type:
        return jsonify([])
    
    results = []
    limit = 50 if query else 200 # Higher limit if listing all
    
    if object_type == 'Asset':
        from ..models import Asset
        q = Asset.query.filter_by(is_archived=False)
        if query:
            q = q.filter(Asset.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': item.status or 'Asset'} for item in items]
    
    elif object_type == 'Policy':
        from ..models import Policy
        q = Policy.query
        if query:
            q = q.filter(Policy.title.ilike(f'%{query}%')) # Policy has title, not name
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.title, 'type': 'Policy'} for item in items]
    
    elif object_type == 'Documentation':
        from ..models import Documentation
        q = Documentation.query
        if query:
            q = q.filter(Documentation.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'Documentation'} for item in items]
    
    elif object_type == 'Link':
        from ..models import Link
        q = Link.query
        if query:
            q = q.filter(Link.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'External Link'} for item in items]
    
    elif object_type == 'Course':
        from ..models import Course
        q = Course.query
        if query:
            q = q.filter(Course.title.ilike(f'%{query}%')) # Course has title
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.title, 'type': 'Training Course'} for item in items]
    
    elif object_type == 'Risk':
        from ..models import Risk
        q = Risk.query
        # risks dont have is_archived, but maybe we exclude 'Closed'? 
        # Not filtered by status: closed risks are legitimate link targets too.
        if query:
            q = q.filter(Risk.risk_description.ilike(f'%{query}%')) # Risk has risk_description, usually not name?
            # Wait, looking at previous code it used Risk.name.ilike
            # Let me check Risk model again or just use risk_description?
            # Previous code: items = Risk.query.filter(Risk.name.ilike(f'%{query}%')).limit(20).all()
            # But in model `Risk` I saw `risk_description`. I didn't see `name`.
            # Let me re-verify Risk model. 
        # Risk model check: 
        # class Risk(db.Model):
        #     risk_description = db.Column(db.Text, nullable=False)
        #     ...
        #     It does NOT have a name field! The previous code was likely broken for Risk.
        #     I will use risk_description as name.
        items = q.limit(limit).all()
        # Truncate description for display
        results = [{'id': item.id, 'name': (item.risk_description[:50] + '...') if len(item.risk_description) > 50 else item.risk_description, 'type': f'Risk (Severity: {item.severity if hasattr(item, "severity") else "N/A"})'} for item in items]
    
    elif object_type == 'Software':
        from ..models import Software
        q = Software.query.filter_by(is_archived=False)
        if query:
            q = q.filter(Software.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'Software'} for item in items]
    
    elif object_type == 'Supplier':
        from ..models import Supplier
        q = Supplier.query.filter_by(is_archived=False)
        if query:
            q = q.filter(Supplier.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'Supplier'} for item in items]
    
    elif object_type == 'BusinessService':
        from ..models import BusinessService
        q = BusinessService.query.filter(BusinessService.status != 'Retired')
        if query:
            q = q.filter(BusinessService.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'Service'} for item in items]

    elif object_type == 'Onboarding':
        from ..models import OnboardingProcess, User
        q = OnboardingProcess.query
        if query:
            # Search by new_hire_name for processes without user, or by user name if user exists
            # Optimized simple search: just filter by new_hire_name OR (join user and filter by user.name)
            # Matches on new_hire_name only. Searching the linked user name as well would
            # need a join, which is not worth it for this picker.
            # Using new_hire_name is safer as it's always populated initially.
            q = q.filter(OnboardingProcess.new_hire_name.ilike(f'%{query}%'))
        
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': f"{item.new_hire_name} ({item.start_date})", 'type': 'Onboarding'} for item in items]

    elif object_type == 'Offboarding':
        from ..models import OffboardingProcess, User
        # Offboarding always has a user_id
        q = OffboardingProcess.query.join(OffboardingProcess.user)
        if query:
            q = q.filter(User.name.ilike(f'%{query}%'))
        
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': f"{item.user.name} ({item.departure_date})", 'type': 'Offboarding'} for item in items]

    elif object_type == 'OrgChartSnapshot':
        from ..models import OrgChartSnapshot
        q = OrgChartSnapshot.query.order_by(OrgChartSnapshot.created_at.desc())
        if query:
            q = q.filter(OrgChartSnapshot.name.ilike(f'%{query}%'))
        items = q.limit(limit).all()
        results = [{'id': item.id, 'name': item.name, 'type': 'Org Chart Snapshot'} for item in items]
    
    return jsonify(results)


# --- Export Defense Pack ---

@audits_bp.route('/<int:id>/export-pack', methods=['POST'])
@login_required
@requires_permission(MODULE)
def export_defense_pack(id):
    """
    Generate and download a complete defense pack for an audit.

    This creates a ZIP file containing:
    - Main report document
    - Evidence documents organized by control
    - All attachments
    - External links manifest
    """
    from ..services.audit_export_service import export_audit_pack
    from flask import send_file
    import os

    db.get_or_404(ComplianceAudit, id)  # 404s on an unknown audit

    try:
        # Generate the export pack
        zip_path, stats = export_audit_pack(id)

        # Send the file to the user
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=os.path.basename(zip_path),
            mimetype='application/zip'
        )

    except Exception as e:
        flash(f'Error generating defense pack: {str(e)}', 'danger')
        return redirect(url_for('audits.audit_detail', id=id))
