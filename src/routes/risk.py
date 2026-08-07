from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
)
from ..models import db, Risk, User, Asset, RiskCategory, RISK_CATEGORIES, RISK_CATEGORY_COLORS, RiskAffectedItem, ThreatType

from ..models.security import RiskReference, RiskCatalog, CatalogRisk
from ..models.activities import SecurityActivity
from ..models.auth import Group
from ..models.procurement import Subscription
from ..models.policy import Policy
from ..models.core import Documentation, Link
from datetime import datetime
from src.utils.logger import log_audit
from ..services.permissions_service import (requires_permission, has_write_permission,
                                           requires_permission_api)

risk_bp = Blueprint('risk', __name__)

# Duplicate dashboard route removed.

risk_bp = Blueprint('risk', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'risk_governance'
DETAIL = 'risk.detail'

@risk_bp.route('/', methods=['GET'])
@requires_permission(MODULE)
def list_risks():
    query = Risk.query

    # Filters
    status = request.args.get('status')
    if status:
        query = query.filter(Risk.status == status)

    strategy = request.args.get('strategy')
    if strategy:
        query = query.filter(Risk.treatment_strategy == strategy)

    owner_id = request.args.get('owner_id')
    if owner_id:
        query = query.filter(Risk.owner_id == owner_id)

    residual_impact = request.args.get('residual_impact', type=int)
    if residual_impact:
        query = query.filter(Risk.residual_impact == residual_impact)

    residual_likelihood = request.args.get('residual_likelihood', type=int)
    if residual_likelihood:
        query = query.filter(Risk.residual_likelihood == residual_likelihood)   

    # Filtered on the percentage for the same reason the ordering is: a raw minimum score
    # means something different on every matrix size. The parameter keeps its name and its
    # 1-100 reading, which on the default 5x5 is what it always was.
    min_score = request.args.get('min_score', type=int)
    if min_score:
        query = query.filter(
            (Risk.residual_impact * Risk.residual_likelihood * 100.0)
            >= (Risk.impact_levels * Risk.likelihood_levels * min_score)
        )

    # Threshold filters (both must be met) — used by the Organizational Health
    # dashboard to link to the exact set of risks that lower the health score.
    min_impact = request.args.get('min_impact', type=int)
    if min_impact:
        query = query.filter(Risk.residual_impact >= min_impact)

    min_likelihood = request.args.get('min_likelihood', type=int)
    if min_likelihood:
        query = query.filter(Risk.residual_likelihood >= min_likelihood)

    # Exclude closed/accepted risks (matches the health-score definition).
    if request.args.get('active_only'):
        query = query.filter(Risk.status != 'Closed', Risk.treatment_strategy != 'Accept')

    # Ordered in SQL by the product scaled to its own matrix, not by the raw product: a
    # register can hold risks measured on differently sized matrices, and 12 out of 16
    # outranks 15 out of 64. Computed rather than sorted in Python so pagination and the
    # database keep agreeing about what "the top" means.
    residual_percent = (
        Risk.residual_impact * Risk.residual_likelihood * 100.0
    ) / (Risk.impact_levels * Risk.likelihood_levels)

    risks = query.order_by(residual_percent.desc(), Risk.created_at.desc()).all()
    
    return render_template('risk/list.html', risks=risks)

@risk_bp.route('/dashboard', methods=['GET'])
@requires_permission(MODULE)
def dashboard():
    # 1. KPIs
    all_risks = Risk.query.all()
    total_risks = len(all_risks)
    
    critical_risks_count = sum(1 for r in all_risks if r.criticality_level == 'Critical')
    risk_exposure = sum(r.residual_score for r in all_risks)
    
    # Efficiency (avoid division by zero)
    total_reduction = sum(r.risk_reduction_percentage for r in all_risks)
    avg_efficiency = round(total_reduction / total_risks, 1) if total_risks > 0 else 0.0

    # 2. Charts Data
    
    # Strategy Distribution
    strategies = {}
    for r in all_risks:
        s = r.treatment_strategy or 'Undefined'
        strategies[s] = strategies.get(s, 0) + 1
    
    strategy_labels = list(strategies.keys())
    strategy_data = list(strategies.values())

    # --- TOP OWNERS (UPDATED for Clickability) ---
    # Group by (id, name) to preserve the ID for linking
    owners_map = {} 
    for r in all_risks:
        if r.owner:
            key = (r.owner.id, r.owner.name)
        else:
            key = (None, 'Unassigned')
        
        owners_map[key] = owners_map.get(key, 0) + 1
    
    # Sort by count desc and take top 5
    sorted_owners = sorted(owners_map.items(), key=lambda item: item[1], reverse=True)[:5]
    
    # Unpack into separate lists (names for labels, ids for links, counts for data)
    owner_labels = [item[0][1] for item in sorted_owners]
    owner_ids = [item[0][0] for item in sorted_owners]
    owner_data = [item[1] for item in sorted_owners]
    # ---------------------------------------------

    # Heatmap Data (Scatter Plot format: x=Likelihood, y=Impact)
    heatmap_map = {}
    
    for r in all_risks:
        x = r.residual_likelihood or 1
        y = r.residual_impact or 1
        coord = (x, y)
        
        if coord not in heatmap_map:
            heatmap_map[coord] = {'count': 0, 'titles': []}
        
        heatmap_map[coord]['count'] += 1
        heatmap_map[coord]['titles'].append(r.risk_description)

    heatmap_data = []
    for (x, y), data in heatmap_map.items():
        tooltip_text = f"{data['count']} Risks:\n" + "\n".join([f"- {t}" for t in data['titles'][:5]])
        if len(data['titles']) > 5:
            tooltip_text += f"\n...and {len(data['titles']) - 5} more"

        heatmap_data.append({
            'x': x,
            'y': y,
            'r': data['count'],
            'title': tooltip_text
        })

    # 3. Tables
    top_critical_risks = sorted(
        [r for r in all_risks if r.criticality_level in ('Critical', 'High')],
        key=lambda x: x.residual_percent,
        reverse=True
    )[:5]

    accepted_risks = [r for r in all_risks if r.treatment_strategy == 'Accept']

    return render_template('risk/dashboard.html',
                           total_risks=total_risks,
                           critical_risks_count=critical_risks_count,
                           risk_exposure=risk_exposure,
                           avg_efficiency=avg_efficiency,
                           strategy_labels=strategy_labels,
                           strategy_data=strategy_data,
                           owner_labels=owner_labels,
                           owner_ids=owner_ids,  # <-- PASSING THIS NEW VARIABLE
                           owner_data=owner_data,
                           heatmap_data=heatmap_data,
                           top_critical_risks=top_critical_risks,
                           accepted_risks=accepted_risks)

@risk_bp.route('/dashboard/pdf', methods=['GET'])
@requires_permission(MODULE)
def dashboard_pdf():
    from weasyprint import HTML
    from flask import make_response
    
    # Re-fetch data for PDF (similar to dashboard but optimized for print)
    all_risks = Risk.query.all()
    total_risks = len(all_risks)
    
    # 1. KPIs
    critical_risks_count = sum(1 for r in all_risks if r.criticality_level == 'Critical')
    risk_exposure = sum(r.residual_score for r in all_risks)
    
    total_reduction = sum(r.risk_reduction_percentage for r in all_risks)
    avg_efficiency = round(total_reduction / total_risks, 1) if total_risks > 0 else 0.0

    # 2. Charts Data
    # Strategy Data for PDF (Dictionary for loop)
    strategies = {}
    for r in all_risks:
        s = r.treatment_strategy or 'Undefined'
        strategies[s] = strategies.get(s, 0) + 1

    # Heatmap Counts for Grid (x, y) -> count
    heatmap_counts = {}
    for r in all_risks:
        coord = (r.residual_likelihood, r.residual_impact)
        heatmap_counts[coord] = heatmap_counts.get(coord, 0) + 1

    # 3. Lists for Page 1
    # Top Critical Risks (Top 10 for PDF summary)
    top_critical_risks = sorted(
        [r for r in all_risks if r.criticality_level in ('Critical', 'High')],
        key=lambda x: x.residual_percent,
        reverse=True
    )[:10]

    accepted_risks = [r for r in all_risks if r.treatment_strategy == 'Accept']

    # 4. Detailed List for Page 2 (Full Register)
    # Sorted by where each risk sits on its own matrix, not by the raw product: a register
    # can hold risks assessed under different matrix sizes, and 12 out of 16 outranks
    # 15 out of 64.
    detailed_risks = sorted(
        all_risks,
        key=lambda x: x.residual_percent,
        reverse=True
    )

    # 5. Metadata
    user = db.session.get(User,session.get('user_id'))

    # Render HTML
    html_content = render_template(
        'risk/dashboard_pdf.html',
        total_risks=total_risks,
        critical_risks_count=critical_risks_count,
        risk_exposure=risk_exposure,
        avg_efficiency=avg_efficiency,
        strategies=strategies,
        heatmap_counts=heatmap_counts,
        top_critical_risks=top_critical_risks,
        accepted_risks=accepted_risks,
        detailed_risks=detailed_risks,
        generated_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        generated_by=user.name if user else 'System'
    )
    
    # Generate PDF
    pdf_file = HTML(string=html_content).write_pdf()
    
    response = make_response(pdf_file)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=risk_report.pdf'
    
    return response

@risk_bp.route('/<int:id>', methods=['GET'])
@requires_permission(MODULE)
def detail(id):
    risk = db.get_or_404(Risk, id)
    return render_template('risk/detail.html', risk=risk)

@risk_bp.route('/catalog', methods=['GET'])
@requires_permission(MODULE)
def catalog_list():
    catalogs = RiskCatalog.query.all()
    return render_template('risk/catalog_list.html', catalogs=catalogs)

@risk_bp.route('/catalog/<int:id>', methods=['GET'])
@requires_permission(MODULE)
def catalog_detail(id):
    catalog = db.get_or_404(RiskCatalog, id)
    return render_template('risk/catalog_detail.html', catalog=catalog)

from src.utils.timezone_helper import now


@risk_bp.route('/new', methods=['GET', 'POST'])
@requires_permission(MODULE)
def new_risk():
    if not has_write_permission(MODULE):
        if request.method == 'POST':
            flash('You do not have permission to log new risks.', 'danger')
            return redirect(url_for('risk.list_risks'))
    if request.method == 'POST':
        # Extract form data
        threat_type_id = request.form.get('threat_type_id')
        source_id = request.form.get('source_catalog_risk_id')
        
        risk = Risk(
            risk_description=request.form['risk_description'],
            extended_description=request.form.get('extended_description'),
            owner_id=request.form.get('owner_id'),
            status=request.form.get('status', 'Draft'),
            treatment_strategy=request.form.get('treatment_strategy'),
            threat_type_id=int(threat_type_id) if threat_type_id else None,
            
            inherent_impact=int(request.form.get('inherent_impact', 5)),
            inherent_likelihood=int(request.form.get('inherent_likelihood', 5)),
            
            # INTEGRITY RULE: Residual = Inherent on creation
            # Residual values can only be modified via Risk Assessments
            residual_impact=int(request.form.get('inherent_impact', 5)),
            residual_likelihood=int(request.form.get('inherent_likelihood', 5)),
            
            mitigation_plan=request.form.get('mitigation_plan'),
            link=request.form.get('link'),
            
            # Import tracking
            source_catalog_risk_id=int(source_id) if source_id else None
        )
        
        # Handle date
        review_date = request.form.get('next_review_date')
        if review_date:
            risk.next_review_date = datetime.strptime(review_date, '%Y-%m-%d').date()
            
        # Handle Assets
        asset_ids = request.form.getlist('asset_ids')
        if asset_ids:
            for asset_id in asset_ids:
                # Verify asset exists
                if db.session.get(Asset,asset_id):
                    item = RiskAffectedItem(linkable_type='Asset', linkable_id=asset_id)
                    risk.affected_items.append(item)
        
        # Handle Categories
        db.session.add(risk)
        db.session.flush()  # Get the risk.id
        category_names = request.form.getlist('category_ids')
        for cat_name in category_names:
            if cat_name in RISK_CATEGORIES:
                risk_cat = RiskCategory(risk_id=risk.id, category=cat_name)
                db.session.add(risk_cat)
        
        # Handle Mitigation Activities
        activity_ids = request.form.getlist('mitigation_activity_ids')
        for activity_id in activity_ids:
            activity = db.session.get(SecurityActivity,activity_id)
            if activity:
                risk.mitigation_activities.append(activity)

        db.session.commit()
        
        # Audit Log
        if source_id:
             log_audit(
                event_type='risk.imported',
                action='create',
                target_object=f"Risk:{risk.id}",
                details=f"Imported from CatalogRisk:{source_id}"
            )
        else:
             log_audit(
                event_type='risk.created',
                action='create',
                target_object=f"Risk:{risk.id}"
            )

        flash('Risk has been successfully logged.', 'success')
        return redirect(url_for('risk.list_risks'))

    users = User.query.filter_by(is_archived=False).all()
    activities = SecurityActivity.query.order_by(SecurityActivity.name).all()
    threat_types = ThreatType.query.order_by(ThreatType.category, ThreatType.name).all()
    
    # Handle Import Logic
    pre_filled_risk = None
    import_id = request.args.get('import_id')
    if import_id:
        catalog_risk = db.session.get(CatalogRisk,import_id)
        if catalog_risk:
            # Create transient object for pre-filling form
            pre_filled_risk = Risk(
                risk_description=catalog_risk.name,
                extended_description=catalog_risk.description,
                threat_type_id=catalog_risk.threat_type_id,
                inherent_impact=catalog_risk.suggested_impact,
                inherent_likelihood=catalog_risk.suggested_likelihood,
                # Use this attribute to pass it to the form (though not a DB column on Risk, we can use it on the object) 
                source_catalog_risk_id=catalog_risk.id 
            )
            # Add implicit category (if threat type has category, we might want to pre-select it? RiskCategory is separate)
            # Logic for categories is separate (m2m). We'll leave it empty for user to select.
            flash(f"Importing risk template: {catalog_risk.name}", 'info')

    return render_template('risk/form.html', users=users, activities=activities,
                           risk_categories=RISK_CATEGORIES, category_colors=RISK_CATEGORY_COLORS,
                           threat_types=threat_types, risk=pre_filled_risk)

@risk_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE)
def edit_risk(id):
    risk = db.get_or_404(Risk, id)
    if not has_write_permission(MODULE):
        if request.method == 'POST':
            flash('You do not have permission to edit risks.', 'danger')
            return redirect(url_for(DETAIL, id=id))
    if request.method == 'POST':
        # Capture old values for audit
        old_score = risk.residual_score
        
        risk.risk_description = request.form['risk_description']
        risk.extended_description = request.form.get('extended_description')
        risk.owner_id = request.form.get('owner_id')
        risk.status = request.form.get('status')
        risk.treatment_strategy = request.form.get('treatment_strategy')
        
        threat_type_id = request.form.get('threat_type_id')
        risk.threat_type_id = int(threat_type_id) if threat_type_id else None
        
        risk.inherent_impact = int(request.form.get('inherent_impact', 5))
        risk.inherent_likelihood = int(request.form.get('inherent_likelihood', 5))
        
        # INTEGRITY RULE: Residual risk cannot be edited manually.
        # It updates only via Assessments.
        # risk.residual_impact = int(request.form.get('residual_impact', 5))
        # risk.residual_likelihood = int(request.form.get('residual_likelihood', 5))
        
        risk.mitigation_plan = request.form.get('mitigation_plan')
        risk.link = request.form.get('link')
        
        # Handle date
        review_date = request.form.get('next_review_date')
        if review_date:
            risk.next_review_date = datetime.strptime(review_date, '%Y-%m-%d').date()
        else:
            risk.next_review_date = None

        # Handle Categories (Clear and Re-add)
        RiskCategory.query.filter_by(risk_id=risk.id).delete()
        category_names = request.form.getlist('category_ids')
        for cat_name in category_names:
            if cat_name in RISK_CATEGORIES:
                risk_cat = RiskCategory(risk_id=risk.id, category=cat_name)
                db.session.add(risk_cat)
        
        # Handle Mitigation Activities (Clear and Re-add)
        risk.mitigation_activities = []
        activity_ids = request.form.getlist('mitigation_activity_ids')
        for activity_id in activity_ids:
            activity = db.session.get(SecurityActivity,activity_id)
            if activity:
                risk.mitigation_activities.append(activity)

        db.session.commit()
        
        log_audit(
            event_type='risk.updated',
            action='update',
            target_object=f"Risk:{risk.id}",
            old_residual_score=old_score,
            new_residual_score=risk.residual_score
        )
        
        flash('Risk has been updated.', 'success')
        return redirect(url_for(DETAIL, id=risk.id))

    users = User.query.filter_by(is_archived=False).all()
    activities = SecurityActivity.query.order_by(SecurityActivity.name).all()
    threat_types = ThreatType.query.order_by(ThreatType.category, ThreatType.name).all()
    
    return render_template('risk/form.html', risk=risk, users=users, activities=activities,
                           risk_categories=RISK_CATEGORIES, category_colors=RISK_CATEGORY_COLORS,
                           threat_types=threat_types)

