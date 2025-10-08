import os
import uuid
from flask import (
    Blueprint, request, redirect, flash, current_app, send_from_directory
)
from werkzeug.utils import secure_filename
from ..models import db, Attachment
from .main import login_required

attachments_bp = Blueprint('attachments', __name__)

@attachments_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    service_id = request.form.get('service_id')
    supplier_id = request.form.get('supplier_id')
    purchase_id = request.form.get('purchase_id')
    asset_id = request.form.get('asset_id')
    peripheral_id = request.form.get('peripheral_id')

    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.referrer)

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.referrer)

    if file:
        original_filename = secure_filename(file.filename)
        file_ext = os.path.splitext(original_filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"

        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))

        new_attachment = Attachment(
            filename=original_filename,
            secure_filename=unique_filename,
            service_id=service_id if service_id else None,
            supplier_id=supplier_id if supplier_id else None,
            purchase_id=purchase_id if purchase_id else None,
            asset_id=asset_id if asset_id else None,
            peripheral_id=peripheral_id if peripheral_id else None
        )
        db.session.add(new_attachment)
        db.session.commit()
        flash('File uploaded successfully!')

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

    os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], attachment.secure_filename))

    db.session.delete(attachment)
    db.session.commit()
    flash('Attachment deleted successfully.')
    return redirect(request.referrer)