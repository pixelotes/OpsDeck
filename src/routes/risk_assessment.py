from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file
from ..models import db, RiskAssessment, RiskAssessmentItem, Risk
from ..services.permissions_service import (requires_permission, has_write_permission,
                                           requires_permission_api)
import io
from src.utils.timezone_helper import now


risk_assessment_bp = Blueprint('risk_assessment', __name__, url_prefix='/risk-assessments')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'risk_governance'
VIEW_ASSESSMENT = 'risk_assessment.view_assessment'

@risk_assessment_bp.route('/', methods=['GET'])
@requires_permission(MODULE)
def list_assessments():
    assessments = RiskAssessment.query.order_by(RiskAssessment.created_at.desc()).all()
    return render_template('risk_assessment/list.html', assessments=assessments)

@risk_assessment_bp.route('/new', methods=['GET', 'POST'])
@requires_permission(MODULE)
def new_assessment():
    if not has_write_permission(MODULE):
        if request.method == 'POST':
            flash('You do not have permission to create assessments.', 'danger')
            return redirect(url_for('risk_assessment.list_assessments'))
    if request.method == 'POST':
        name = request.form.get('name')
        include_risks = request.form.get('include_risks') == 'yes'
        
        assessment = RiskAssessment(name=name, status='Draft')
        db.session.add(assessment)
        db.session.commit() # Commit to get ID
        
        if include_risks:
            # Snapshot Logic
            open_risks = Risk.query.filter(Risk.status != 'Closed').all()
            for risk in open_risks:
                item = RiskAssessmentItem(
                    assessment_id=assessment.id,
                    original_risk_id=risk.id,
                    risk_description=risk.risk_description,
                    threat_type_name=risk.threat_type.name if risk.threat_type else None,
                    category_list=",".join([c.category for c in risk.categories]),
                    inherent_impact=risk.inherent_impact,
                    inherent_likelihood=risk.inherent_likelihood,
                    residual_impact=risk.residual_impact,
                    residual_likelihood=risk.residual_likelihood,
                    # The matrix travels with the numbers. Without it the item would take
                    # the organisation's current matrix from its column default, so a risk
                    # scored 4 out of 5 would be frozen as 4 out of 8 the moment somebody
                    # widened the matrix — a snapshot that misreports the very risk it is
                    # a snapshot of.
                    impact_levels=risk.impact_levels,
                    likelihood_levels=risk.likelihood_levels,
                    treatment_strategy=risk.treatment_strategy
                )
                db.session.add(item)
            
            assessment.calculate_total_risk()
            db.session.commit()
            flash(f'Assessment created with {len(open_risks)} snapshot items.', 'success')
        else:
            flash('Empty assessment created.', 'success')
            
        return redirect(url_for(VIEW_ASSESSMENT, id=assessment.id))
        
    return render_template('risk_assessment/new.html')

@risk_assessment_bp.route('/<int:id>', methods=['GET'])
@requires_permission(MODULE)
def view_assessment(id):
    assessment = db.get_or_404(RiskAssessment, id)
    return render_template('risk_assessment/detail.html', assessment=assessment)

