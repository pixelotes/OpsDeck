from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from ..models import db, Asset, Peripheral, DisposalRecord
from .main import login_required
from .admin import admin_required

disposal_bp = Blueprint('disposal', __name__, url_prefix='/disposal')

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
        db.session.commit()
        
        flash(f'"{item.name}" has been marked as disposed and archived.', 'success')
        
        if isinstance(item, Asset):
            return redirect(url_for('assets.assets'))
        else:
            return redirect(url_for('peripherals.peripherals'))

    return render_template('disposal/form.html', item=item)