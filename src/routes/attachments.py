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

        new_attachment = Attachment(
            filename=original_filename,
            secure_filename=unique_filename,
            service_id=request.form.get('service_id'),
            supplier_id=request.form.get('supplier_id'),
            purchase_id=request.form.get('purchase_id'),
            asset_id=request.form.get('asset_id'),
            peripheral_id=request.form.get('peripheral_id'),
            policy_id=request.form.get('policy_id'),
            policy_version_id=request.form.get('policy_version_id'),
            security_assessment_id=request.form.get('security_assessment_id'),
            risk_id=request.form.get('risk_id')
        )
        db.session.add(new_attachment)
        db.session.commit()
        flash('File uploaded successfully!', 'success')

    return redirect(request.referrer)


@attachments_bp.route('/download/<int:attachment_id>')
@login_required
def download_file(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)
    return send_from_directory(
        current_app.config['UPLOAD_FOLDER'],
        attachment.secure_filename,
        as_attachment=True,
        download_name=attachment.filename
    )

@attachments_bp.route('/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(attachment_id):
    attachment = Attachment.query.get_or_404(attachment_id)

    try:
        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.secure_filename))
    except OSError as e:
        flash(f'Error deleting file from disk: {e}', 'danger')

    db.session.delete(attachment)
    db.session.commit()
    flash('Attachment deleted successfully.', 'success')
    return redirect(request.referrer)