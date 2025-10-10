from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from ..models import db, Asset, Peripheral, DisposalRecord, DisposalHistory
from .main import login_required
from .admin import admin_required

disposal_bp = Blueprint('disposal', __name__, url_prefix='/disposal')

@disposal_bp.route('/')
@login_required
def list_disposals():
    """A list view that shows only computer disposals for audit purposes."""
    disposal_records = DisposalRecord.query.order_by(DisposalRecord.disposal_date.desc()).all()
    return render_template('disposal/list.html', records=disposal_records)

@disposal_bp.route('/<int:id>')
@login_required
def disposal_detail(id):
    """Shows the details of a single disposal record."""
    record = DisposalRecord.query.get_or_404(id)
    return render_template('disposal/detail.html', record=record)

@disposal_bp.route('/record', methods=['GET', 'POST'])
@login_required
@admin_required
def record_disposal():
    asset_id = request.args.get('asset_id')
    peripheral_id = request.args.get('peripheral_id')
    item = None
    
    if asset_id:
        item = Asset.query.get_or_404(asset_id)
    elif peripheral_id:
        item = Peripheral.query.get_or_404(peripheral_id)
    else:
        return "No asset or peripheral specified", 400

    if request.method == 'POST':
        record = DisposalRecord(
            disposal_date=datetime.strptime(request.form['disposal_date'], '%Y-%m-%d').date(),
            disposal_method=request.form['disposal_method'],
            disposal_partner=request.form.get('disposal_partner'),
            notes=request.form.get('notes')
        )
        
        item.status = 'Disposed'
        item.is_archived = True
        
        if isinstance(item, Asset):
            record.asset_id = item.id
        else:
            record.peripheral_id = item.id
            
        db.session.add(record)
        db.session.commit() # Commit here to get the record.id

        # Handle file upload for the certificate
        if 'certificate' in request.files and request.files['certificate'].filename != '':
             # This is a simplified redirect. A more robust solution would be a helper function.
            return redirect(url_for('attachments.upload_file', disposal_record_id=record.id, _method='POST', **request.files))
        
        flash(f'"{item.name}" has been marked as disposed and archived.', 'success')
        
        if isinstance(item, Asset):
            return redirect(url_for('assets.assets'))
        else:
            return redirect(url_for('peripherals.peripherals'))

    return render_template('disposal/form.html', item=item)

@disposal_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_disposal(id):
    record = DisposalRecord.query.get_or_404(id)
    item = record.asset or record.peripheral

    if request.method == 'POST':
        user_id = session.get('user_id')
        reason = request.form.get('reason')

        if not reason:
            flash('A reason for the change is required.', 'danger')
            return render_template('disposal/edit_form.html', record=record, item=item)

        changes = []
        
        # Compare and track changes
        new_date = datetime.strptime(request.form['disposal_date'], '%Y-%m-%d').date()
        if record.disposal_date != new_date:
            changes.append(('Date', record.disposal_date.strftime('%Y-%m-%d'), new_date.strftime('%Y-%m-%d')))
            record.disposal_date = new_date

        if record.disposal_method != request.form['disposal_method']:
            changes.append(('Method', record.disposal_method, request.form['disposal_method']))
            record.disposal_method = request.form['disposal_method']

        if record.disposal_partner != request.form.get('disposal_partner'):
            changes.append(('Partner', record.disposal_partner, request.form.get('disposal_partner')))
            record.disposal_partner = request.form.get('disposal_partner')
            
        if record.notes != request.form.get('notes'):
            changes.append(('Notes', record.notes, request.form.get('notes')))
            record.notes = request.form.get('notes')

        # Create history entries for each change
        for field, old_val, new_val in changes:
            history_entry = DisposalHistory(
                disposal_id=id,
                field_changed=field,
                old_value=old_val,
                new_value=new_val,
                reason=reason,
                changed_by_id=user_id
            )
            db.session.add(history_entry)
        
        db.session.commit()
        
        # Handle file upload for the certificate
        if 'certificate' in request.files and request.files['certificate'].filename != '':
             return redirect(url_for('attachments.upload_file', disposal_record_id=record.id, _method='POST', **request.files))
        
        flash('Disposal record updated successfully.', 'success')
        return redirect(url_for('disposal.disposal_detail', id=id))

    return render_template('disposal/edit_form.html', record=record, item=item)