from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from ..models import db, Asset, Peripheral, DisposalRecord, DisposalHistory, Supplier
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

disposal_bp = Blueprint('disposal', __name__, url_prefix='/disposal')

@disposal_bp.route('/', methods=['GET'])
@login_required
@requires_permission('operations')
def list_disposals():
    """A list view that shows only computer disposals for audit purposes."""
    disposal_records = DisposalRecord.query.order_by(DisposalRecord.disposal_date.desc()).all()
    return render_template('disposal/list.html', records=disposal_records)

@disposal_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission('operations')
def disposal_detail(id):
    """Shows the details of a single disposal record."""
    record = db.get_or_404(DisposalRecord, id)
    return render_template('disposal/detail.html', record=record)

@disposal_bp.route('/record', methods=['GET', 'POST'])
@login_required
@requires_permission('operations')
def record_disposal():
    if request.method == 'POST':
        if not has_write_permission('operations'):
            flash('Write access required to record disposals.', 'danger')
            return redirect(url_for('disposal.list_disposals'))
    asset_id = request.args.get('asset_id')
    peripheral_id = request.args.get('peripheral_id')
    item = None
    
    if asset_id:
        item = db.get_or_404(Asset, asset_id)
    elif peripheral_id:
        item = db.get_or_404(Peripheral, peripheral_id)
    else:
        return "No asset or peripheral specified", 400

    if request.method == 'POST':
        record = DisposalRecord(
            disposal_date=datetime.strptime(request.form['disposal_date'], '%Y-%m-%d').date(),
            disposal_method=request.form['disposal_method'],
            disposal_partner_id=request.form.get('disposal_partner_id') or None,
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

    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    return render_template('disposal/form.html', item=item, suppliers=suppliers)

@disposal_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission('operations')
def edit_disposal(id):
    record = db.get_or_404(DisposalRecord, id)
    item = record.asset or record.peripheral

    if request.method == 'POST':
        if not has_write_permission('operations'):
            flash('Write access required to update disposal records.', 'danger')
            return redirect(url_for('disposal.disposal_detail', id=id))
        user_id = session.get('user_id')
        reason = request.form.get('reason')

        if not reason:
            flash('A reason for the change is required.', 'danger')
            return render_template('disposal/edit_form.html', record=record, item=item,
                               suppliers=Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all())

        changes = []
        
        # Compare and track changes
        new_date = datetime.strptime(request.form['disposal_date'], '%Y-%m-%d').date()
        if record.disposal_date != new_date:
            changes.append(('Date', record.disposal_date.strftime('%Y-%m-%d'), new_date.strftime('%Y-%m-%d')))
            record.disposal_date = new_date

        if record.disposal_method != request.form['disposal_method']:
            changes.append(('Method', record.disposal_method, request.form['disposal_method']))
            record.disposal_method = request.form['disposal_method']

        new_partner_id = request.form.get('disposal_partner_id') or None
        new_partner_id = int(new_partner_id) if new_partner_id else None
        if record.disposal_partner_id != new_partner_id:
            old_name = record.disposal_partner.name if record.disposal_partner else None
            new_supplier = db.session.get(Supplier, new_partner_id) if new_partner_id else None
            changes.append(('Partner', old_name, new_supplier.name if new_supplier else None))
            record.disposal_partner_id = new_partner_id
            
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