# src/routes/cost_centers.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..extensions import db
from ..models.core import CostCenter
from ..models.services import BusinessService
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

cost_centers_bp = Blueprint('cost_centers', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'finance'
DETAIL = 'cost_centers.detail'
COST_CENTERS_FORM_HTML = 'cost_centers/form.html'

@cost_centers_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_cost_centers():
    """List all cost centers."""
    cost_centers = CostCenter.query.order_by(CostCenter.code).all()
    
    # Add service count to each cost center
    for cc in cost_centers:
        cc.service_count = len(cc.services)
    
    return render_template('cost_centers/list.html', cost_centers=cost_centers)


@cost_centers_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_cost_center():
    """Create a new cost center."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('cost_centers.list_cost_centers'))
        code = request.form.get('code', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        # Validation
        if not code:
            flash('Code is required.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=None)
        
        if not name:
            flash('Name is required.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=None)
        
        # Check for duplicate code
        existing = CostCenter.query.filter_by(code=code).first()
        if existing:
            flash(f'A cost center with code "{code}" already exists.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=None)
        
        # Create new cost center
        cost_center = CostCenter(
            code=code,
            name=name,
            description=description if description else None
        )
        
        db.session.add(cost_center)
        db.session.commit()
        
        flash(f'Cost center "{code}" created successfully.', 'success')
        return redirect(url_for(DETAIL, id=cost_center.id))
    
    return render_template(COST_CENTERS_FORM_HTML, cost_center=None)


@cost_centers_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def detail(id):
    """Display cost center details."""
    cost_center = db.get_or_404(CostCenter, id)
    
    # Get associated services
    services = BusinessService.query.filter_by(cost_center_id=id).order_by(BusinessService.name).all()
    
    return render_template('cost_centers/detail.html', cost_center=cost_center, services=services)


@cost_centers_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit(id):
    """Edit an existing cost center."""
    cost_center = db.get_or_404(CostCenter, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(DETAIL, id=id))
        code = request.form.get('code', '').strip()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        
        # Validation
        if not code:
            flash('Code is required.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=cost_center)
        
        if not name:
            flash('Name is required.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=cost_center)
        
        # Check for duplicate code (excluding current cost center)
        existing = CostCenter.query.filter(
            CostCenter.code == code,
            CostCenter.id != id
        ).first()
        if existing:
            flash(f'A cost center with code "{code}" already exists.', 'danger')
            return render_template(COST_CENTERS_FORM_HTML, cost_center=cost_center)
        
        # Update cost center
        cost_center.code = code
        cost_center.name = name
        cost_center.description = description if description else None
        
        db.session.commit()
        
        flash(f'Cost center "{code}" updated successfully.', 'success')
        return redirect(url_for(DETAIL, id=cost_center.id))
    
    return render_template(COST_CENTERS_FORM_HTML, cost_center=cost_center)


@cost_centers_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete(id):
    """Delete a cost center."""
    cost_center = db.get_or_404(CostCenter, id)
    
    # Check if any services are associated
    service_count = BusinessService.query.filter_by(cost_center_id=id).count()
    if service_count > 0:
        flash(f'Cannot delete cost center "{cost_center.code}" because it has {service_count} associated service(s). Please reassign or remove the services first.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    
    code = cost_center.code
    db.session.delete(cost_center)
    db.session.commit()
    
    flash(f'Cost center "{code}" deleted successfully.', 'success')
    return redirect(url_for('cost_centers.list_cost_centers'))