@risk_bp.route('/<int:id>/affected_items/add', methods=['POST'])
@requires_permission(MODULE)
def add_affected_item(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to modify risk items.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    risk = db.get_or_404(Risk, id)
    linkable_type = request.form.get('linkable_type')
    linkable_id = request.form.get('linkable_id')
    
    if not linkable_type or not linkable_id:
        flash('Invalid item selected.', 'danger')
        return redirect(url_for(DETAIL, id=id))

    # Check if already exists
    exists = RiskAffectedItem.query.filter_by(
        risk_id=risk.id,
        linkable_type=linkable_type,
        linkable_id=linkable_id
    ).first()
    
    if exists:
        flash('Item is already linked to this risk.', 'warning')
        return redirect(url_for(DETAIL, id=id))
        
    # Verify existence of the target object
    model_map = {
        'User': User,
        'Group': Group,
        'Asset': Asset,
        'Subscription': Subscription
    }
    
    model = model_map.get(linkable_type)
    if not model:
        flash(f'Unsupported item type: {linkable_type}', 'danger')
        return redirect(url_for(DETAIL, id=id))
        
    target = db.session.get(model,linkable_id)
    if not target:
        flash('Target item not found.', 'danger')
        return redirect(url_for(DETAIL, id=id))
        
    item = RiskAffectedItem(risk_id=risk.id, linkable_type=linkable_type, linkable_id=linkable_id)
    db.session.add(item)
    db.session.commit()
    
    flash('Affected item added successfully.', 'success')
    return redirect(url_for(DETAIL, id=id))

@risk_bp.route('/affected_items/<int:item_id>/delete', methods=['POST'])
@requires_permission(MODULE)
def remove_affected_item(item_id):
    if not has_write_permission(MODULE):
        item = db.get_or_404(RiskAffectedItem, item_id)
        flash('You do not have permission to modify risk items.', 'danger')
        return redirect(url_for(DETAIL, id=item.risk_id))
    item = db.get_or_404(RiskAffectedItem, item_id)
    risk_id = item.risk_id
    db.session.delete(item)
    db.session.commit()
    flash('Affected item removed.', 'success')
    return redirect(url_for(DETAIL, id=risk_id))

@risk_bp.route('/api/items/<item_type>', methods=['GET'])
@requires_permission_api(MODULE)
def api_get_items(item_type):
    """API endpoint to fetch items by type for dynamic selector."""
    model_map = {
        'User': User,
        'Group': Group,
        'Asset': Asset,
        'Subscription': Subscription
    }
    
    model = model_map.get(item_type)
    if not model:
        return jsonify([])
    
    items = []
    if item_type == 'User':
        records = model.query.filter_by(is_archived=False).order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': r.email} for r in records]
    elif item_type == 'Group':
        records = model.query.order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': f'{len(r.users)} members'} for r in records]
    elif item_type == 'Asset':
        records = model.query.filter_by(is_archived=False).order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': r.serial_number or r.status} for r in records]
    elif item_type == 'Subscription':
        records = model.query.filter_by(is_archived=False).order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': r.supplier.name if r.supplier else 'N/A'} for r in records]
    
    return jsonify(items)


@risk_bp.route('/api/references/<ref_type>', methods=['GET'])
@requires_permission_api(MODULE)
def api_get_references(ref_type):
    """API endpoint to fetch reference items by type for dynamic selector."""
    model_map = {
        'Policy': Policy,
        'Documentation': Documentation,
        'Link': Link
    }
    
    model = model_map.get(ref_type)
    if not model:
        return jsonify([])
    
    items = []
    if ref_type == 'Policy':
        records = model.query.order_by(model.title).all()
        items = [{'id': r.id, 'name': r.title, 'detail': r.category or 'General'} for r in records]
    elif ref_type == 'Documentation':
        records = model.query.order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': r.description[:50] + '...' if r.description and len(r.description) > 50 else (r.description or 'No description')} for r in records]
    elif ref_type == 'Link':
        records = model.query.order_by(model.name).all()
        items = [{'id': r.id, 'name': r.name, 'detail': r.url[:40] + '...' if len(r.url) > 40 else r.url} for r in records]
    
    return jsonify(items)


@risk_bp.route('/<int:id>/references/add', methods=['POST'])
@requires_permission(MODULE)
def add_reference(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to modify risk references.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """Add a reference (Policy, Documentation, Link) to a risk."""
    risk = db.get_or_404(Risk, id)
    linkable_type = request.form.get('linkable_type')
    linkable_id = request.form.get('linkable_id')
    
    if not linkable_type or not linkable_id:
        flash('Invalid reference selected.', 'danger')
        return redirect(url_for(DETAIL, id=id))

    # Check if already exists
    exists = RiskReference.query.filter_by(
        risk_id=risk.id,
        linkable_type=linkable_type,
        linkable_id=linkable_id
    ).first()
    
    if exists:
        flash('Reference is already linked to this risk.', 'warning')
        return redirect(url_for(DETAIL, id=id))
        
    # Verify existence of the target object
    model_map = {
        'Policy': Policy,
        'Documentation': Documentation,
        'Link': Link
    }
    
    model = model_map.get(linkable_type)
    if not model:
        flash(f'Unsupported reference type: {linkable_type}', 'danger')
        return redirect(url_for(DETAIL, id=id))
        
    target = db.session.get(model,linkable_id)
    if not target:
        flash('Target reference not found.', 'danger')
        return redirect(url_for(DETAIL, id=id))
        
    ref = RiskReference(risk_id=risk.id, linkable_type=linkable_type, linkable_id=linkable_id)
    db.session.add(ref)
    db.session.commit()
    
    flash('Reference added successfully.', 'success')
    return redirect(url_for(DETAIL, id=id))


@risk_bp.route('/references/<int:ref_id>/delete', methods=['POST'])
@requires_permission(MODULE)
def remove_reference(ref_id):
    if not has_write_permission(MODULE):
        ref = db.get_or_404(RiskReference, ref_id)
        flash('You do not have permission to modify risk references.', 'danger')
        return redirect(url_for(DETAIL, id=ref.risk_id))
    """Remove a reference from a risk."""
    ref = db.get_or_404(RiskReference, ref_id)
    risk_id = ref.risk_id
    db.session.delete(ref)
    db.session.commit()
    flash('Reference removed.', 'success')
    return redirect(url_for(DETAIL, id=risk_id))