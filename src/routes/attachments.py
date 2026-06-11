import os
import uuid
from flask import (
    Blueprint, request, redirect, flash, current_app, send_from_directory
)
from werkzeug.utils import secure_filename
from .main import login_required
from ..models import db, Attachment
from ..services.permissions_service import has_write_permission, requires_permission
from ..utils.redirects import safe_redirect_target

attachments_bp = Blueprint('attachments', __name__)

@attachments_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(safe_redirect_target(request.referrer))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(safe_redirect_target(request.referrer))

    if file:
        original_filename = secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"

        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))

        
        # Determine the permission key based on the target object
        perm_key = None
        if request.form.get('asset_id'):
            perm_key = 'core_inventory'
            linkable_id = request.form.get('asset_id')
            linkable_type = 'Asset'
        elif request.form.get('contract_id'):
            perm_key = 'procurement'
            linkable_id = request.form.get('contract_id')
            linkable_type = 'Contract'
        elif request.form.get('subscription_id'):
            perm_key = 'core_inventory' # Subscriptions are in Core Inventory in sidebar
            linkable_id = request.form.get('subscription_id')
            linkable_type = 'Subscription'
        elif request.form.get('supplier_id'):
            perm_key = 'procurement'
            linkable_id = request.form.get('supplier_id')
            linkable_type = 'Supplier'
        elif request.form.get('purchase_id'):
            perm_key = 'finance'
            linkable_id = request.form.get('purchase_id')
            linkable_type = 'Purchase'
        elif request.form.get('peripheral_id'):
            perm_key = 'core_inventory'
            linkable_id = request.form.get('peripheral_id')
            linkable_type = 'Peripheral'
        elif request.form.get('policy_id'):
            perm_key = 'knowledge_policy'
            linkable_id = request.form.get('policy_id')
            linkable_type = 'Policy'
        elif request.form.get('policy_version_id'):
            perm_key = 'knowledge_policy'
            linkable_id = request.form.get('policy_version_id')
            linkable_type = 'PolicyVersion'
        elif request.form.get('security_assessment_id'):
            perm_key = 'compliance'
            linkable_id = request.form.get('security_assessment_id')
            linkable_type = 'SecurityAssessment'
        elif request.form.get('risk_id'):
            perm_key = 'risk_governance'
            linkable_id = request.form.get('risk_id')
            linkable_type = 'Risk'
        elif request.form.get('bcdr_test_log_id'):
            perm_key = 'operations'
            linkable_id = request.form.get('bcdr_test_log_id')
            linkable_type = 'BCDRTestLog'        
        elif request.form.get('maintenance_log_id'):
            perm_key = 'operations'
            linkable_id = request.form.get('maintenance_log_id')
            linkable_type = 'MaintenanceLog'
        elif request.form.get('disposal_record_id'):
            perm_key = 'operations'
            linkable_id = request.form.get('disposal_record_id')
            linkable_type = 'DisposalRecord'
        elif request.form.get('course_completion_id'):
            perm_key = 'knowledge_policy'
            linkable_id = request.form.get('course_completion_id')
            linkable_type = 'CourseCompletion'
        elif request.form.get('security_incident_id'):
            perm_key = 'operations'
            linkable_id = request.form.get('security_incident_id')
            linkable_type = 'SecurityIncident'
        
        if not perm_key or not has_write_permission(perm_key):
            flash('Write access required to upload files for this object.', 'danger')
            return redirect(safe_redirect_target(request.referrer))

        # Create the attachment
        new_attachment = Attachment(
            filename=original_filename,
            secure_filename=unique_filename,
            linkable_id=linkable_id,
            linkable_type=linkable_type
        )

        db.session.add(new_attachment)
        db.session.commit()
        flash('File uploaded successfully!', 'success')

    return redirect(safe_redirect_target(request.referrer))

@attachments_bp.route('/download/<int:attachment_id>', methods=['GET'])
@login_required
def download_file(attachment_id):
    """
    Provides a secure download link for an attachment.
    """
    attachment = db.get_or_404(Attachment, attachment_id)

    # Send the file from the upload folder
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        attachment.secure_filename,
        # Use the original filename as the download name
        download_name=attachment.filename,
        as_attachment=True
    )

@attachments_bp.route('/delete/<int:attachment_id>', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    """
    Deletes an attachment from the filesystem and the database.
    """
    attachment = db.get_or_404(Attachment, attachment_id)

    # Check permissions based on the linked object
    type_to_perm = {
        'Asset': 'core_inventory',
        'Contract': 'procurement',
        'Subscription': 'core_inventory',
        'Supplier': 'procurement',
        'Purchase': 'finance',
        'Peripheral': 'core_inventory',
        'Policy': 'knowledge_policy',
        'PolicyVersion': 'knowledge_policy',
        'SecurityAssessment': 'compliance',
        'Risk': 'risk_governance',
        'BCDRTestLog': 'operations',
        'MaintenanceLog': 'operations',
        'DisposalRecord': 'operations',
        'CourseCompletion': 'knowledge_policy',
        'SecurityIncident': 'operations',
        'Change': 'operations'
    }
    
    perm_key = type_to_perm.get(attachment.linkable_type)
    if not perm_key or not has_write_permission(perm_key):
        flash('Write access required to delete this attachment.', 'danger')
        return redirect(safe_redirect_target(request.referrer))
    
    # Store filename before deleting the DB record
    secure_filename_to_delete = attachment.secure_filename
    
    try:
        # Delete the database record
        db.session.delete(attachment)
        db.session.commit()
        
        # Delete the file from the filesystem
        try:
            os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], secure_filename_to_delete))
        except OSError as e:
            # Log this error, but don't block the user
            current_app.logger.error(f"Error deleting file {secure_filename_to_delete}: {e}")
            flash('File record deleted, but the physical file could not be removed.', 'warning')
            return redirect(safe_redirect_target(request.referrer))

        flash('Attachment deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting attachment record {attachment_id}: {e}")
        flash('An error occurred while deleting the attachment.', 'danger')

    return redirect(safe_redirect_target(request.referrer))