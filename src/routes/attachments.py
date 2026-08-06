import os
import uuid
from flask import (
    Blueprint, request, redirect, flash, current_app, send_from_directory, session, abort
)
from werkzeug.utils import secure_filename
from .main import login_required
from ..models import db, Attachment
from ..services.permissions_service import has_write_permission, user_has_module_access
from ..utils.redirects import safe_redirect_target

attachments_bp = Blueprint('attachments', __name__)

# Which module governs an attachment, by the type of object it hangs off. Every
# linkable_type in use must appear here: the three routes below resolve access through
# this map, and an unlisted type is refused rather than waved through. Slugs come from
# the MODULE constant of the blueprint that owns each object.
ATTACHMENT_PERMISSIONS = {
    'ActivityExecution': 'operations',
    'Asset': 'core_inventory',
    'AuditControlItem': 'compliance',
    'BCDRPlan': 'operations',
    'BCDRTestLog': 'operations',
    'BusinessService': 'core_inventory',
    'Change': 'operations',
    'ComplianceAudit': 'compliance',
    'Contract': 'procurement',
    'CourseCompletion': 'knowledge_policy',
    'DisposalRecord': 'operations',
    'Documentation': 'knowledge_policy',
    'MaintenanceLog': 'operations',
    'Peripheral': 'core_inventory',
    'Policy': 'knowledge_policy',
    'PolicyVersion': 'knowledge_policy',
    'Purchase': 'finance',
    'Request': 'operations',
    'Risk': 'risk_governance',
    'RiskAssessmentItem': 'risk_governance',
    'RoadmapInitiative': 'roadmaps',
    'SecurityAssessment': 'compliance',
    'SecurityIncident': 'operations',
    'Software': 'core_inventory',
    'Subscription': 'core_inventory',
    'Supplier': 'procurement',
    'User': 'administration',
}

# Form field carrying the target id -> the linkable_type it denotes. Checked in this
# order, first one present wins, mirroring what the upload form submits.
UPLOAD_TARGETS = {
    'asset_id': 'Asset',
    'contract_id': 'Contract',
    'subscription_id': 'Subscription',
    'supplier_id': 'Supplier',
    'purchase_id': 'Purchase',
    'peripheral_id': 'Peripheral',
    'policy_id': 'Policy',
    'policy_version_id': 'PolicyVersion',
    'security_assessment_id': 'SecurityAssessment',
    'risk_id': 'Risk',
    'bcdr_test_log_id': 'BCDRTestLog',
    'maintenance_log_id': 'MaintenanceLog',
    'disposal_record_id': 'DisposalRecord',
    'course_completion_id': 'CourseCompletion',
    'security_incident_id': 'SecurityIncident',
}


def _module_for(linkable_type):
    """Module slug governing `linkable_type`, or None if it is not recognised."""
    module = ATTACHMENT_PERMISSIONS.get(linkable_type)
    if module is None:
        # Worth a log line: it means an object type grew attachments without being
        # added here, and its users are now getting a 403 they cannot explain.
        current_app.logger.warning(
            'Attachment type %r has no module mapping; access refused.', linkable_type)
    return module


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

    if not file:
        return redirect(safe_redirect_target(request.referrer))

    # Work out the target and check permissions *before* touching the filesystem.
    # Saving first would let an unauthorised caller litter the upload folder with
    # files that never get an Attachment row, so nothing ever cleans them up.
    linkable_id = None
    linkable_type = None
    for field, target_type in UPLOAD_TARGETS.items():
        if request.form.get(field):
            linkable_id = request.form.get(field)
            linkable_type = target_type
            break

    perm_key = _module_for(linkable_type) if linkable_type else None
    if not perm_key or not has_write_permission(perm_key):
        flash('Write access required to upload files for this object.', 'danger')
        return redirect(safe_redirect_target(request.referrer))

    original_filename = secure_filename(file.filename)
    file_ext = os.path.splitext(original_filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))

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
    Serves an attachment to a user who has read access to the object it belongs to.

    The permission check is the point: being logged in used to be enough, so any
    account could walk the id space and pull down every attachment in the system —
    incident evidence, audit files, HR documents — regardless of which modules it was
    granted. Deletion has always checked; downloading did not.
    """
    attachment = db.get_or_404(Attachment, attachment_id)

    perm_key = _module_for(attachment.linkable_type)
    if not perm_key or not user_has_module_access(session.get('user_id'), perm_key):
        abort(403)

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

    perm_key = _module_for(attachment.linkable_type)
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