@risk_assessment_bp.route('/item/<int:id>/edit', methods=['POST'])
@requires_permission(MODULE)
def edit_assessment_item(id):
    if not has_write_permission(MODULE):
        item = db.get_or_404(RiskAssessmentItem, id)
        flash('You do not have permission to edit assessment items.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=item.assessment_id))
    item = db.get_or_404(RiskAssessmentItem, id)
    if item.assessment.status == 'Locked':
        flash('Cannot edit items in a locked assessment.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=item.assessment_id))
        
    item.risk_description = request.form.get('risk_description')
    item.residual_impact = int(request.form.get('residual_impact'))
    item.residual_likelihood = int(request.form.get('residual_likelihood'))
    item.mitigation_notes = request.form.get('mitigation_notes')
    
    # Recalculate total risk for the assessment
    item.assessment.calculate_total_risk()
    
    db.session.commit()
    flash('Assessment item updated.', 'success')
    return redirect(url_for(VIEW_ASSESSMENT, id=item.assessment_id))

@risk_assessment_bp.route('/<int:id>/lock', methods=['POST'])
@requires_permission(MODULE)
def lock_assessment(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to lock assessments.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    assessment = db.get_or_404(RiskAssessment, id)
    
    # Checkbox from the sync modal
    sync_to_live = request.form.get('sync_to_live') == 'on'
    
    # 1. Lock the assessment
    assessment.status = 'Locked'
    assessment.locked_at = now()
    assessment.calculate_total_risk()
    
    # 2. Write-back: Update live risks (Optional Sync)
    updated_count = 0
    if sync_to_live:
        for item in assessment.items:
            # Only update if there's a linked original risk
            if item.original_risk_id:
                live_risk = db.session.get(Risk,item.original_risk_id)
                if live_risk:
                    # Update residual scores from assessment, matrix included: the numbers
                    # only mean anything alongside the scale they were chosen from, and
                    # writing them onto a risk still holding a different one would
                    # misread them.
                    live_risk.residual_impact = item.residual_impact
                    live_risk.residual_likelihood = item.residual_likelihood
                    live_risk.impact_levels = item.impact_levels
                    live_risk.likelihood_levels = item.likelihood_levels
                    
                    # Conditional status update/suggestion
                    # If risk was 'Draft' or 'Identified', move it along.
                    # If it was 'Accepted', we might not want to auto-change it, but score MUST update.
                    
                    # Logic: If status is NOT closed, update status based on severity.
                    # Named bands rather than raw scores, which only lined up with the
                    # intent while every matrix was 5x5: `< 5` meant "Low" and `>= 15`
                    # meant "High or worse".
                    if live_risk.status not in ['Closed', 'Accepted']:
                        severity = item.criticality_level
                        if severity == 'Low':
                            live_risk.status = 'Mitigated'
                        elif severity in ('Critical', 'High'):
                            live_risk.status = 'In Treatment'
                        else:
                            live_risk.status = 'Assessed'
                    
                    updated_count += 1
    
    db.session.commit()
    
    msg = 'Assessment locked successfully.'
    if sync_to_live and updated_count > 0:
        msg += f' {updated_count} live risk(s) updated with new scores.'
    flash(msg, 'success')
    return redirect(url_for(VIEW_ASSESSMENT, id=assessment.id))

@risk_assessment_bp.route('/<int:id>/pdf', methods=['GET'])
@requires_permission(MODULE)
def export_pdf(id):
    assessment = db.get_or_404(RiskAssessment, id)
    from weasyprint import HTML
    
    html = render_template('risk_assessment/pdf_report.html', assessment=assessment, now=now())
    pdf = HTML(string=html).write_pdf()
    
    return send_file(
        io.BytesIO(pdf),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Assessment_{assessment.name.replace(" ", "_")}.pdf'
    )


# --- Evidence Management Routes ---

@risk_assessment_bp.route('/<int:id>/item/<int:item_id>/upload', methods=['POST'])
@requires_permission(MODULE)
def upload_evidence(id, item_id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to upload evidence.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    """Upload a file as evidence for an assessment item."""
    from ..models import Attachment, RiskAssessmentEvidence
    from werkzeug.utils import secure_filename
    from flask import current_app
    import uuid
    import os
    
    assessment = db.get_or_404(RiskAssessment, id)
    item = db.get_or_404(RiskAssessmentItem, item_id)
    
    if item.assessment_id != assessment.id:
        flash('Invalid item for this assessment.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    if assessment.status == 'Locked':
        flash('Cannot add evidence to a locked assessment.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    # Save file
    original_filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(save_path)
    
    # Create Attachment record
    attachment = Attachment(
        filename=original_filename,
        secure_filename=unique_filename,
        linkable_type='RiskAssessmentItem',
        linkable_id=item_id
    )
    db.session.add(attachment)
    db.session.flush()
    
    # Create Evidence record
    notes = request.form.get('notes', '')
    evidence = RiskAssessmentEvidence(
        item_id=item_id,
        attachment_id=attachment.id,
        notes=notes
    )
    db.session.add(evidence)
    db.session.commit()
    
    flash(f'Evidence file "{original_filename}" uploaded successfully.', 'success')
    return redirect(url_for(VIEW_ASSESSMENT, id=id))


@risk_assessment_bp.route('/<int:id>/item/<int:item_id>/link', methods=['POST'])
@requires_permission(MODULE)
def link_evidence(id, item_id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to link evidence.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    """Link an existing OpsDeck object as evidence for an assessment item."""
    from ..models import RiskAssessmentEvidence
    
    assessment = db.get_or_404(RiskAssessment, id)
    item = db.get_or_404(RiskAssessmentItem, item_id)
    
    if item.assessment_id != assessment.id:
        flash('Invalid item for this assessment.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    if assessment.status == 'Locked':
        flash('Cannot add evidence to a locked assessment.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    linkable_type = request.form.get('linkable_type')
    linkable_id = request.form.get('linkable_id')
    notes = request.form.get('notes', '')
    
    if not linkable_type or not linkable_id:
        flash('Please select an object to link.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    evidence = RiskAssessmentEvidence(
        item_id=item_id,
        linkable_type=linkable_type,
        linkable_id=int(linkable_id),
        notes=notes
    )
    db.session.add(evidence)
    db.session.commit()
    
    flash(f'{linkable_type} linked as evidence successfully.', 'success')
    return redirect(url_for(VIEW_ASSESSMENT, id=id))


@risk_assessment_bp.route('/<int:id>/evidence/<int:evidence_id>/delete', methods=['POST'])
@requires_permission(MODULE)
def delete_evidence(id, evidence_id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to remove evidence.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    """Remove an evidence item from an assessment."""
    from ..models import RiskAssessmentEvidence
    
    assessment = db.get_or_404(RiskAssessment, id)
    evidence = db.get_or_404(RiskAssessmentEvidence, evidence_id)
    
    if evidence.item.assessment_id != assessment.id:
        flash('Invalid evidence for this assessment.', 'danger')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    if assessment.status == 'Locked':
        flash('Cannot remove evidence from a locked assessment.', 'warning')
        return redirect(url_for(VIEW_ASSESSMENT, id=id))
    
    db.session.delete(evidence)
    db.session.commit()
    
    flash('Evidence removed successfully.', 'success')
    return redirect(url_for(VIEW_ASSESSMENT, id=id))


@risk_assessment_bp.route('/api/linkable-objects/<linkable_type>', methods=['GET'])
@requires_permission_api(MODULE)
def get_linkable_objects(linkable_type):
    """API endpoint to get objects of a specific type for linking as evidence."""
    from flask import jsonify
    from ..models import Policy, Asset, Documentation, Software, Supplier, Course, BCDRPlan
    
    model_map = {
        'Policy': (Policy, 'title'),
        'Asset': (Asset, 'name'),
        'Documentation': (Documentation, 'name'),
        'Software': (Software, 'name'),
        'Supplier': (Supplier, 'name'),
        'Course': (Course, 'title'),
        'BCDRPlan': (BCDRPlan, 'name'),
    }
    
    if linkable_type not in model_map:
        return jsonify([])
    
    model, name_field = model_map[linkable_type]
    
    # Filter out archived items if the model has is_archived
    if hasattr(model, 'is_archived'):
        objects = model.query.filter_by(is_archived=False).all()
    elif hasattr(model, 'status'):
        objects = model.query.filter(model.status != 'Archived').all()
    else:
        objects = model.query.all()
    
    result = [{'id': obj.id, 'name': getattr(obj, name_field, f'#{obj.id}')} for obj in objects]
    return jsonify(result)
