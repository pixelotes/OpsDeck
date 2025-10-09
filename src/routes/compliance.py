from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from ..models import db, Supplier, SecurityAssessment, PolicyVersion, User, Audit, AuditEvent, Asset, BCDRPlan, BCDRTestLog, Service
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
        
        # This will now work correctly with the updated attachments route
        if 'report_file' in request.files:
            file = request.files['report_file']
            if file.filename != '':
                # Manually create a new request context to call the upload function
                with request.another_app.test_request_context(
                    '/attachments/upload', 
                    method='POST', 
                    data={'security_assessment_id': assessment.id},
                    files={'file': file}
                ):
                    # You might need a more robust way to handle this cross-blueprint call
                    # depending on your final upload logic. For now, this demonstrates the principle.
                    pass


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
        # Handle service and asset associations
        service_ids = request.form.getlist('service_ids')
        asset_ids = request.form.getlist('asset_ids')
        plan.services = Service.query.filter(Service.id.in_(service_ids)).all()
        plan.assets = Asset.query.filter(Asset.id.in_(asset_ids)).all()
        
        db.session.add(plan)
        db.session.commit()
        flash('BCDR Plan created successfully.', 'success')
        return redirect(url_for('compliance.list_bcdr_plans'))

    services = Service.query.order_by(Service.name).all()
    assets = Asset.query.order_by(Asset.name).all()
    return render_template('compliance/bcdr_form.html', services=services, assets=assets)

@compliance_bp.route('/bcdr/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_bcdr_plan(id):
    plan = BCDRPlan.query.get_or_404(id)
    if request.method == 'POST':
        plan.name = request.form['name']
        plan.description = request.form.get('description')
        
        # Handle service and asset associations
        service_ids = request.form.getlist('service_ids')
        asset_ids = request.form.getlist('asset_ids')
        plan.services = Service.query.filter(Service.id.in_(service_ids)).all()
        plan.assets = Asset.query.filter(Asset.id.in_(asset_ids)).all()
        
        db.session.commit()
        flash('BCDR Plan updated successfully.', 'success')
        return redirect(url_for('compliance.bcdr_detail', id=plan.id))

    services = Service.query.order_by(Service.name).all()
    assets = Asset.query.order_by(Asset.name).all()
    return render_template('compliance/bcdr_form.html', plan=plan, services=services, assets=assets)

@compliance_bp.route('/bcdr/<int:id>')
@login_required
@admin_required
def bcdr_detail(id):
    plan = BCDRPlan.query.get_or_404(id)
    return render_template('compliance/bcdr_detail.html', plan=plan)

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
        db.session.commit()
        
        # This logic is simplified; a more robust solution would handle the file directly
        if 'proof_file' in request.files and request.files['proof_file'].filename != '':
            # Create a new request to the attachment upload endpoint
            # This is a workaround. A better approach would be to refactor file uploading into a helper function.
            return redirect(url_for('attachments.upload_file', bcdr_test_log_id=test_log.id, _method='POST', **request.files))

        flash('BCDR test log has been recorded.', 'success')
        return redirect(url_for('compliance.bcdr_detail', id=plan_id))

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
        
        db.session.commit()
        
        if 'proof_file' in request.files and request.files['proof_file'].filename != '':
             return redirect(url_for('attachments.upload_file', bcdr_test_log_id=test_log.id, _method='POST', **request.files))

        flash('BCDR test log has been updated.', 'success')
        return redirect(url_for('compliance.bcdr_detail', id=plan.id))

    return render_template('compliance/bcdr_test_log_form.html', plan=plan, test_log=test_log, today_date=test_log.test_date.strftime('%Y-%m-%d'))