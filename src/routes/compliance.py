import os
import uuid
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from datetime import datetime
from ..models import db, Supplier, SecurityAssessment, PolicyVersion, User, Audit, AuditEvent, Asset, BCDRPlan, BCDRTestLog, Subscription, SecurityIncident, PostIncidentReview, IncidentTimelineEvent, MaintenanceLog, Attachment, Framework, FrameworkControl, ComplianceLink
from .main import login_required
from .admin import admin_required

compliance_bp = Blueprint('compliance', __name__)

@compliance_bp.route('/vendors')
@login_required
def vendor_compliance():
    """Displays a list of all suppliers and their compliance status."""
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('compliance/vendor_list.html', suppliers=suppliers)

@compliance_bp.route('/<int:supplier_id>/new_assessment', methods=['GET', 'POST'])
@login_required
@admin_required
def new_assessment(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    if request.method == 'POST':
        assessment = SecurityAssessment(
            supplier_id=supplier_id,
            status=request.form['status'],
            assessment_date=datetime.strptime(request.form['assessment_date'], '%Y-%m-%d').date(),
            notes=request.form.get('notes')
        )
        db.session.add(assessment)
        db.session.commit()
        
        if 'report_file' in request.files:
            file = request.files['report_file']
            if file.filename != '':
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                
                # Save physical file
                upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(upload_path)

                # Create Attachment record manually
                new_attachment = Attachment(
                    filename=original_filename,
                    secure_filename=unique_filename,
                    linkable_type='SecurityAssessment', # Polymorphic link
                    linkable_id=assessment.id           # ID from committed object
                )
                db.session.add(new_attachment)
                db.session.commit()


        flash('New security assessment has been logged.', 'success')
        return redirect(url_for('suppliers.supplier_detail', id=supplier_id))

    return render_template('compliance/assessment_form.html', supplier=supplier, today_date=datetime.utcnow().strftime('%Y-%m-%d'))

@compliance_bp.route('/assessment/<int:id>')
@login_required
def assessment_detail(id):
    assessment = SecurityAssessment.query.get_or_404(id)
    return render_template('compliance/assessment_detail.html', assessment=assessment)

@compliance_bp.route('/assessment/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_assessment(id):
    assessment = SecurityAssessment.query.get_or_404(id)
    supplier = assessment.supplier

    if request.method == 'POST':
        assessment.status = request.form['status']
        assessment.assessment_date = datetime.strptime(request.form['assessment_date'], '%Y-%m-%d').date()
        assessment.notes = request.form.get('notes')
        
        db.session.commit()
        flash('Security assessment has been updated.', 'success')
        return redirect(url_for('suppliers.supplier_detail', id=supplier.id))

    return render_template('compliance/assessment_form.html', supplier=supplier, assessment=assessment)

@compliance_bp.route('/policy-report')
@login_required
def policy_report():
    """Shows which users have not acknowledged active policies."""
    active_versions = PolicyVersion.query.filter_by(status='Active').all()
    
    report_data = []
    for version in active_versions:
        # Get users who have already acknowledged the policy
        acknowledged_user_ids = {ack.user_id for ack in version.acknowledgements}
        
        # Get all users who SHOULD acknowledge the policy
        required_users = set()

        # Add users assigned directly
        for user in version.users_to_acknowledge:
            if not user.is_archived:
                required_users.add(user)
        
        # Add users from assigned groups
        for group in version.groups_to_acknowledge:
            for user in group.users:
                if not user.is_archived:
                    required_users.add(user)
        
        # If no users or groups are assigned, the policy applies to everyone
        if not version.users_to_acknowledge and not version.groups_to_acknowledge:
            all_active_users = User.query.filter_by(is_archived=False).all()
            required_users.update(all_active_users)

        # Determine which of the required users have not yet acknowledged
        unacknowledged_users = [
            user for user in required_users if user.id not in acknowledged_user_ids
        ]
        
        # Sort users by name for consistent display
        unacknowledged_users.sort(key=lambda u: u.name)
        
        if unacknowledged_users:
            report_data.append({
                'policy': version.policy,
                'version': version,
                'users': unacknowledged_users
            })
            
    return render_template('compliance/policy_report.html', report_data=report_data)

@compliance_bp.route('/audits')
@login_required
@admin_required
def list_audits():
    """Displays a list of all asset audits."""
    audits = Audit.query.order_by(Audit.created_at.desc()).all()
    return render_template('compliance/audit_list.html', audits=audits)

@compliance_bp.route('/audits/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_audit():
    """Creates a new audit."""
    if request.method == 'POST':
        user_id = session.get('user_id')
        audit = Audit(
            name=request.form['name'],
            description=request.form.get('description'),
            conducted_by_user_id=user_id
        )
        db.session.add(audit)
        db.session.commit()
        flash('New audit has been created successfully.', 'success')
        return redirect(url_for('compliance.audit_detail', id=audit.id))
    
    return render_template('compliance/audit_form.html')

@compliance_bp.route('/audits/<int:id>')
@login_required
@admin_required
def audit_detail(id):
    """Shows the details of an audit and allows for asset verification."""
    audit = Audit.query.get_or_404(id)
    
    # Get all active assets that haven't been audited yet in this session
    audited_asset_ids = [event.asset_id for event in audit.events]
    assets_to_audit = Asset.query.filter(
        Asset.is_archived == False,
        Asset.id.notin_(audited_asset_ids)
    ).order_by(Asset.name).all()

    # Query and sort the audit events here
    audit_events = audit.events.order_by(AuditEvent.event_time.desc()).all()

    return render_template(
        'compliance/audit_detail.html', 
        audit=audit, 
        assets_to_audit=assets_to_audit,
        audit_events=audit_events
    )

@compliance_bp.route('/audits/<int:id>/record_event', methods=['POST'])
@login_required
@admin_required
def record_audit_event(id):
    """Records a verification or flagged issue for an asset in an audit."""
    audit = Audit.query.get_or_404(id)
    asset_id = request.form.get('asset_id')
    status = request.form.get('status')
    notes = request.form.get('notes')
    
    asset = Asset.query.get_or_404(asset_id)
    
    event = AuditEvent(
        audit_id=audit.id,
        asset_id=asset.id,
        user_id=asset.user_id, # Record who the asset is currently assigned to
        status=status,
        notes=notes
    )
    
    db.session.add(event)
    db.session.commit()

    if status == 'Verified':
        flash(f'Asset "{asset.name}" has been verified.', 'success')
    else:
        flash(f'Asset "{asset.name}" has been flagged with an issue.', 'warning')
        
    return redirect(url_for('compliance.audit_detail', id=id))

@compliance_bp.route('/audits/<int:id>/complete', methods=['POST'])
@login_required
@admin_required
def complete_audit(id):
    audit = Audit.query.get_or_404(id)
    audit.is_completed = True
    db.session.commit()
    flash(f'Audit "{audit.name}" has been marked as complete.', 'success')
    return redirect(url_for('compliance.list_audits'))

@compliance_bp.route('/bcdr')
@login_required
@admin_required
def list_bcdr_plans():
    """Displays a list of all BCDR plans."""
    plans = BCDRPlan.query.order_by(BCDRPlan.name).all()
    return render_template('compliance/bcdr_list.html', plans=plans)

@compliance_bp.route('/bcdr/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_bcdr_plan():
    if request.method == 'POST':
        plan = BCDRPlan(
            name=request.form['name'],
            description=request.form.get('description')
        )
        # Handle subscription and asset associations
        subscription_ids = request.form.getlist('subscription_ids')
        asset_ids = request.form.getlist('asset_ids')
        plan.subscriptions = Subscription.query.filter(Subscription.id.in_(subscription_ids)).all()
        plan.assets = Asset.query.filter(Asset.id.in_(asset_ids)).all()
        
        db.session.add(plan)
        db.session.commit()
        flash('BCDR Plan created successfully.', 'success')
        return redirect(url_for('compliance.list_bcdr_plans'))

    subscriptions = Subscription.query.order_by(Subscription.name).all()
    assets = Asset.query.order_by(Asset.name).all()
    return render_template('compliance/bcdr_form.html', subscriptions=subscriptions, assets=assets)

@compliance_bp.route('/bcdr/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_bcdr_plan(id):
    plan = BCDRPlan.query.get_or_404(id)
    if request.method == 'POST':
        plan.name = request.form['name']
        plan.description = request.form.get('description')
        
        # Handle subscription and asset associations
        subscription_ids = request.form.getlist('subscription_ids')
        asset_ids = request.form.getlist('asset_ids')
        plan.subscriptions = Subscription.query.filter(Subscription.id.in_(subscription_ids)).all()
        plan.assets = Asset.query.filter(Asset.id.in_(asset_ids)).all()
        
        db.session.commit()
        flash('BCDR Plan updated successfully.', 'success')
        return redirect(url_for('compliance.bcdr_detail', id=plan.id))

    subscriptions = Subscription.query.order_by(Subscription.name).all()
    assets = Asset.query.order_by(Asset.name).all()
    return render_template('compliance/bcdr_form.html', plan=plan, subscriptions=subscriptions, assets=assets)

@compliance_bp.route('/bcdr/<int:id>')
@login_required
@admin_required
def bcdr_detail(id):
    plan = BCDRPlan.query.get_or_404(id)
    return render_template('compliance/bcdr_detail.html', plan=plan)

@compliance_bp.route('/bcdr/test/<int:test_id>')
@login_required
@admin_required
def bcdr_test_log_detail(test_id):
    """Muestra los detalles de un único BCDR test log."""
    test_log = BCDRTestLog.query.get_or_404(test_id)
    return render_template('compliance/bcdr_test_log_detail.html', test_log=test_log)

@compliance_bp.route('/bcdr/<int:plan_id>/log_test', methods=['GET', 'POST'])
@login_required
@admin_required
def log_bcdr_test(plan_id):
    plan = BCDRPlan.query.get_or_404(plan_id)
    if request.method == 'POST':
        test_log = BCDRTestLog(
            plan_id=plan.id,
            test_date=datetime.strptime(request.form['test_date'], '%Y-%m-%d').date(),
            status=request.form['status'],
            notes=request.form.get('notes')
        )
        db.session.add(test_log)
        db.session.commit() # Hacemos commit para obtener el test_log.id
        
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
                    linkable_type='BCDRTestLog',
                    linkable_id=test_log.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash('BCDR test log has been recorded.', 'success')
        # Redirigimos a la nueva vista de detalles del log
        return redirect(url_for('compliance.bcdr_test_log_detail', test_id=test_log.id))

    return render_template('compliance/bcdr_test_log_form.html', plan=plan, today_date=datetime.utcnow().strftime('%Y-%m-%d'))

@compliance_bp.route('/bcdr/test/<int:test_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_bcdr_test(test_id):
    test_log = BCDRTestLog.query.get_or_404(test_id)
    plan = test_log.plan
    if request.method == 'POST':
        test_log.test_date = datetime.strptime(request.form['test_date'], '%Y-%m-%d').date()
        test_log.status = request.form['status']
        test_log.notes = request.form.get('notes')
        
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                # Borramos el adjunto anterior si existe (opcional, pero recomendado)
                existing_attachment = Attachment.query.filter_by(linkable_type='BCDRTestLog', linkable_id=test_log.id).first()
                if existing_attachment:
                    try:
                        os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], existing_attachment.secure_filename))
                    except OSError:
                        pass # Ignorar si el archivo no existe
                    db.session.delete(existing_attachment)
                
                # Subir el nuevo
                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                
                attachment = Attachment(
                    filename=original_filename,
                    secure_filename=unique_filename,
                    linkable_type='BCDRTestLog',
                    linkable_id=test_log.id
                )
                db.session.add(attachment)
        
        db.session.commit()

        flash('BCDR test log has been updated.', 'success')
        # Redirigimos a la nueva vista de detalles del log
        return redirect(url_for('compliance.bcdr_test_log_detail', test_id=test_log.id))

    return render_template('compliance/bcdr_test_log_form.html', plan=plan, test_log=test_log, today_date=test_log.test_date.strftime('%Y-%m-%d'))

@compliance_bp.route('/incidents')
@login_required
@admin_required
def list_incidents():
    incidents = SecurityIncident.query.order_by(SecurityIncident.incident_date.desc()).all()
    return render_template('compliance/incident_list.html', incidents=incidents)

@compliance_bp.route('/incidents/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_incident():
    if request.method == 'POST':
        incident = SecurityIncident(
            title=request.form['title'],
            description=request.form['description'],
            incident_date=datetime.strptime(request.form['incident_date'], '%Y-%m-%dT%H:%M'),
            status=request.form['status'],
            severity=request.form['severity'],
            impact=request.form['impact'],
            data_breach='data_breach' in request.form,
            third_party_impacted='third_party_impacted' in request.form,
            reported_by_id=session.get('user_id'),
            owner_id=request.form.get('owner_id') or None
        )
        incident.affected_assets = Asset.query.filter(Asset.id.in_(request.form.getlist('asset_ids'))).all()
        incident.affected_users = User.query.filter(User.id.in_(request.form.getlist('user_ids'))).all()
        incident.affected_subscriptions = Subscription.query.filter(Subscription.id.in_(request.form.getlist('subscription_ids'))).all()
        incident.affected_suppliers = Supplier.query.filter(Supplier.id.in_(request.form.getlist('supplier_ids'))).all()
        db.session.add(incident)
        db.session.commit()
        flash('Security incident logged successfully.', 'success')
        return redirect(url_for('compliance.incident_detail', id=incident.id))
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    return render_template('compliance/incident_form.html', users=users, assets=assets, subscriptions=subscriptions, suppliers=suppliers)

@compliance_bp.route('/incidents/<int:id>')
@login_required
@admin_required
def incident_detail(id):
    incident = SecurityIncident.query.get_or_404(id)
    return render_template('compliance/incident_detail.html', incident=incident)

@compliance_bp.route('/incidents/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_incident(id):
    incident = SecurityIncident.query.get_or_404(id)
    if request.method == 'POST':
        incident.title = request.form['title']
        incident.description = request.form['description']
        incident.incident_date = datetime.strptime(request.form['incident_date'], '%Y-%m-%dT%H:%M')
        incident.status = request.form['status']
        incident.severity = request.form['severity']
        incident.impact = request.form['impact']
        incident.data_breach = 'data_breach' in request.form
        incident.third_party_impacted = 'third_party_impacted' in request.form
        incident.owner_id = request.form.get('owner_id') or None
        if incident.status == 'Closed' and not incident.resolved_at:
            incident.resolved_at = datetime.utcnow()
        elif incident.status != 'Closed':
            incident.resolved_at = None
        incident.affected_assets = Asset.query.filter(Asset.id.in_(request.form.getlist('asset_ids'))).all()
        incident.affected_users = User.query.filter(User.id.in_(request.form.getlist('user_ids'))).all()
        incident.affected_subscriptions = Subscription.query.filter(Subscription.id.in_(request.form.getlist('subscription_ids'))).all()
        incident.affected_suppliers = Supplier.query.filter(Supplier.id.in_(request.form.getlist('supplier_ids'))).all()
        db.session.commit()
        flash('Incident details updated.', 'success')
        return redirect(url_for('compliance.incident_detail', id=id))
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    return render_template('compliance/incident_form.html', incident=incident, users=users, assets=assets, subscriptions=subscriptions, suppliers=suppliers)

@compliance_bp.route('/incidents/<int:id>/review', methods=['GET', 'POST'])
@login_required
@admin_required
def incident_review(id):
    incident = SecurityIncident.query.get_or_404(id)
    review = incident.review

    if not review:
        # If no review exists, create one to start with
        review = PostIncidentReview(incident_id=id)
        db.session.add(review)
        db.session.commit()

    if request.method == 'POST':
        # Update the text fields
        review.summary = request.form.get('summary')
        review.lead_up = request.form.get('lead_up')
        review.fault = request.form.get('fault')
        review.impact_analysis = request.form.get('impact_analysis')
        review.detection = request.form.get('detection')
        review.response = request.form.get('response')
        review.recovery = request.form.get('recovery')
        review.lessons_learned = request.form.get('lessons_learned')
        db.session.commit()
        flash('Post-Incident Review saved successfully.', 'success')
        return redirect(url_for('compliance.incident_review', id=id))

    return render_template('compliance/pir_form.html', incident=incident, review=review)

@compliance_bp.route('/incidents/review/<int:review_id>/timeline', methods=['POST'])
@login_required
@admin_required
def add_timeline_event(review_id):
    review = PostIncidentReview.query.get_or_404(review_id)
    data = request.json
    max_order = db.session.query(db.func.max(IncidentTimelineEvent.order)).filter_by(review_id=review.id).scalar() or -1
    
    event = IncidentTimelineEvent(
        review_id=review.id,
        event_time=datetime.fromisoformat(data['time']),
        description=data['description'],
        order=max_order + 1
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({'id': event.id, 'time': event.event_time.strftime('%Y-%m-%dT%H:%M'), 'description': event.description}), 201

@compliance_bp.route('/incidents/review/timeline/<int:event_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_timeline_event(event_id):
    event = IncidentTimelineEvent.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})

@compliance_bp.route('/incidents/review/<int:review_id>/timeline/reorder', methods=['POST'])
@login_required
@admin_required
def reorder_timeline_events(review_id):
    ordered_ids = request.json.get('ordered_ids', [])
    for index, event_id in enumerate(ordered_ids):
        event = IncidentTimelineEvent.query.filter_by(id=event_id, review_id=review_id).first()
        if event:
            event.order = index
    db.session.commit()
    return jsonify({'success': True})

@compliance_bp.route('/data-erasures')
@login_required
@admin_required
def list_erasures():
    """Displays a filtered list of all data erasure maintenance events for audit purposes."""
    erasure_logs = MaintenanceLog.query.filter_by(event_type='Data Erasure').order_by(MaintenanceLog.event_date.desc()).all()
    return render_template('compliance/erasure_list.html', logs=erasure_logs)

# --- API Routes for Compliance Linking ---

@compliance_bp.route('/frameworks', methods=['GET'])
@login_required
def get_frameworks():
    """Returns a JSON list of active frameworks."""
    frameworks = Framework.query.filter_by(is_active=True).order_by(Framework.name).all()
    return jsonify([{
        'id': f.id,
        'name': f.name,
        'description': f.description
    } for f in frameworks])

@compliance_bp.route('/frameworks/<int:framework_id>/controls', methods=['GET'])
@login_required
def get_framework_controls(framework_id):
    """Returns a JSON list of controls for a specific framework."""
    framework = Framework.query.get_or_404(framework_id)
    if not framework.is_active:
        return jsonify({'error': 'Framework is disabled'}), 400
        
    controls = framework.framework_controls.order_by(FrameworkControl.control_id).all()
    return jsonify([{
        'id': c.id,
        'control_id': c.control_id,
        'name': c.name,
        'description': c.description
    } for c in controls])

@compliance_bp.route('/link', methods=['POST'])
@login_required
def create_compliance_link():
    """Creates a new compliance link."""
    data = request.json
    framework_control_id = data.get('framework_control_id')
    linkable_id = data.get('linkable_id')
    linkable_type = data.get('linkable_type')
    description = data.get('description')

    if not all([framework_control_id, linkable_id, linkable_type, description]):
        return jsonify({'error': 'Missing required fields'}), 400

    # Validate control exists
    control = FrameworkControl.query.get(framework_control_id)
    if not control:
        return jsonify({'error': 'Control not found'}), 404
        
    # Validate framework is active
    if not control.framework.is_active:
        return jsonify({'error': 'Framework is disabled'}), 400

    # Check for existing link to avoid duplicates
    existing_link = ComplianceLink.query.filter_by(
        framework_control_id=framework_control_id,
        linkable_id=linkable_id,
        linkable_type=linkable_type
    ).first()

    if existing_link:
        return jsonify({'error': 'Link already exists'}), 409

    link = ComplianceLink(
        framework_control_id=framework_control_id,
        linkable_id=linkable_id,
        linkable_type=linkable_type,
        description=description
    )
    db.session.add(link)
    db.session.commit()

    return jsonify({
        'id': link.id,
        'status': 'success',
        'message': 'Link created successfully'
    }), 201

@compliance_bp.route('/link/<int:link_id>', methods=['DELETE'])
@login_required
def delete_compliance_link(link_id):
    """Deletes a compliance link."""
    link = ComplianceLink.query.get_or_404(link_id)
    db.session.delete(link)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Link deleted successfully'})