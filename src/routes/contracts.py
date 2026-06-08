from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from datetime import datetime
from ..models import db
from ..models.contracts import Contract, ContractItem
from ..models.procurement import Supplier
from ..models.assets import Asset
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

contracts_bp = Blueprint('contracts', __name__)

@contracts_bp.route('/', methods=['GET'])
@login_required
@requires_permission('procurement')
def list_contracts():
    status_filter = request.args.get('status')
    
    query = Contract.query
    
    if status_filter:
        if status_filter == 'Expired':
             # Filter by status "Expired" OR dynamically calculated expiry
             query = query.filter((Contract.status == 'Expired') | (Contract.end_date < datetime.today().date()))
        else:
             query = query.filter(Contract.status == status_filter)
    
    contracts = query.order_by(Contract.end_date.asc()).all()
    
    return render_template('contracts/list.html', contracts=contracts, filter=status_filter)

@contracts_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement')
def new_contract():
    if request.method == 'POST':
        if not has_write_permission('procurement'):
            flash('Write access required to create contracts.', 'danger')
            return redirect(url_for('contracts.list_contracts'))
        try:
            name = request.form['name']
            contract_type = request.form['contract_type']
            supplier_id = request.form['supplier_id']
            status = request.form['status']
            
            # Dates
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
            
            # Financials
            cost = float(request.form.get('cost', 0))
            currency = request.form.get('currency', 'EUR')
            payment_frequency = request.form.get('payment_frequency')
            
            # Lifecycle
            notice_period_days = int(request.form.get('notice_period_days', 30))
            is_auto_renew = 'is_auto_renew' in request.form
            
            description = request.form.get('description')
            contact_email = request.form.get('contact_email')
            
            contract = Contract(
                name=name,
                contract_type=contract_type,
                supplier_id=supplier_id,
                status=status,
                start_date=start_date,
                end_date=end_date,
                cost=cost,
                currency=currency,
                payment_frequency=payment_frequency,
                notice_period_days=notice_period_days,
                is_auto_renew=is_auto_renew,
                renewal_notes=request.form.get('renewal_notes'),
                description=description,
                contact_email=contact_email
            )
            
            db.session.add(contract)
            db.session.commit()
            
            flash('Contract created successfully.', 'success')
            return redirect(url_for('contracts.contract_detail', id=contract.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating contract: {str(e)}', 'danger')
            
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('contracts/detail.html', contract=None, suppliers=suppliers)

@contracts_bp.route('/<int:id>', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement')
def contract_detail(id):
    contract = db.get_or_404(Contract, id)
    
    if request.method == 'POST':
        # Handle Edit
        if not has_write_permission('procurement'):
            flash('Write access required to update contracts.', 'danger')
            return redirect(url_for('contracts.contract_detail', id=id))
        try:
            contract.name = request.form['name']
            contract.contract_type = request.form['contract_type']
            contract.supplier_id = request.form['supplier_id']
            contract.status = request.form['status']
            
            contract.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            contract.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
            
            contract.cost = float(request.form.get('cost', 0))
            contract.currency = request.form.get('currency', 'EUR')
            contract.payment_frequency = request.form.get('payment_frequency')
            
            contract.notice_period_days = int(request.form.get('notice_period_days', 30))
            contract.is_auto_renew = 'is_auto_renew' in request.form
            contract.renewal_notes = request.form.get('renewal_notes')
            contract.description = request.form.get('description')
            contract.contact_email = request.form.get('contact_email')
            
            db.session.commit()
            flash('Contract updated successfully.', 'success')
            return redirect(url_for('contracts.contract_detail', id=contract.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating contract: {str(e)}', 'danger')

    suppliers = Supplier.query.order_by(Supplier.name).all()
    
    # Pre-fetch linked items for display (could optimize with specific queries if needed)
    linked_items = []
    for item in contract.items:
        obj = item.item
        if obj:
            linked_items.append({
                'id': item.id, # The link ID, for deletion
                'type': item.item_type,
                'name': getattr(obj, 'name', 'Unknown Item'),
                'obj_id': obj.id,
                'url': _get_item_url(item.item_type, obj.id)
            })

    return render_template('contracts/detail.html', 
                           contract=contract, 
                           suppliers=suppliers,
                           linked_items=linked_items)

@contracts_bp.route('/<int:id>/link', methods=['POST'])
@login_required
@requires_permission('procurement')
def link_item(id):
    if not has_write_permission('procurement'):
        flash('Write access required to link items.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=id))
    contract = db.get_or_404(Contract, id)
    item_type = request.form.get('item_type') # 'Asset', 'Subscription', etc.
    item_id = request.form.get('item_id')
    
    if not item_type or not item_id:
        flash('Missing item type or ID.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=id))

    # Verify item exists
    item_class = _get_model_class(item_type)
    if not item_class:
        flash('Invalid item type.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=id))
        
    obj = db.session.get(item_class,item_id)
    if not obj:
        flash(f'{item_type} with ID {item_id} not found.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=id))

    # Check for existing link
    existing = ContractItem.query.filter_by(
        contract_id=contract.id,
        item_type=item_type,
        item_id=item_id
    ).first()
    
    if existing:
        flash('Item already linked to this contract.', 'info')
    else:
        link = ContractItem(contract_id=contract.id, item_type=item_type, item_id=item_id)
        db.session.add(link)
        db.session.commit()
        flash('Item linked successfully.', 'success')
    
    return redirect(url_for('contracts.contract_detail', id=id))

@contracts_bp.route('/link/<int:link_id>/delete', methods=['POST'])
@login_required
@requires_permission('procurement')
def unlink_item(link_id):
    if not has_write_permission('procurement'):
        link = db.get_or_404(ContractItem, link_id)
        flash('Write access required to unlink items.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=link.contract_id))
    link = db.get_or_404(ContractItem, link_id)
    contract_id = link.contract_id
    db.session.delete(link)
    db.session.commit()
    flash('Item unlinked.', 'success')
    return redirect(url_for('contracts.contract_detail', id=contract_id))

@contracts_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission('procurement')
def delete_contract(id):
    if not has_write_permission('procurement'):
        flash('Write access required to delete contracts.', 'danger')
        return redirect(url_for('contracts.contract_detail', id=id))
    contract = db.get_or_404(Contract, id)
    db.session.delete(contract)
    db.session.commit()
    flash('Contract deleted.', 'success')
    return redirect(url_for('contracts.list_contracts'))

# --- Helpers ---

def _get_model_class(item_type):
    from ..models.assets import Asset, License
    from ..models.procurement import Subscription
    from ..models.services import BusinessService
    
    mapping = {
        'Asset': Asset,
        'Subscription': Subscription,
        'License': License,
        'BusinessService': BusinessService
    }
    return mapping.get(item_type)

def _get_item_url(item_type, item_id):
    if item_type == 'Asset':
        return url_for('assets.asset_detail', id=item_id)
    elif item_type == 'Subscription':
        return url_for('subscriptions.subscription_detail', id=item_id)
    elif item_type == 'License':
        return url_for('licenses.list_licenses') # License detail might be a modal or list
    elif item_type == 'BusinessService':
        return url_for('services.detail', id=item_id)
    return '#'

@contracts_bp.route('/search-items', methods=['GET'])
@login_required
@requires_permission('procurement')
def search_items():
    """
    JSON endpoint for Select2 AJAX search.
    Expects args:
      - type: 'Asset', 'Subscription', 'License', 'BusinessService'
      - q: search term
    Returns:
      [{'id': 123, 'text': 'Name (Serial...)'}, ...]
    """
    item_type = request.args.get('type')
    search_term = request.args.get('q', '').strip()
    
    if not item_type or not search_term:
        return {'results': []}

    results = []
    
    # helper to format
    def fmt(id, text, extra=None):
        display = text
        if extra:
            display += f" ({extra})"
        return {'id': id, 'text': display}

    if item_type == 'Asset':
        # Search by name, serial, or internal_id
        from ..models.assets import Asset
        query = Asset.query.filter(
            (Asset.name.ilike(f'%{search_term}%')) |
            (Asset.serial_number.ilike(f'%{search_term}%')) |
            (Asset.internal_id.ilike(f'%{search_term}%'))
        ).filter_by(is_archived=False).limit(20)
        
        for asset in query:
            extra = asset.serial_number or asset.internal_id or "No Serial"
            results.append(fmt(asset.id, asset.name, extra))

    elif item_type == 'Subscription':
        from ..models.procurement import Subscription
        query = Subscription.query.filter(
            Subscription.name.ilike(f'%{search_term}%')
        ).filter_by(is_archived=False).limit(20)
        
        for sub in query:
            results.append(fmt(sub.id, sub.name, sub.subscription_type))

    elif item_type == 'License':
        from ..models.assets import License
        query = License.query.filter(
            (License.name.ilike(f'%{search_term}%')) |
            (License.license_key.ilike(f'%{search_term}%'))
        ).filter_by(is_archived=False).limit(20)
        
        for lic in query:
            results.append(fmt(lic.id, lic.name, "License"))

    elif item_type == 'BusinessService':
        from ..models.services import BusinessService
        # services usually don't have is_archived, checking status instead if needed, 
        # or just filtering by name
        query = BusinessService.query.filter(
            BusinessService.name.ilike(f'%{search_term}%')
        ).limit(20)
        
        for svc in query:
            results.append(fmt(svc.id, svc.name, svc.status))

    return {'results': results}
