import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app, Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from ..models import db, MaintenanceLog, Asset, Peripheral, User, Attachment # Added Attachment
from .main import login_required
from .admin import admin_required

maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/maintenance')

@maintenance_bp.route('/')
@login_required
def list_logs():
    logs = MaintenanceLog.query.order_by(MaintenanceLog.event_date.desc()).all()
    return render_template('maintenance/list.html', logs=logs)

@maintenance_bp.route('/<int:id>')
@login_required
def log_detail(id):
    log = MaintenanceLog.query.get_or_404(id)
    return render_template('maintenance/detail.html', log=log)

@maintenance_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_log():
    if request.method == 'POST':
        log = MaintenanceLog(
            event_type=request.form['event_type'],
            description=request.form['description'],
            status=request.form['status'],
            event_date=datetime.strptime(request.form['event_date'], '%Y-%m-%d').date(),
            ticket_link=request.form.get('ticket_link'),
            notes=request.form.get('notes'),
            assigned_to_id=request.form.get('assigned_to_id') or None,
            asset_id=request.form.get('asset_id') or None,
            peripheral_id=request.form.get('peripheral_id') or None
        )
        db.session.add(log)
        db.session.commit()

        # Handle File Upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                
                attachment = Attachment(
                    filename=original_filename,
                    secure_filename=unique_filename,
                    linkable_type='MaintenanceLog',
                    linkable_id=log.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash('Maintenance log created successfully.', 'success')
        return redirect(url_for('maintenance.log_detail', id=log.id))

    # Pre-select asset or peripheral for query params if available
    preselected_asset_id = request.args.get('asset_id', type=int)
    preselected_peripheral_id = request.args.get('peripheral_id', type=int)
    event_type = request.args.get('event_type')
    
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    peripherals = Peripheral.query.filter_by(is_archived=False).order_by(Peripheral.name).all()

    return render_template('maintenance/form.html',
                        users=users,
                        assets=assets,
                        peripherals=peripherals,
                        preselected_asset_id=preselected_asset_id,
                        preselected_peripheral_id=preselected_peripheral_id,
                        event_type=event_type)

@maintenance_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_log(id):
    log = MaintenanceLog.query.get_or_404(id)
    if request.method == 'POST':
        log.event_type = request.form['event_type']
        log.description = request.form['description']
        log.status = request.form['status']
        log.event_date = datetime.strptime(request.form['event_date'], '%Y-%m-%d').date()
        log.ticket_link = request.form.get('ticket_link')
        log.notes = request.form.get('notes')
        log.assigned_to_id = request.form.get('assigned_to_id') or None
        log.asset_id = request.form.get('asset_id') or None
        log.peripheral_id = request.form.get('peripheral_id') or None
        
        # Handle File Upload
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                
                attachment = Attachment(
                    filename=original_filename,
                    secure_filename=unique_filename,
                    linkable_type='MaintenanceLog',
                    linkable_id=log.id
                )
                db.session.add(attachment)

        db.session.commit()
        flash('Maintenance log updated successfully.', 'success')
        return redirect(url_for('maintenance.log_detail', id=log.id))

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    peripherals = Peripheral.query.filter_by(is_archived=False).order_by(Peripheral.name).all()
    
    return render_template('maintenance/form.html',
                           log=log,
                           users=users,
                           assets=assets,
                           peripherals=peripherals)