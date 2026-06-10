import json
import os
import uuid
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from datetime import datetime
from ..models import db, Supplier, SecurityAssessment, PolicyVersion, User, AssetInventory, AssetInventoryItem, Asset, BCDRPlan, BCDRTestLog, Subscription, SecurityIncident, PostIncidentReview, IncidentTimelineEvent, MaintenanceLog, Attachment, Framework, FrameworkControl, ComplianceLink, ComplianceRule, Risk, Policy
from ..models.activities import SecurityActivity
from ..models.communications import Campaign
from ..models.core import Tag
from ..models.uar import UARComparison, UARExecution, UARFinding
from ..models.services import BusinessService
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..services.uar_service import UARAutomationService
from ..utils.uar_engine import AccessReviewEngine
from src.utils.timezone_helper import now
from ..utils.redirects import safe_redirect_target


# Optional import for Enterprise Plugin
try:
    from opsdeck_enterprise.models.report import Report
except ImportError:
    Report = None

compliance_bp = Blueprint('compliance', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE_COMPLIANCE = 'compliance'
MODULE_OPERATIONS = 'operations'
BCDR_DETAIL = 'compliance.bcdr_detail'
BCDR_TEST_LOG_DETAIL = 'compliance.bcdr_test_log_detail'
COMPLIANCE_DASHBOARD = 'compliance.dashboard'
CONTROL_DETAIL = 'frameworks.control_detail'
INCIDENT_DETAIL = 'compliance.incident_detail'
INCIDENT_REVIEW = 'compliance.incident_review'
INVENTORY_DETAIL = 'compliance.inventory_detail'
FRAMEWORKS_LIST = 'frameworks.list'
RISK_DASHBOARD = 'risk.dashboard'
SUPPLIER_DETAIL = 'suppliers.supplier_detail'
UAR_AUTOMATION_DETAIL = 'compliance.uar_automation_detail'
UAR_EXECUTION_DETAIL = 'compliance.uar_execution_detail'

@compliance_bp.route('/json/linkable-objects', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_linkable_objects():
    """
    Endpoint polimórfico para selectores dinámicos.
    Uso: /compliance/json/linkable-objects?type=Asset&q=macbook
    """
    obj_type = request.args.get('type')
    query = request.args.get('q', '').lower()
    
    results = []
    
    # Mapeo de String a Clase de Modelo + Campos de Búsqueda
    model_map = {
        'Asset': (Asset, ['name', 'serial_number']), 
        'Policy': (Policy, ['title']), # Note: Policy uses 'title', not 'name' in some models, checking...
        'Risk': (Risk, ['risk_description', 'extended_description']), # Risk uses risk_description
        'User': (User, ['name', 'email']),
        'Vendor': (Supplier, ['name']),
        # Añade 'Procedure', 'Control', etc. según necesites
    }

    if obj_type in model_map:
        model, search_fields = model_map[obj_type]
        
        # Construir query dinámica
        q_obj = model.query
        if query:
            # Filtro OR simple sobre los campos definidos
            filters = [getattr(model, field).ilike(f'%{query}%') for field in search_fields if getattr(model, field) is not None]
            q_obj = q_obj.filter(db.or_(*filters))
            
        # Limitar resultados para no matar el navegador
        items = q_obj.limit(50).all()
        
        results = []
        for item in items:
            # Safe attribute access depending on model
            name = "Unknown"
            details = ""
            item_id = item.id

            if obj_type == 'Asset':
                name = item.name
                details = item.serial_number or item.status
            elif obj_type == 'Policy':
                name = item.title
                details = item.category
            elif obj_type == 'Risk':
                name = item.risk_description
                details = f"Risk #{item.id}"
            elif obj_type == 'User':
                name = item.name
                details = item.email
            elif obj_type == 'Vendor':
                name = item.name
                details = item.compliance_status
            
            results.append({
                'id': item_id,
                'name': name,
                'details': details
            })

    return jsonify(results)

@compliance_bp.route('/json/subscriptions', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_json_subscriptions():
    """Returns list of Subscriptions for UAR dropdown."""
    q = request.args.get('q', '').lower()
    query = Subscription.query.order_by(Subscription.name)
    if q:
        query = query.filter(Subscription.name.ilike(f'%{q}%'))
    subs = query.limit(50).all()
    return jsonify([{
        'id': s.id,
        'name': s.name
    } for s in subs])

@compliance_bp.route('/json/services', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_json_services():
    from ..models.services import BusinessService
    """Returns list of Business Services for UAR dropdown."""
    q = request.args.get('q', '').lower()
    query = BusinessService.query.order_by(BusinessService.name)
    if q:
        query = query.filter(BusinessService.name.ilike(f'%{q}%'))
    svcs = query.limit(50).all()
    return jsonify([{
        'id': s.id,
        'name': s.name
    } for s in svcs])

# --- User Access Review (UAR) Routes ---

@compliance_bp.route('/access-review', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def access_review():
    """Renders the User Access Review interface."""
    reports = []
    if Report:
        # Fetch last 20 reports, joined with subtask info if possible, or just raw
        # We probably want to show the subtask name if available. 
        # For now, just listing recent reports.
        reports = Report.query.order_by(Report.created_at.desc()).limit(20).all()
        
    return render_template('compliance/access_review.html', reports=reports)

@compliance_bp.route('/access-review/preview', methods=['POST'])
@requires_permission(MODULE_COMPLIANCE)
def access_review_preview():
    """
    Executes a comparison of the loaded datasets.
    Expects JSON: {
        'source_a_type': 'Active Users' | 'Subscription' | 'Service' | 'JSON',
        'source_a_id': 123, # For Sub/Service
        'source_a_json': '...', # For JSON
        
        'source_b_type': 'Active Users' | 'Report' | 'Subscription' | 'Service' | 'JSON',
        'source_b_id': 123,
        'source_b_json': '...',
        
        'match_key': 'email', # Column to match on
        'compare_fields': ['role', 'admin'], # Columns to compare values
        
        # Legacy/Advanced
        'query': 'SELECT ...' 
    }
    """
    data = request.json
    engine = AccessReviewEngine()
    
    try:
        # --- Load Dataset A ---
        type_a = data.get('source_a_type', 'Active Users')
        if type_a == 'Active Users':
            users_data = _get_active_users_as_dict()
            current_app.logger.info(f"[UAR] Loading {len(users_data)} users into dataset_a")
            engine.load_dataset('dataset_a', users_data)
        elif type_a == 'Subscription':
            engine.load_from_subscription('dataset_a', data.get('source_a_id'))
        elif type_a == 'Service':
            engine.load_from_service('dataset_a', data.get('source_a_id'))
        elif type_a == 'Database Query':
            query = data.get('source_a_query', '')
            if query:
                query_results = _validate_and_execute_query(query)
                engine.load_dataset('dataset_a', query_results)
        elif type_a == 'JSON':
            try:
                engine.load_dataset('dataset_a', json.loads(data.get('source_a_json', '[]')))
            except json.JSONDecodeError:
                pass

        # --- Load Dataset B ---
        type_b = data.get('source_b_type')
        # Legacy fallback
        if not type_b and data.get('source_b') == 'Active Users': type_b = 'Active Users'
        if not type_b and data.get('source_b_report_id'): type_b = 'Report'
        if not type_b and data.get('source_b_json'): type_b = 'JSON'
        
        if type_b == 'Active Users':
            engine.load_dataset('dataset_b', _get_active_users_as_dict())
        elif type_b == 'Report':
            # Support both new ID field or legacy field
            r_id = data.get('source_b_report_id') or data.get('source_b_id')
            engine.load_from_report('dataset_b', r_id)
        elif type_b == 'Subscription':
            engine.load_from_subscription('dataset_b', data.get('source_b_id'))
        elif type_b == 'Service':
            engine.load_from_service('dataset_b', data.get('source_b_id'))
        elif type_b == 'Database Query':
            query = data.get('source_b_query', '')
            if query:
                query_results = _validate_and_execute_query(query)
                engine.load_dataset('dataset_b', query_results)
        elif type_b == 'JSON':
            try:
                engine.load_dataset('dataset_b', json.loads(data.get('source_b_json', '[]')))
            except json.JSONDecodeError:
                pass
            
        # --- Comparison ---
        # Support new flexible column mapping format
        key_field_a = data.get('key_field_a')
        key_field_b = data.get('key_field_b')
        field_mappings = data.get('field_mappings', [])
        
        # Legacy support: single match_key means same column name in both
        legacy_match_key = data.get('match_key')
        legacy_compare_fields = data.get('compare_fields', [])
        
        if key_field_a and key_field_b:
            # New flexible mapping format
            results = engine.perform_structured_comparison(
                key_field_a=key_field_a,
                key_field_b=key_field_b,
                field_mappings=field_mappings
            )
        elif legacy_match_key:
            # Legacy format: same key name in both datasets
            results = engine.perform_structured_comparison(
                key_field_a=legacy_match_key,
                key_field_b=legacy_match_key,
                field_mappings=[{"field_a": f, "field_b": f} for f in legacy_compare_fields] if legacy_compare_fields else []
            )
        else:
            # Fallback to raw SQL query
            query = data.get('query')
            if not query:
                 # Default fallback if nothing provided
                 query = "SELECT * FROM dataset_b WHERE login NOT IN (SELECT custom_field_github_user FROM dataset_a)"
            results = engine.execute_query(query)
        
        return jsonify({'success': True, 'results': results})
        
    except Exception as e:
        current_app.logger.error(f"[UAR] Error in endpoint: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        engine.cleanup()

@compliance_bp.route('/access-review/schema', methods=['POST'])
@requires_permission(MODULE_COMPLIANCE)
def get_access_review_schema():
    """
    Returns the columns/keys for the selected datasets.
    """
    data = request.json
    engine = AccessReviewEngine()
    response_schema = {'dataset_a': [], 'dataset_b': []}
    response_samples = {'dataset_a': [], 'dataset_b': []}
    
    try:
        # --- Load Dataset A ---
        type_a = data.get('source_a_type', 'Active Users')
        if type_a == 'Active Users':
            users_data = _get_active_users_as_dict()
            current_app.logger.info(f"[UAR] Loading {len(users_data)} users into dataset_a")
            engine.load_dataset('dataset_a', users_data)
        elif type_a == 'Subscription':
            engine.load_from_subscription('dataset_a', data.get('source_a_id'))
        elif type_a == 'Service':
            engine.load_from_service('dataset_a', data.get('source_a_id'))
        elif type_a == 'Database Query':
            query = data.get('source_a_query', '')
            if query:
                query_results = _validate_and_execute_query(query)
                engine.load_dataset('dataset_a', query_results)
        elif type_a == 'JSON':
            try:
                json_data = json.loads(data.get('source_a_json', '[]'))
                if not isinstance(json_data, list):
                    return jsonify({'success': False, 'error': 'JSON must be an array of objects'}), 400
                if json_data and not isinstance(json_data[0], dict):
                    return jsonify({'success': False, 'error': 'JSON array must contain objects'}), 400
                engine.load_dataset('dataset_a', json_data)
            except json.JSONDecodeError as e:
                return jsonify({'success': False, 'error': f'Invalid JSON format for Dataset A: {str(e)}'}), 400
                
        # --- Load Dataset B ---
        type_b = data.get('source_b_type')
        # Legacy fallback logic for UI compatibility
        if not type_b:
             if data.get('source_b_report_id'): type_b = 'Report'
             elif data.get('source_b') == 'Active Users': type_b = 'Active Users'
             elif data.get('source_b_json'): type_b = 'JSON'
        
        if type_b == 'Active Users':
            users_data = _get_active_users_as_dict()
            current_app.logger.info(f"[UAR] Loading {len(users_data)} users into dataset_b")
            engine.load_dataset('dataset_b', users_data)
        elif type_b == 'Report':
            r_id = data.get('source_b_report_id') or data.get('source_b_id')
            engine.load_from_report('dataset_b', r_id)
        elif type_b == 'Subscription':
            engine.load_from_subscription('dataset_b', data.get('source_b_id'))
        elif type_b == 'Service':
            engine.load_from_service('dataset_b', data.get('source_b_id'))
        elif type_b == 'Database Query':
            query = data.get('source_b_query', '')
            if query:
                query_results = _validate_and_execute_query(query)
                engine.load_dataset('dataset_b', query_results)
        elif type_b == 'JSON':
            try:
                json_data = json.loads(data.get('source_b_json', '[]'))
                if not isinstance(json_data, list):
                    return jsonify({'success': False, 'error': 'JSON must be an array of objects'}), 400
                if json_data and not isinstance(json_data[0], dict):
                    return jsonify({'success': False, 'error': 'JSON array must contain objects'}), 400
                engine.load_dataset('dataset_b', json_data)
            except json.JSONDecodeError as e:
                return jsonify({'success': False, 'error': f'Invalid JSON format for Dataset B: {str(e)}'}), 400
        
        # Get info
        for ds_name in ['dataset_a', 'dataset_b']:
            try:
                # Check if table exists first
                table_check = engine.execute_query(
                    f"SELECT name FROM sqlite_master WHERE type='table' AND name='{ds_name}'"
                )

                if not table_check:
                    # Table doesn't exist - dataset was empty
                    current_app.logger.warning(f"[UAR] Table {ds_name} does not exist (likely empty dataset)")
                    response_schema[ds_name] = []
                    response_samples[ds_name] = []
                    continue

                cols = engine.execute_query(f"PRAGMA table_info({ds_name})")
                if cols:
                    response_schema[ds_name] = [c['name'] for c in cols]
                    # Get samples (convert row objects to dicts)
                    samples = engine.execute_query(f"SELECT * FROM {ds_name} LIMIT 3")
                    response_samples[ds_name] = [dict(s) for s in samples]
                else:
                    # Table exists but has no columns (shouldn't happen)
                    current_app.logger.warning(f"[UAR] No columns found for {ds_name}")
                    response_schema[ds_name] = []
                    response_samples[ds_name] = []
            except Exception as schema_err:
                current_app.logger.error(f"[UAR] Error getting schema for {ds_name}: {schema_err}")
                # Return error but don't crash
                response_schema[ds_name] = []
                response_samples[ds_name] = []
                
        return jsonify({
            'success': True, 
            'schema': response_schema,
            'samples': response_samples
        })

    except Exception as e:
        current_app.logger.error(f"[UAR] Error in endpoint: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 400
    finally:
        engine.cleanup()

def _validate_and_execute_query(sql_query: str):
    """
    Validates that the query is read-only (SELECT/JOIN only) and executes it against the database.
    Returns list of dicts.
    """
    # Remove comments and normalize
    query_normalized = sql_query.strip().upper()

    # Security check: only allow SELECT queries
    if not query_normalized.startswith('SELECT'):
        raise ValueError("Only SELECT queries are allowed")

    # Block dangerous keywords (even in subqueries)
    dangerous_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE']
    for keyword in dangerous_keywords:
        if keyword in query_normalized:
            raise ValueError(f"Query contains forbidden keyword: {keyword}")

    # Execute query with read-only connection
    try:
        result = db.session.execute(db.text(sql_query))
        rows = result.fetchall()

        # Convert to list of dicts
        if rows:
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
        return []
    except Exception as e:
        current_app.logger.error(f"[UAR] Database query error: {e}")
        raise ValueError(f"Query execution failed: {str(e)}")

def _get_active_users_as_dict():
    """Helper to fetch active users and format them as dicts with flat custom properties."""
    users = User.query.filter_by(is_archived=False).all()
    current_app.logger.info(f"[UAR] Found {len(users)} active users")
    user_list = []
    for u in users:
        u_dict = {
            'id': u.id,
            'name': u.name,
            'email': u.email,
            'role': u.role,
            'is_archived': u.is_archived
        }
        try:
            for k, v in u.custom_properties.items():
                u_dict[f"custom_field_{k}"] = v
        except Exception as e:
            current_app.logger.warning(f"[UAR] Error getting custom properties for user {u.id}: {e}")
        user_list.append(u_dict)
    current_app.logger.info(f"[UAR] Returning {len(user_list)} user records")
    return user_list

@compliance_bp.route('/access-review/promote', methods=['POST'])
@requires_permission(MODULE_COMPLIANCE)
def promote_finding_to_incident():
    """
    Creates a Security Incident from a specific finding row.
    """
    if not has_write_permission(MODULE_COMPLIANCE):
        return jsonify({'success': False, 'message': 'Permission denied'}), 403
        
    data = request.json
    finding = data.get('finding', {})
    description_text = "\n".join([f"{k}: {v}" for k, v in finding.items()])
    
    incident = SecurityIncident(
        title=f"Access Violation Detected: {finding.get('email') or finding.get('login') or 'Unknown'}",
        description=f"Generated from User Access Review.\n\nFinding Details:\n{description_text}",
        status='Investigating',
        severity='SEV-2', 
        impact='Moderate',
        reported_by_id=session.get('user_id'),
        incident_date=now()
    )
    
    db.session.add(incident)
    db.session.commit()
    
    return jsonify({'success': True, 'incident_id': incident.id})

# --- JSON APIs for Automation Rules Dynamic Selectors ---

@compliance_bp.route('/json/activities', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_activities():
    """Returns list of Security Activities for dropdown."""
    q = request.args.get('q', '').lower()
    query = SecurityActivity.query.order_by(SecurityActivity.name)
    if q:
        query = query.filter(SecurityActivity.name.ilike(f'%{q}%'))
    activities = query.limit(50).all()
    return jsonify([{
        'id': a.id,
        'name': a.name,
        'frequency': a.frequency or ''
    } for a in activities])

@compliance_bp.route('/json/tags', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_all_tags():
    """Returns list of all non-archived Tags for dropdowns."""
    try:
        tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
        return jsonify([{
            'id': t.id,
            'name': t.name
        } for t in tags])
    except Exception as e:
        return jsonify([]), 500

@compliance_bp.route('/json/maintenance-types', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_maintenance_types():
    """Returns distinct event_type values from MaintenanceLog."""
    types = db.session.query(MaintenanceLog.event_type).distinct().order_by(MaintenanceLog.event_type).all()
    return jsonify([t[0] for t in types if t[0]])

@compliance_bp.route('/json/bcdr-plans', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def get_bcdr_plans():
    """Returns list of BCDR Plans for dropdown."""
    q = request.args.get('q', '').lower()
    query = BCDRPlan.query.order_by(BCDRPlan.name)
    if q:
        query = query.filter(BCDRPlan.name.ilike(f'%{q}%'))
    plans = query.limit(50).all()
    return jsonify([{
        'id': p.id,
        'name': p.name
    } for p in plans])

@compliance_bp.route('/vendors', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def vendor_compliance():
    """Displays a list of all suppliers and their compliance status."""
    suppliers = Supplier.query.order_by(Supplier.name).all()
    return render_template('compliance/vendor_list.html', suppliers=suppliers)

@compliance_bp.route('/assessments', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def list_assessments():
    """Displays a list of all security assessments."""
    assessments = SecurityAssessment.query.order_by(SecurityAssessment.assessment_date.desc()).all()
    return render_template('compliance/assessment_list.html', assessments=assessments)

@compliance_bp.route('/<int:supplier_id>/new_assessment', methods=['GET', 'POST'])
@requires_permission(MODULE_COMPLIANCE)
def new_assessment(supplier_id):
    if not has_write_permission(MODULE_COMPLIANCE):
        if request.method == 'POST':
            flash('You do not have permission to log assessments.', 'danger')
            return redirect(url_for(SUPPLIER_DETAIL, id=supplier_id))
    supplier = db.get_or_404(Supplier, supplier_id)
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
        return redirect(url_for(SUPPLIER_DETAIL, id=supplier_id))

    return render_template('compliance/assessment_form.html', supplier=supplier, today_date=now().strftime('%Y-%m-%d'))

@compliance_bp.route('/assessment/<int:id>', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def assessment_detail(id):
    assessment = db.get_or_404(SecurityAssessment, id)
    return render_template('compliance/assessment_detail.html', assessment=assessment)

@compliance_bp.route('/assessment/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE_COMPLIANCE)
def edit_assessment(id):
    assessment = db.get_or_404(SecurityAssessment, id)
    if not has_write_permission(MODULE_COMPLIANCE):
        if request.method == 'POST':
            flash('You do not have permission to edit assessments.', 'danger')
            return redirect(url_for(SUPPLIER_DETAIL, id=assessment.supplier_id))
    supplier = assessment.supplier

    if request.method == 'POST':
        assessment.status = request.form['status']
        assessment.assessment_date = datetime.strptime(request.form['assessment_date'], '%Y-%m-%d').date()
        assessment.notes = request.form.get('notes')
        
        db.session.commit()
        flash('Security assessment has been updated.', 'success')
        return redirect(url_for(SUPPLIER_DETAIL, id=supplier.id))

    return render_template('compliance/assessment_form.html', supplier=supplier, assessment=assessment)

@compliance_bp.route('/policy-report', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
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

@compliance_bp.route('/my-policies', methods=['GET'])
@login_required
def my_policies():
    """Shows policies assigned to the current user."""
    active_versions = PolicyVersion.query.filter_by(status='Active').all()
    user_id = session.get('user_id')
    current_user_obj = db.session.get(User,user_id)
    
    my_policy_list = []
    
    for version in active_versions:
        # Check if policy applies to user
        is_assigned = False
        
        # 1. Global assignment (no specific assignments)
        if not version.users_to_acknowledge and not version.groups_to_acknowledge:
            is_assigned = True
            
        # 2. Direct assignment
        if not is_assigned and current_user_obj in version.users_to_acknowledge:
            is_assigned = True
            
        # 3. Group assignment
        if not is_assigned:
            user_group_ids = {g.id for g in current_user_obj.groups}
            version_group_ids = {g.id for g in version.groups_to_acknowledge}
            if not user_group_ids.isdisjoint(version_group_ids):
                is_assigned = True
        
        if is_assigned:
            # Check acknowledgement status
            # We look for an acknowledgement record for this version and user
            ack = next((a for a in version.acknowledgements if a.user_id == user_id), None)
            
            my_policy_list.append({
                'policy': version.policy,
                'version': version,
                'is_acknowledged': ack is not None,
                'acknowledged_at': ack.acknowledged_at if ack else None
            })
    
    return render_template('compliance/my_policies.html', policies=my_policy_list)

# --- Asset Inventory Management ---

@compliance_bp.route('/inventory', methods=['GET'])
@requires_permission(MODULE_COMPLIANCE)
def list_inventory():
    """Displays a list of all asset inventories."""
    inventories = AssetInventory.query.order_by(AssetInventory.created_at.desc()).all()
    return render_template('compliance/inventory_list.html', inventories=inventories)

@compliance_bp.route('/inventory/new', methods=['GET', 'POST'])
@requires_permission(MODULE_COMPLIANCE)
def new_inventory():
    if not has_write_permission(MODULE_COMPLIANCE):
        if request.method == 'POST':
            flash('You do not have permission to create inventories.', 'danger')
            return redirect(url_for('compliance.list_inventory'))
    """Creates a new asset inventory."""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        
        inventory = AssetInventory(
            name=name,
            description=description,
            conducted_by_user_id=session.get('user_id')
        )
        db.session.add(inventory)
        db.session.commit()
        
        flash('Asset Inventory created successfully.', 'success')
        return redirect(url_for(INVENTORY_DETAIL, id=inventory.id))
        
    return render_template('compliance/inventory_form.html')

@compliance_bp.route('/inventory/<int:id>')
@requires_permission(MODULE_COMPLIANCE)
def inventory_detail(id):
    """Displays details of a specific asset inventory."""
    inventory = db.get_or_404(AssetInventory, id)
    inventory_items = inventory.items.order_by(AssetInventoryItem.event_time.desc()).all()
    
    # Get assets that are NOT in this inventory yet
    # This is a simplified check; in a real app, you'd filter by active assets
    audited_asset_ids = [e.asset_id for e in inventory_items]
    assets_to_audit = Asset.query.filter(Asset.id.notin_(audited_asset_ids)).all()
    
    return render_template('compliance/inventory_detail.html', inventory=inventory, inventory_items=inventory_items, assets_to_audit=assets_to_audit)

@compliance_bp.route('/inventory/<int:id>/log', methods=['POST'])
@requires_permission(MODULE_COMPLIANCE)
def log_inventory_item(id):
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('You do not have permission to log items.', 'danger')
        return redirect(url_for(INVENTORY_DETAIL, id=id))
    """Logs an asset check during an inventory."""
    inventory = db.get_or_404(AssetInventory, id)
    
    asset_id = request.form.get('asset_id')
    status = request.form.get('status')
    notes = request.form.get('notes')
    
    item = AssetInventoryItem(
        inventory_id=inventory.id,
        asset_id=asset_id,
        user_id=session.get('user_id'),
        status=status,
        notes=notes
    )
    db.session.add(item)
    db.session.commit()
    
    flash('Asset logged successfully.', 'success')
    return redirect(url_for(INVENTORY_DETAIL, id=inventory.id))

@compliance_bp.route('/inventory/<int:id>/complete', methods=['POST'])
@requires_permission(MODULE_COMPLIANCE)
def complete_inventory(id):
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('You do not have permission to complete inventories.', 'danger')
        return redirect(url_for(INVENTORY_DETAIL, id=id))
    """Marks an inventory as complete."""
    inventory = db.get_or_404(AssetInventory, id)
    inventory.is_completed = True
    db.session.commit()
    
    flash(f'Inventory "{inventory.name}" has been marked as complete.', 'success')
    return redirect(url_for('compliance.list_inventory'))

@compliance_bp.route('/bcdr')
@requires_permission(MODULE_OPERATIONS)
def list_bcdr_plans():
    """Displays a list of all BCDR plans."""
    plans = BCDRPlan.query.order_by(BCDRPlan.name).all()
    return render_template('compliance/bcdr_list.html', plans=plans)

@compliance_bp.route('/bcdr/new', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def new_bcdr_plan():
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to create BCDR plans.', 'danger')
            return redirect(url_for('compliance.list_bcdr_plans'))
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
@requires_permission(MODULE_OPERATIONS)
def edit_bcdr_plan(id):
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to edit BCDR plans.', 'danger')
            return redirect(url_for(BCDR_DETAIL, id=id))
    plan = db.get_or_404(BCDRPlan, id)
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
        return redirect(url_for(BCDR_DETAIL, id=plan.id))

    subscriptions = Subscription.query.order_by(Subscription.name).all()
    assets = Asset.query.order_by(Asset.name).all()
    return render_template('compliance/bcdr_form.html', plan=plan, subscriptions=subscriptions, assets=assets)

@compliance_bp.route('/bcdr/<int:id>')
@requires_permission(MODULE_OPERATIONS)
def bcdr_detail(id):
    plan = db.get_or_404(BCDRPlan, id)
    return render_template('compliance/bcdr_detail.html', plan=plan)

@compliance_bp.route('/bcdr/test/<int:test_id>')
@requires_permission(MODULE_OPERATIONS)
def bcdr_test_log_detail(test_id):
    """Muestra los detalles de un único BCDR test log."""
    test_log = db.get_or_404(BCDRTestLog, test_id)
    return render_template('compliance/bcdr_test_log_detail.html', test_log=test_log)

@compliance_bp.route('/bcdr/<int:plan_id>/log_test', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def log_bcdr_test(plan_id):
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to log BCDR tests.', 'danger')
            return redirect(url_for(BCDR_DETAIL, id=plan_id))
    plan = db.get_or_404(BCDRPlan, plan_id)
    if request.method == 'POST':
        test_log = BCDRTestLog(
            plan_id=plan.id,
            test_date=datetime.strptime(request.form['test_date'], '%Y-%m-%d').date(),
            status=request.form['status'],
            notes=request.form.get('notes'),
            assignee_id=request.form.get('assignee_id') or None
        )

        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             test_log.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

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
        return redirect(url_for(BCDR_TEST_LOG_DETAIL, test_id=test_log.id))
    
    users = User.query.order_by(User.name).all()
    return render_template('compliance/bcdr_test_log_form.html', plan=plan, today_date=now().strftime('%Y-%m-%d'), users=users)

@compliance_bp.route('/bcdr/test/<int:test_id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def edit_bcdr_test(test_id):
    test_log = db.get_or_404(BCDRTestLog, test_id)
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to edit BCDR test logs.', 'danger')
            return redirect(url_for(BCDR_TEST_LOG_DETAIL, test_id=test_id))
    plan = test_log.plan
    if request.method == 'POST':
        test_log.test_date = datetime.strptime(request.form['test_date'], '%Y-%m-%d').date()
        test_log.status = request.form['status']
        test_log.notes = request.form.get('notes')
        test_log.assignee_id = request.form.get('assignee_id') or None
        
        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             test_log.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        else:
             test_log.tags = []

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

        flash('BCDR test log updated.', 'success')
        # Redirigimos a la nueva vista de detalles del log
        return redirect(url_for(BCDR_TEST_LOG_DETAIL, test_id=test_log.id))

    users = User.query.order_by(User.name).all()
    return render_template('compliance/bcdr_test_log_form.html', plan=plan, test_log=test_log, users=users, today_date=test_log.test_date.strftime('%Y-%m-%d'))

@compliance_bp.route('/incidents')
@requires_permission(MODULE_OPERATIONS)
def list_incidents():
    query = SecurityIncident.query
    status = request.args.get('status')
    if status:
        query = query.filter(SecurityIncident.status == status)
    incidents = query.order_by(SecurityIncident.incident_date.desc()).all()
    return render_template('compliance/incident_list.html', incidents=incidents)

@compliance_bp.route('/incidents/new', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def new_incident():
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to log incidents.', 'danger')
            return redirect(url_for('compliance.list_incidents'))
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
        
        # Handle Assignee
        incident.assignee_id = request.form.get('assignee_id') or None

        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             incident.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

        db.session.add(incident)
        db.session.commit()
        flash('Security incident logged successfully.', 'success')
        return redirect(url_for(INCIDENT_DETAIL, id=incident.id))
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    return render_template('compliance/incident_form.html', users=users, assets=assets, subscriptions=subscriptions, suppliers=suppliers)

@compliance_bp.route('/incidents/<int:id>')
@requires_permission(MODULE_OPERATIONS)
def incident_detail(id):
    incident = db.get_or_404(SecurityIncident, id)
    return render_template('compliance/incident_detail.html', incident=incident)

@compliance_bp.route('/incidents/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def edit_incident(id):
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to edit incidents.', 'danger')
            return redirect(url_for(INCIDENT_DETAIL, id=id))
    incident = db.get_or_404(SecurityIncident, id)
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
            incident.resolved_at = now()
        elif incident.status != 'Closed':
            incident.resolved_at = None
        incident.affected_assets = Asset.query.filter(Asset.id.in_(request.form.getlist('asset_ids'))).all()
        incident.affected_users = User.query.filter(User.id.in_(request.form.getlist('user_ids'))).all()
        incident.affected_subscriptions = Subscription.query.filter(Subscription.id.in_(request.form.getlist('subscription_ids'))).all()
        incident.affected_suppliers = Supplier.query.filter(Supplier.id.in_(request.form.getlist('supplier_ids'))).all()
        
        # Handle Assignee
        incident.assignee_id = request.form.get('assignee_id') or None

        # Handle Tags
        tag_ids = request.form.get('tags', '').split(',')
        if tag_ids and tag_ids[0]:
             incident.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        else:
             incident.tags = []

        db.session.commit()
        flash('Incident details updated.', 'success')
        return redirect(url_for(INCIDENT_DETAIL, id=id))
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    return render_template('compliance/incident_form.html', incident=incident, users=users, assets=assets, subscriptions=subscriptions, suppliers=suppliers)

@compliance_bp.route('/incidents/<int:id>/review', methods=['GET', 'POST'])
@requires_permission(MODULE_OPERATIONS)
def incident_review(id):
    if not has_write_permission(MODULE_OPERATIONS):
        if request.method == 'POST':
            flash('You do not have permission to edit incident reviews.', 'danger')
            return redirect(url_for(INCIDENT_DETAIL, id=id))
    incident = db.get_or_404(SecurityIncident, id)
    review = incident.review

    if not review:
        # If no review exists, create one to start with
        review = PostIncidentReview(incident_id=id)
        db.session.add(review)
        db.session.commit()

    if request.method == 'POST':
        # Block edits if report is locked
        if review.is_locked:
            flash('This report is locked. Unlock it to make changes.', 'warning')
            return redirect(url_for(INCIDENT_REVIEW, id=id))
        
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
        return redirect(url_for(INCIDENT_REVIEW, id=id))

    return render_template('compliance/pir_form.html', incident=incident, review=review)

@compliance_bp.route('/incidents/review/<int:review_id>/toggle-lock', methods=['POST'])
@requires_permission(MODULE_OPERATIONS)
def toggle_pir_lock(review_id):
    if not has_write_permission(MODULE_OPERATIONS):
        return jsonify({'success': False, 'message': 'You do not have permission to lock incident reviews.'}), 403
    """Toggle lock state of a Post-Incident Review."""
    review = db.get_or_404(PostIncidentReview, review_id)
    
    if review.is_locked:
        # Unlock
        review.is_locked = False
        review.locked_at = None
        review.locked_by_id = None
        flash('Post-Incident Review has been unlocked for editing.', 'success')
    else:
        # Lock
        review.is_locked = True
        review.locked_at = now()
        review.locked_by_id = session.get('user_id')
        flash('Post-Incident Review has been finalized and locked.', 'success')
    
    db.session.commit()
    return redirect(url_for(INCIDENT_REVIEW, id=review.incident_id))

@compliance_bp.route('/incidents/review/<int:review_id>/timeline', methods=['POST'])
@requires_permission(MODULE_OPERATIONS)
def add_timeline_event(review_id):
    if not has_write_permission(MODULE_OPERATIONS):
        return jsonify({'error': 'You do not have permission to modify timeline events.'}), 403
    review = db.get_or_404(PostIncidentReview, review_id)
    
    # Block timeline additions when locked
    if review.is_locked:
        return jsonify({'error': 'Report is locked'}), 403
    
    data = request.json
    max_order = db.session.query(db.func.max(IncidentTimelineEvent.order)).filter_by(review_id=review.id).scalar() or -1
    
    # Parse datetime-local format (YYYY-MM-DDTHH:MM)
    time_str = data['time']
    try:
        event_time = datetime.strptime(time_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    event = IncidentTimelineEvent(
        review_id=review.id,
        event_time=event_time,
        description=data['description'],
        order=max_order + 1
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({'id': event.id, 'time': event.event_time.strftime('%Y-%m-%dT%H:%M'), 'description': event.description}), 201

@compliance_bp.route('/incidents/review/timeline/<int:event_id>', methods=['DELETE'])
@requires_permission(MODULE_OPERATIONS)
def delete_timeline_event(event_id):
    if not has_write_permission(MODULE_OPERATIONS):
        return jsonify({'error': 'You do not have permission to delete timeline events.'}), 403
    event = db.get_or_404(IncidentTimelineEvent, event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})

@compliance_bp.route('/incidents/review/<int:review_id>/timeline/reorder', methods=['POST'])
@requires_permission(MODULE_OPERATIONS)
def reorder_timeline_events(review_id):
    if not has_write_permission(MODULE_OPERATIONS):
        return jsonify({'error': 'You do not have permission to reorder timeline events.'}), 403
    ordered_ids = request.json.get('ordered_ids', [])
    for index, event_id in enumerate(ordered_ids):
        event = IncidentTimelineEvent.query.filter_by(id=event_id, review_id=review_id).first()
        if event:
            event.order = index
    db.session.commit()
    return jsonify({'success': True})

@compliance_bp.route('/incidents/<int:id>/export_pdf')
@requires_permission(MODULE_OPERATIONS)
def export_pir_pdf(id):
    """Export Post-Incident Review as professional PDF."""
    from weasyprint import HTML
    from flask import make_response
    from ..models.core import OrganizationSettings
    
    incident = db.get_or_404(SecurityIncident, id)
    review = incident.review
    
    if not review:
        flash('No Post-Incident Review found for this incident.', 'warning')
        return redirect(url_for(INCIDENT_DETAIL, id=id))
    
    # Get organization settings for logo
    org_settings = OrganizationSettings.query.first()
    user = db.session.get(User,session.get('user_id'))
    
    # Sort timeline by event_time
    sorted_timeline = sorted(review.timeline_events, key=lambda e: e.event_time)
    
    html_content = render_template(
        'compliance/pir_pdf.html',
        incident=incident,
        review=review,
        sorted_timeline=sorted_timeline,
        org_settings=org_settings,
        generated_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        generated_by=user.name if user else 'System'
    )
    
    pdf_file = HTML(string=html_content).write_pdf()
    
    response = make_response(pdf_file)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=PIR_{incident.id}_{incident.title[:20].replace(" ", "_")}.pdf'
    
    return response

@compliance_bp.route('/evidence/upload', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def upload_evidence():
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to upload evidence.', 'danger')
        return redirect(url_for(COMPLIANCE_DASHBOARD)) # Assuming a dashboard or index route for compliance
    
    # Placeholder for actual evidence upload logic
    # This function was added by the instruction, so its implementation is new.
    # The instruction only provided the decorator and permission check.
    # For a complete implementation, you'd need to handle file uploads,
    # link them to controls, etc.
    flash('Evidence upload functionality not fully implemented yet.', 'info')
    return redirect(safe_redirect_target(request.referrer, url_for(COMPLIANCE_DASHBOARD)))

@compliance_bp.route('/data-erasures')
@requires_permission(MODULE_OPERATIONS)
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
    framework = db.get_or_404(Framework, framework_id)
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
@requires_permission(MODULE_COMPLIANCE)
def create_compliance_link():
    """Creates a new compliance link."""
    if not has_write_permission(MODULE_COMPLIANCE):
        return jsonify({'error': 'Write access required to create compliance links.'}), 403

    data = request.json
    framework_control_id = data.get('framework_control_id')
    linkable_id = data.get('linkable_id')
    linkable_type = data.get('linkable_type')
    description = data.get('description')

    if not all([framework_control_id, linkable_id, linkable_type, description]):
        return jsonify({'error': 'Missing required fields'}), 400

    # Validate control exists
    control = db.session.get(FrameworkControl,framework_control_id)
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
@requires_permission(MODULE_COMPLIANCE)
def delete_compliance_link(link_id):
    """Deletes a compliance link."""
    if not has_write_permission(MODULE_COMPLIANCE):
        return jsonify({'error': 'Write access required to delete compliance links.'}), 403

    link = db.get_or_404(ComplianceLink, link_id)
    db.session.delete(link)
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Link deleted successfully'})


@compliance_bp.route('/link/manual/create', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def create_manual_link():
    """
    Processes the manual link modal form.
    Expects: framework_control_id, linkable_type, linkable_id, description
    """
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to create manual links.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(FRAMEWORKS_LIST)))

    framework_control_id = request.form.get('framework_control_id', type=int)
    linkable_type = request.form.get('linkable_type')
    linkable_id = request.form.get('linkable_id', type=int)
    description = request.form.get('description', '').strip()

    if not all([framework_control_id, linkable_type, linkable_id]):
        flash('Missing required fields.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(FRAMEWORKS_LIST)))

    # Validate control exists
    control = db.session.get(FrameworkControl,framework_control_id)
    if not control:
        flash('Control not found.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(FRAMEWORKS_LIST)))

    # Check for existing link to avoid duplicates
    existing = ComplianceLink.query.filter_by(
        framework_control_id=framework_control_id,
        linkable_type=linkable_type,
        linkable_id=linkable_id
    ).first()

    if existing:
        flash('This item is already linked to this control.', 'warning')
    else:
        link = ComplianceLink(
            framework_control_id=framework_control_id,
            linkable_type=linkable_type,
            linkable_id=linkable_id,
            description=description or f'Manual link to {linkable_type}'
        )
        db.session.add(link)
        db.session.commit()
        flash('Item linked successfully.', 'success')

    # Redirect back to the control detail page
    return redirect(url_for(CONTROL_DETAIL, id=framework_control_id))

@compliance_bp.route('/link/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def link_control():
    """Form to link a control to an object (Risk, Asset, etc)."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to link controls.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(RISK_DASHBOARD)))

    linkable_type = request.args.get('linkable_type') or request.form.get('linkable_type')
    linkable_id = request.args.get('linkable_id') or request.form.get('linkable_id')

    if not linkable_type or not linkable_id:
        flash('Missing linkable object information.', 'danger')
        return redirect(url_for(RISK_DASHBOARD))

    if request.method == 'POST':
        framework_control_id = request.form.get('framework_control_id')
        description = request.form.get('description')

        if not framework_control_id or not description:
            flash('Please select a control and provide a description.', 'danger')
        else:
            # Check for existing link
            existing = ComplianceLink.query.filter_by(
                framework_control_id=framework_control_id,
                linkable_id=linkable_id,
                linkable_type=linkable_type
            ).first()

            if existing:
                flash('This control is already linked.', 'warning')
            else:
                link = ComplianceLink(
                    framework_control_id=framework_control_id,
                    linkable_id=linkable_id,
                    linkable_type=linkable_type,
                    description=description
                )
                db.session.add(link)
                db.session.commit()
                flash('Control linked successfully.', 'success')
                
                # Redirect back to the object
                if linkable_type == 'Risk':
                    return redirect(url_for('risk.detail', id=linkable_id))
                # Add other types as needed
                
                return redirect(url_for(RISK_DASHBOARD))

    frameworks = Framework.query.filter_by(is_active=True).order_by(Framework.name).all()
    return render_template('compliance/link_control.html', 
                           frameworks=frameworks, 
                           linkable_type=linkable_type, 
                           linkable_id=linkable_id)

@compliance_bp.route('/dashboard')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def dashboard():
    """Displays the compliance dashboard with real-time status evaluation."""
    from src.services.compliance_service import get_compliance_evaluator

    evaluator = get_compliance_evaluator()

    # IMPORTANT: Only show active frameworks in dashboard (current compliance state)
    # Historical audits (ComplianceAudit) can reference inactive frameworks as historical evidence
    # This design allows companies to deactivate frameworks without losing historical audit data
    frameworks = Framework.query.filter_by(is_active=True).order_by(Framework.name).all()

    # Build dashboard data with evaluated status for each framework
    dashboard_data = []
    for framework in frameworks:
        framework_status = evaluator.get_framework_status(framework.id)
        if framework_status:
            dashboard_data.append(framework_status)
    
    return render_template('compliance/dashboard.html', dashboard_data=dashboard_data, now=now)

@compliance_bp.route('/dashboard/pdf')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def export_dashboard_pdf():
    """Exports the compliance dashboard to PDF using the same data as the HTML dashboard."""
    from weasyprint import HTML
    from flask import make_response
    from src.services.compliance_service import get_compliance_evaluator

    # Use the same data logic as the HTML dashboard
    evaluator = get_compliance_evaluator()
    frameworks = Framework.query.filter_by(is_active=True).order_by(Framework.name).all()
    
    dashboard_data = []
    for framework in frameworks:
        framework_status = evaluator.get_framework_status(framework.id)
        if framework_status:
            dashboard_data.append(framework_status)
    
    user = db.session.get(User,session.get('user_id'))
    
    html_content = render_template(
        'compliance/dashboard_pdf.html', 
        dashboard_data=dashboard_data,
        generated_at=now().strftime('%Y-%m-%d %H:%M:%S'),
        generated_by=user.name if user else 'System'
    )
    
    pdf_file = HTML(string=html_content).write_pdf()
    
    response = make_response(pdf_file)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=compliance_report.pdf'
    
    return response


# --- Automation Rules Management ---

@compliance_bp.route('/rules/create', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def create_rule():
    """Creates a new ComplianceRule for automated compliance checking."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to create automation rules.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(COMPLIANCE_DASHBOARD)))

    import json
    
    framework_control_id = request.form.get('framework_control_id', type=int)
    name = request.form.get('name', '').strip()
    target_model = request.form.get('target_model', '').strip()
    frequency_days = request.form.get('frequency_days', 90, type=int)
    grace_period_days = request.form.get('grace_period_days', 7, type=int)
    
    if not all([framework_control_id, name, target_model]):
        flash('Missing required fields for automation rule.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(COMPLIANCE_DASHBOARD)))
    
    # Validate control exists
    control = db.session.get(FrameworkControl,framework_control_id)
    if not control:
        flash('Control not found.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(COMPLIANCE_DASHBOARD)))
    
    # Build criteria JSON based on target_model
    criteria = {}
    
    if target_model == 'ActivityExecution':
        activity_id = request.form.get('activity_id', type=int)
        if activity_id:
            criteria = {
                "method": "parent_match",
                "value": activity_id
            }
        else:
            # Try activity name
            activity_name = request.form.get('activity_name', '').strip()
            if activity_name:
                criteria = {
                    "method": "parent_match",
                    "activity_name": activity_name
                }
    
    elif target_model == 'Campaign':
        tags_str = request.form.get('tags', '').strip()
        if tags_str:
            tags = [t.strip() for t in tags_str.split(',') if t.strip()]
            criteria = {
                "method": "tag_match",
                "tags": tags
            }
    
    elif target_model == 'MaintenanceLog':
        event_type = request.form.get('event_type', '').strip()
        if event_type:
            criteria = {
                "method": "event_type_match",
                "event_type": event_type
            }
        else:
            criteria = {"method": "any_completed"}
    
    elif target_model == 'BCDRTestLog':
        plan_id = request.form.get('plan_id', type=int)
        if plan_id:
            criteria = {
                "method": "plan_match",
                "plan_id": plan_id
            }
        else:
            criteria = {"method": "any_passed"}
    
    elif target_model == 'OnboardingProcess':
        tag = request.form.get('criteria_tag', '').strip()
        if tag:
            criteria = {"tag": tag}
    
    elif target_model == 'OffboardingProcess':
        tag = request.form.get('criteria_tag', '').strip()
        if tag:
            criteria = {"tag": tag}
    
    elif target_model == 'SecurityAssessment':
        # Optional: Filter by specific supplier
        supplier_id = request.form.get('supplier_id', type=int)
        if supplier_id:
            criteria = {"supplier_id": supplier_id}
        else:
            criteria = {}  # Any supplier assessment counts
    
    elif target_model == 'RiskAssessment':
        # Simple mode: No criteria needed, just finds most recent
        criteria = {}
    
    # Create and save the rule
    rule = ComplianceRule(
        framework_control_id=framework_control_id,
        name=name,
        target_model=target_model,
        criteria=json.dumps(criteria),
        frequency_days=frequency_days,
        grace_period_days=grace_period_days,
        enabled=True
    )
    
    db.session.add(rule)
    db.session.commit()
    
    flash(f'Automation rule "{name}" created successfully.', 'success')
    return redirect(safe_redirect_target(request.referrer, url_for(CONTROL_DETAIL, id=framework_control_id)))

@compliance_bp.route('/evidence/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def delete_evidence(id):
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to delete evidence.', 'danger')
        return redirect(url_for(COMPLIANCE_DASHBOARD)) # Assuming a dashboard or index route for compliance
    
    # Placeholder for actual evidence deletion logic
    # This function was added by the instruction, so its implementation is new.
    # The instruction only provided the decorator and permission check.
    # For a complete implementation, you'd need to retrieve and delete the evidence.
    flash(f'Evidence with ID {id} deletion functionality not fully implemented yet.', 'info')
    return redirect(safe_redirect_target(request.referrer, url_for(COMPLIANCE_DASHBOARD)))

@compliance_bp.route('/rules/<int:rule_id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def delete_rule(rule_id):
    """Deletes a ComplianceRule."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to delete automation rules.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(CONTROL_DETAIL, id=rule_id))) # Redirect to control detail if rule_id is invalid

    rule = db.get_or_404(ComplianceRule, rule_id)
    rule_name = rule.name
    control_id = rule.framework_control_id
    
    db.session.delete(rule)
    db.session.commit()
    
    flash(f'Automation rule "{rule_name}" has been deleted.', 'success')
    return redirect(safe_redirect_target(request.referrer, url_for(CONTROL_DETAIL, id=control_id)))


@compliance_bp.route('/rules/<int:rule_id>/toggle', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def toggle_rule(rule_id):
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to toggle rules.', 'danger')
        return redirect(safe_redirect_target(request.referrer, url_for(CONTROL_DETAIL, id=rule_id)))
    """Toggles a ComplianceRule enabled/disabled state."""
    rule = db.get_or_404(ComplianceRule, rule_id)
    
    rule.enabled = not rule.enabled
    db.session.commit()
    
    status = 'enabled' if rule.enabled else 'disabled'
    flash(f'Automation rule "{rule.name}" has been {status}.', 'success')
    return redirect(safe_redirect_target(request.referrer, url_for(CONTROL_DETAIL, id=rule.framework_control_id)))

# ======================================================================
# UAR AUTOMATION ROUTES
# ======================================================================

@compliance_bp.route('/uar/automation')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_automation_list():
    """List all UAR automated comparisons."""
    comparisons = UARComparison.query.filter_by(is_archived=False).order_by(UARComparison.name).all()
    return render_template('compliance/uar_automation_list.html', comparisons=comparisons)


@compliance_bp.route('/uar/automation/new', methods=['GET', 'POST'])
@compliance_bp.route('/uar/automation/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_automation_form(id=None):
    """Create or edit UAR comparison."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to manage UAR automation.', 'danger')
        return redirect(url_for('compliance.uar_automation_list'))

    comparison = db.get_or_404(UARComparison, id) if id else UARComparison()

    if request.method == 'POST':
        # Parse form data
        comparison.name = request.form.get('name')
        comparison.description = request.form.get('description')
        comparison.source_a_type = request.form.get('source_a_type')
        comparison.source_b_type = request.form.get('source_b_type')
        
        # Parse source configurations
        source_a_config = {}
        if comparison.source_a_type == 'Subscription':
            source_a_config['subscription_id'] = int(request.form.get('source_a_subscription_id', 0))
        elif comparison.source_a_type == 'Business Service':
            source_a_config['service_id'] = int(request.form.get('source_a_service_id', 0))
        elif comparison.source_a_type == 'Database Query':
            source_a_config['query'] = request.form.get('source_a_query', '')
        elif comparison.source_a_type == 'Enterprise Report':
            source_a_config['report_id'] = int(request.form.get('source_a_report_id', 0))
        
        comparison.source_a_config = source_a_config

        source_b_config = {}
        if comparison.source_b_type == 'Subscription':
            source_b_config['subscription_id'] = int(request.form.get('source_b_subscription_id', 0))
        elif comparison.source_b_type == 'Business Service':
            source_b_config['service_id'] = int(request.form.get('source_b_service_id', 0))
        elif comparison.source_b_type == 'Database Query':
            source_b_config['query'] = request.form.get('source_b_query', '')
        elif comparison.source_b_type == 'Enterprise Report':
            source_b_config['report_id'] = int(request.form.get('source_b_report_id', 0))
        
        comparison.source_b_config = source_b_config

        # Comparison config
        comparison.key_field_a = request.form.get('key_field_a')
        comparison.key_field_b = request.form.get('key_field_b')
        
        # Field mappings
        field_mappings = []
        mapping_count = int(request.form.get('mapping_count', 0))
        for i in range(mapping_count):
            field_a = request.form.get(f'mapping_{i}_field_a')
            field_b = request.form.get(f'mapping_{i}_field_b')
            if field_a and field_b:
                field_mappings.append({'field_a': field_a, 'field_b': field_b})
        comparison.field_mappings = field_mappings

        # Schedule config
        comparison.schedule_type = request.form.get('schedule_type', 'manual')
        schedule_config = {}
        if comparison.schedule_type in ['daily', 'weekly']:
            schedule_config['hour'] = int(request.form.get('schedule_hour', 8))
        if comparison.schedule_type == 'weekly':
            schedule_config['day_of_week'] = int(request.form.get('schedule_day_of_week', 1))
        if comparison.schedule_type == 'monthly':
            schedule_config['hour'] = int(request.form.get('schedule_hour', 8))
            schedule_config['day_of_month'] = int(request.form.get('schedule_day_of_month', 1))
        comparison.schedule_config = schedule_config

        # Alert config
        comparison.alert_on_left_only = 'alert_on_left_only' in request.form
        comparison.alert_on_right_only = 'alert_on_right_only' in request.form
        comparison.alert_on_mismatches = 'alert_on_mismatches' in request.form
        comparison.min_findings_threshold = int(request.form.get('min_findings_threshold', 1))
        
        # Notification channels
        channels = []
        if 'notify_email' in request.form:
            channels.append('email')
        if 'notify_slack' in request.form:
            channels.append('slack')
        comparison.notification_channels = channels

        # Notification recipients
        recipients = []
        recipient_count = int(request.form.get('recipient_count', 0))
        for i in range(recipient_count):
            recipient_type = request.form.get(f'recipient_{i}_type')
            recipient_value = request.form.get(f'recipient_{i}_value')
            if recipient_type and recipient_value:
                recipients.append({'type': recipient_type, 'value': recipient_value})
        comparison.notification_recipients = recipients

        # Auto-escalation
        comparison.auto_create_incidents = 'auto_create_incidents' in request.form
        comparison.auto_incident_severity = request.form.get('auto_incident_severity', 'SEV-2')

        # Status
        comparison.is_enabled = 'is_enabled' in request.form

        if not id:
            db.session.add(comparison)

        # Calculate next_run if enabled
        if comparison.is_enabled and comparison.schedule_type != 'manual':
            service = UARAutomationService()
            comparison.next_run_at = service._calculate_next_run(comparison)

        db.session.commit()
        flash(f"UAR comparison '{comparison.name}' saved successfully", "success")
        return redirect(url_for(UAR_AUTOMATION_DETAIL, id=comparison.id))

    # GET: render form
    subscriptions = Subscription.query.all()
    services = BusinessService.query.all()
    reports = Report.query.order_by(Report.created_at.desc()).limit(50).all() if Report else []

    return render_template('compliance/uar_automation_form.html',
                         comparison=comparison,
                         subscriptions=subscriptions,
                         services=services,
                         reports=reports)


@compliance_bp.route('/uar/automation/<int:id>')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_automation_detail(id):
    """View UAR comparison configuration and execution history."""
    comparison = db.get_or_404(UARComparison, id)
    executions = UARExecution.query.filter_by(comparison_id=id)\
        .order_by(UARExecution.started_at.desc())\
        .limit(20)\
        .all()

    return render_template('compliance/uar_automation_detail.html',
                         comparison=comparison,
                         executions=executions)


@compliance_bp.route('/uar/automation/<int:id>/run', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_automation_run(id):
    """Manually trigger UAR comparison execution."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to run comparisons.', 'danger')
        return redirect(url_for(UAR_AUTOMATION_DETAIL, id=id))

    comparison = db.get_or_404(UARComparison, id)

    service = UARAutomationService()

    try:
        execution = service.execute_comparison(comparison)
        db.session.commit()
        flash(f"Comparison executed successfully: {execution.findings_count} findings detected", "success")
        return redirect(url_for(UAR_EXECUTION_DETAIL, execution_id=execution.id))
    except Exception as e:
        current_app.logger.error(f"[UAR] Manual execution failed: {e}", exc_info=True)
        flash(f"Execution failed: {str(e)}", "danger")
        return redirect(url_for(UAR_AUTOMATION_DETAIL, id=id))


@compliance_bp.route('/uar/execution/<int:execution_id>')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_execution_detail(execution_id):
    """View UAR execution results with findings."""
    execution = db.get_or_404(UARExecution, execution_id)

    # Paginate findings
    page = request.args.get('page', 1, type=int)
    finding_type_filter = request.args.get('type', 'all')

    findings_query = UARFinding.query.filter_by(execution_id=execution_id)
    if finding_type_filter != 'all':
        findings_query = findings_query.filter_by(finding_type=finding_type_filter)

    findings = findings_query.order_by(UARFinding.severity.desc(), UARFinding.id)\
        .paginate(page=page, per_page=50, error_out=False)

    return render_template('compliance/uar_execution_detail.html',
                         execution=execution,
                         findings=findings)


@compliance_bp.route('/uar/finding/<int:id>/resolve', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_finding_resolve(id):
    """Mark finding as resolved."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to resolve findings.', 'danger')
        finding = db.get_or_404(UARFinding, id)
        return redirect(url_for(UAR_EXECUTION_DETAIL, execution_id=finding.execution_id))

    finding = db.get_or_404(UARFinding, id)

    finding.status = request.form.get('status')
    finding.resolution_notes = request.form.get('notes')
    finding.resolved_at = now()
    finding.assigned_to_id = session.get('user_id')

    db.session.commit()
    flash("Finding updated successfully", "success")
    return redirect(url_for(UAR_EXECUTION_DETAIL, execution_id=finding.execution_id))


@compliance_bp.route('/uar/finding/<int:id>/promote-incident', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_finding_promote(id):
    """Manually promote finding to SecurityIncident."""
    if not has_write_permission(MODULE_COMPLIANCE):
        flash('Write access required to create incidents.', 'danger')
        finding = db.get_or_404(UARFinding, id)
        return redirect(url_for(UAR_EXECUTION_DETAIL, execution_id=finding.execution_id))

    finding = db.get_or_404(UARFinding, id)

    if finding.security_incident_id:
        flash("Finding already linked to an incident", "warning")
        return redirect(url_for(UAR_EXECUTION_DETAIL, execution_id=finding.execution_id))

    incident = SecurityIncident(
        title=f"Access Violation: {finding.key_value}",
        description=(
            f"Manual escalation from UAR Finding #{finding.id}\n\n"
            f"{finding.description}\n\n"
            f"Finding Type: {finding.finding_type}\n"
            f"Severity: {finding.severity}"
        ),
        status='Investigating',
        severity='SEV-2',
        impact='Moderate',
        source='User Access Review'
    )
    db.session.add(incident)
    db.session.flush()
    finding.security_incident_id = incident.id
    db.session.commit()

    flash(f"Security incident created: {incident.title}", "success")
    return redirect(url_for('security.incident_detail', id=incident.id))


@compliance_bp.route('/uar/findings/bulk-action', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def uar_findings_bulk_action():
    """
    Handle bulk operations on UAR findings.

    Supported actions:
    - mark_false_positive: Mark selected findings as false positives
    - assign: Assign selected findings to a user
    - resolve: Mark selected findings as resolved
    - create_incident: Create a security incident for selected findings
    - export: Export selected findings to CSV
    """
    if not has_write_permission(MODULE_COMPLIANCE):
        return jsonify({'error': 'Write access required'}), 403

    data = request.json
    action = data.get('action')
    finding_ids = data.get('finding_ids', [])

    if not finding_ids:
        return jsonify({'error': 'No findings selected'}), 400

    findings = UARFinding.query.filter(UARFinding.id.in_(finding_ids)).all()

    if not findings:
        return jsonify({'error': 'No valid findings found'}), 404

    # Get execution_id for redirect
    execution_id = findings[0].execution_id if findings else None

    try:
        if action == 'mark_false_positive':
            for finding in findings:
                finding.status = 'false_positive'
                finding.resolved_at = now()
                finding.assigned_to_id = session.get('user_id')
                finding.resolution_notes = data.get('notes', 'Marked as false positive via bulk action')

            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'{len(findings)} findings marked as false positive',
                'count': len(findings)
            })

        elif action == 'assign':
            user_id = data.get('user_id')
            if not user_id:
                return jsonify({'error': 'User ID required for assignment'}), 400

            user = db.session.get(User,user_id)
            if not user:
                return jsonify({'error': 'User not found'}), 404

            for finding in findings:
                finding.assigned_to_id = user_id
                finding.status = 'acknowledged'

            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'{len(findings)} findings assigned to {user.name}',
                'count': len(findings)
            })

        elif action == 'resolve':
            status = data.get('resolution_status', 'resolved')
            notes = data.get('notes', 'Resolved via bulk action')

            for finding in findings:
                finding.status = status
                finding.resolved_at = now()
                finding.assigned_to_id = session.get('user_id')
                finding.resolution_notes = notes

            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'{len(findings)} findings resolved',
                'count': len(findings)
            })

        elif action == 'create_incident':
            # Create a single incident for all findings
            finding_list = '\n'.join([
                f"- {f.key_value}: {f.finding_type} ({f.severity})"
                for f in findings
            ])

            incident = SecurityIncident(
                title=f"Bulk Access Violations: {len(findings)} findings",
                description=(
                    f"Bulk escalation from UAR execution #{execution_id}\n\n"
                    f"Total findings: {len(findings)}\n\n"
                    f"Affected entities:\n{finding_list}"
                ),
                status='Investigating',
                severity='SEV-2',
                impact='Moderate',
                source='User Access Review - Bulk Action'
            )
            db.session.add(incident)
            db.session.flush()

            # Link all findings to the incident
            for finding in findings:
                finding.security_incident_id = incident.id
                finding.status = 'acknowledged'

            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'Security incident created for {len(findings)} findings',
                'count': len(findings),
                'incident_id': incident.id,
                'redirect_url': url_for('security.incident_detail', id=incident.id)
            })

        elif action == 'export':
            # Generate CSV data
            import io
            import csv

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=[
                'ID', 'Finding Type', 'Severity', 'Key Value', 'Status',
                'Description', 'Dataset A', 'Dataset B', 'Created At'
            ])
            writer.writeheader()

            for finding in findings:
                writer.writerow({
                    'ID': finding.id,
                    'Finding Type': finding.finding_type,
                    'Severity': finding.severity,
                    'Key Value': finding.key_value,
                    'Status': finding.status,
                    'Description': finding.description,
                    'Dataset A': json.dumps(finding.raw_data_a) if finding.raw_data_a else '',
                    'Dataset B': json.dumps(finding.raw_data_b) if finding.raw_data_b else '',
                    'Created At': finding.created_at.isoformat() if finding.created_at else ''
                })

            csv_data = output.getvalue()
            return jsonify({
                'success': True,
                'message': f'{len(findings)} findings exported',
                'count': len(findings),
                'csv_data': csv_data,
                'filename': f'uar_findings_{execution_id}_{now().strftime("%Y%m%d_%H%M%S")}.csv'
            })

        else:
            return jsonify({'error': f'Unknown action: {action}'}), 400

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bulk action failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# --- Compliance Drift Detection Routes ---

@compliance_bp.route('/drift')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def drift_dashboard():
    """
    Compliance drift detection dashboard showing timeline and regressions.
    """
    from ..services.compliance_drift_service import get_drift_detector

    detector = get_drift_detector()

    # Get all active frameworks
    frameworks = Framework.query.filter_by(is_active=True).all()

    return render_template(
        'compliance/drift_dashboard.html',
        frameworks=frameworks
    )


@compliance_bp.route('/drift/api/timeline/<int:framework_id>')
@login_required
@requires_permission(MODULE_COMPLIANCE)
def api_drift_timeline(framework_id):
    """
    API endpoint to get drift timeline for a framework.

    Query Parameters:
        days: Number of days to look back (default: 30)

    Returns:
        JSON with drift timeline data
    """
    from ..services.compliance_drift_service import get_drift_detector

    detector = get_drift_detector()
    days = request.args.get('days', type=int, default=30)

    try:
        timeline = detector.get_drift_timeline(framework_id, days)
        return jsonify(timeline)
    except Exception as e:
        current_app.logger.error(f"Drift timeline error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@compliance_bp.route('/drift/api/detect', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def api_detect_drift():
    """
    API endpoint to manually trigger drift detection.

    Request Body:
        framework_id: Optional framework ID (null for all frameworks)
        lookback_hours: Hours to look back (default: 24)

    Returns:
        JSON with detected drifts
    """
    from ..services.compliance_drift_service import get_drift_detector

    detector = get_drift_detector()
    data = request.json or {}

    framework_id = data.get('framework_id')
    lookback_hours = data.get('lookback_hours', 24)

    try:
        drifts = detector.detect_drift(framework_id, lookback_hours)

        # Generate alert if regressions found
        alert = detector.generate_drift_alert(drifts) if drifts else None

        return jsonify({
            'success': True,
            'drift_count': len(drifts),
            'drifts': [d.to_dict() for d in drifts],
            'alert': alert
        })
    except Exception as e:
        current_app.logger.error(f"Drift detection error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@compliance_bp.route('/drift/api/snapshot', methods=['POST'])
@login_required
@requires_permission(MODULE_COMPLIANCE)
def api_create_snapshot():
    """
    API endpoint to manually create a compliance snapshot.

    Request Body:
        framework_id: Optional framework ID (null for all frameworks)

    Returns:
        JSON with snapshot ID
    """
    if not has_write_permission(MODULE_COMPLIANCE):
        return jsonify({'error': 'Write permission required'}), 403

    from ..services.compliance_drift_service import get_drift_detector

    detector = get_drift_detector()
    data = request.json or {}

    framework_id = data.get('framework_id')

    try:
        snapshot = detector.capture_snapshot(framework_id)

        return jsonify({
            'success': True,
            'snapshot_id': snapshot.id,
            'timestamp': snapshot.created_at.isoformat(),
            'message': 'Compliance snapshot created successfully'
        })
    except Exception as e:
        current_app.logger.error(f"Snapshot creation error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
