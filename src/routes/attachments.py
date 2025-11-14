import os
import uuid
from flask import (
    Blueprint, request, redirect, flash, current_app, send_from_directory, url_for
)
from werkzeug.utils import secure_filename
from .main import login_required
from ..models import db, Attachment

attachments_bp = Blueprint('attachments', __name__)

@attachments_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(request.referrer)

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'warning')
        return redirect(request.referrer)

    if file:
        original_filename = secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"

        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))

        
        # Create the attachment without the old, invalid FKs
        new_attachment = Attachment(
            filename=original_filename,
            secure_filename=unique_filename
        )

        # Find the parent object from the submitted form data and set the
        # new polymorphic columns. This handles all 14 classes.
        
        if request.form.get('asset_id'):
            new_attachment.linkable_id = request.form.get('asset_id')
            new_attachment.linkable_type = 'Asset'
        elif request.form.get('subscription_id'):
            new_attachment.linkable_id = request.form.get('subscription_id')
            new_attachment.linkable_type = 'Subscription'
        elif request.form.get('supplier_id'):
            new_attachment.linkable_id = request.form.get('supplier_id')
            new_attachment.linkable_type = 'Supplier'
        elif request.form.get('purchase_id'):
            new_attachment.linkable_id = request.form.get('purchase_id')
            new_attachment.linkable_type = 'Purchase'
        elif request.form.get('peripheral_id'):
            new_attachment.linkable_id = request.form.get('peripheral_id')
            new_attachment.linkable_type = 'Peripheral'
        elif request.form.get('policy_id'):
            new_attachment.linkable_id = request.form.get('policy_id')
            new_attachment.linkable_type = 'Policy'
        elif request.form.get('policy_version_id'):
            new_attachment.linkable_id = request.form.get('policy_version_id')
            new_attachment.linkable_type = 'PolicyVersion'
        elif request.form.get('security_assessment_id'):
            new_attachment.linkable_id = request.form.get('security_assessment_id')
            new_attachment.linkable_type = 'SecurityAssessment'
        elif request.form.get('risk_id'):
            new_attachment.linkable_id = request.form.get('risk_id')
            new_attachment.linkable_type = 'Risk'
        elif request.form.get('bcdr_test_log_id'):
            new_attachment.linkable_id = request.form.get('bcdr_test_log_id')
            new_attachment.linkable_type = 'BCDRTestLog'        
        elif request.form.get('maintenance_log_id'):
            new_attachment.linkable_id = request.form.get('maintenance_log_id')
            new_attachment.linkable_type = 'MaintenanceLog'
        elif request.form.get('disposal_record_id'):
            new_attachment.linkable_id = request.form.get('disposal_record_id')
            new_attachment.linkable_type = 'DisposalRecord'
        elif request.form.get('course_completion_id'):
            new_attachment.linkable_id = request.form.get('course_completion_id')
            new_attachment.linkable_type = 'CourseCompletion'
        elif request.form.get('security_incident_id'):
            new_attachment.linkable_id = request.form.get('security_incident_id')
            new_attachment.linkable_type = 'SecurityIncident'
        
        else:
            flash('Error: Could not determine what to link this attachment to.', 'danger')
            # Don't save the file or DB record if we don't know the parent
            try:
                os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
            except OSError:
                pass # File might not exist, but we must not proceed
            return redirect(request.referrer)

        db.session.add(new_attachment)
        db.session.commit()
        flash('File uploaded successfully!', 'success')

    return redirect(request.referrer)

@attachments_bp.route('/download/<int:attachment_id>')
@login_required
def download_file(attachment_id):
    """
    Provides a secure download link for an attachment.
    """
    attachment = Attachment.query.get_or_404(attachment_id)
    
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
    attachment = Attachment.query.get_or_404(attachment_id)
    
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
            return redirect(request.referrer)

        flash('Attachment deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting attachment record {attachment_id}: {e}")
        flash('An error occurred while deleting the attachment.', 'danger')

    return redirect(request.referrer)