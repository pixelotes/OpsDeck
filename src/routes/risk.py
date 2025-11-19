from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Risk, User, Asset
from .main import login_required
from .admin import admin_required
from datetime import datetime

risk_bp = Blueprint('risk', __name__)

@risk_bp.route('/')
@login_required
def list_risks():
    risks = Risk.query.order_by(Risk.created_at.desc()).all()
    return render_template('risk/list.html', risks=risks)

@risk_bp.route('/dashboard')
@login_required
def dashboard():
    # 1. KPIs
    all_risks = Risk.query.all()
    total_risks = len(all_risks)
    
    critical_risks_count = sum(1 for r in all_risks if r.residual_score >= 20)
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

    # Top Owners
    owners = {}
    for r in all_risks:
        name = r.owner.name if r.owner else 'Unassigned'
        owners[name] = owners.get(name, 0) + 1
    
    # Sort by count desc and take top 5
    sorted_owners = sorted(owners.items(), key=lambda item: item[1], reverse=True)[:5]
    owner_labels = [item[0] for item in sorted_owners]
    owner_data = [item[1] for item in sorted_owners]

    # Heatmap Data (Scatter Plot format: x=Likelihood, y=Impact)
    # We need to group risks by coordinate to show "bubble size" or just list them
    heatmap_data = []
    for r in all_risks:
        heatmap_data.append({
            'x': r.residual_likelihood,
            'y': r.residual_impact,
            'r': 5, # Radius (could be dynamic based on count at this spot)
            'title': r.risk_description # For tooltip
        })

    # 3. Tables
    # Top Critical Risks (Residual Score >= 15 for the list, ordered desc)
    top_critical_risks = sorted(
        [r for r in all_risks if r.residual_score >= 15],
        key=lambda x: x.residual_score,
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
                           owner_data=owner_data,
                           heatmap_data=heatmap_data,
                           top_critical_risks=top_critical_risks,
                           accepted_risks=accepted_risks)

@risk_bp.route('/<int:id>')
@login_required
def detail(id):
    risk = Risk.query.get_or_404(id)
    return render_template('risk/detail.html', risk=risk)

@risk_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_risk():
    if request.method == 'POST':
        # Extract form data
        risk = Risk(
            risk_description=request.form['risk_description'],
            owner_id=request.form.get('owner_id'),
            status=request.form.get('status'),
            treatment_strategy=request.form.get('treatment_strategy'),
            
            inherent_impact=int(request.form.get('inherent_impact', 5)),
            inherent_likelihood=int(request.form.get('inherent_likelihood', 5)),
            
            residual_impact=int(request.form.get('residual_impact', 5)),
            residual_likelihood=int(request.form.get('residual_likelihood', 5)),
            
            mitigation_plan=request.form.get('mitigation_plan'),
            link=request.form.get('link')
        )
        
        # Handle date
        review_date = request.form.get('next_review_date')
        if review_date:
            risk.next_review_date = datetime.strptime(review_date, '%Y-%m-%d').date()
            
        # Handle Assets
        asset_ids = request.form.getlist('asset_ids')
        if asset_ids:
            for asset_id in asset_ids:
                asset = Asset.query.get(asset_id)
                if asset:
                    risk.assets.append(asset)

        db.session.add(risk)
        db.session.commit()
        flash('Risk has been successfully logged.', 'success')
        return redirect(url_for('risk.list_risks'))

    users = User.query.filter_by(is_archived=False).all()
    assets = Asset.query.filter_by(is_archived=False).all()
    return render_template('risk/form.html', users=users, assets=assets)

@risk_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_risk(id):
    risk = Risk.query.get_or_404(id)
    if request.method == 'POST':
        risk.risk_description = request.form['risk_description']
        risk.owner_id = request.form.get('owner_id')
        risk.status = request.form.get('status')
        risk.treatment_strategy = request.form.get('treatment_strategy')
        
        risk.inherent_impact = int(request.form.get('inherent_impact', 5))
        risk.inherent_likelihood = int(request.form.get('inherent_likelihood', 5))
        
        risk.residual_impact = int(request.form.get('residual_impact', 5))
        risk.residual_likelihood = int(request.form.get('residual_likelihood', 5))
        
        risk.mitigation_plan = request.form.get('mitigation_plan')
        risk.link = request.form.get('link')
        
        # Handle date
        review_date = request.form.get('next_review_date')
        if review_date:
            risk.next_review_date = datetime.strptime(review_date, '%Y-%m-%d').date()
        else:
            risk.next_review_date = None

        # Handle Assets (Clear and Re-add)
        risk.assets = [] # Clear existing
        asset_ids = request.form.getlist('asset_ids')
        if asset_ids:
            for asset_id in asset_ids:
                asset = Asset.query.get(asset_id)
                if asset:
                    risk.assets.append(asset)

        db.session.commit()
        flash('Risk has been updated.', 'success')
        return redirect(url_for('risk.list_risks'))

    users = User.query.filter_by(is_archived=False).all()
    assets = Asset.query.filter_by(is_archived=False).all()
    return render_template('risk/form.html', risk=risk, users=users, assets=assets)