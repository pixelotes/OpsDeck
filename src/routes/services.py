from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from ..services.permissions_service import requires_permission, has_write_permission
from ..models.services import BusinessService, ServiceComponent, ServiceDependency, DependencyType
from ..models.auth import User
from ..models.core import CostCenter, Documentation, Link, Attachment
from ..models.assets import Asset, Software, License
from ..models.procurement import Supplier, Subscription
from ..models.configuration import Configuration
from ..models.policy import Policy
from ..models.certificates import Certificate
from ..models.credentials import Credential
from ..models.activities import SecurityActivity
from ..extensions import db
from ..utils.dependency_graph import get_full_dependency_tree
import os
import uuid

from .main import login_required

services_bp = Blueprint('services', __name__, 
                        template_folder='../templates/services', # Relative to src/routes
                        url_prefix='/services')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
DETAIL = 'services.detail'

@services_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_services():
    services = BusinessService.query.order_by(BusinessService.name).all()
    return render_template('services/list.html', services=services)

@services_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def create_service():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for('services.list_services'))
        name = request.form.get('name')
        description = request.form.get('description')
        owner_id = request.form.get('owner_id')
        criticality = request.form.get('criticality')
        status = request.form.get('status')
        sla_response = request.form.get('sla_response_hours')
        sla_resolution = request.form.get('sla_resolution_hours')
        cost_center_id = request.form.get('cost_center_id')
        
        service = BusinessService(
            name=name,
            description=description,
            owner_id=owner_id if owner_id else None,
            criticality=criticality,
            status=status,
            sla_response_hours=int(sla_response) if sla_response else None,
            sla_resolution_hours=int(sla_resolution) if sla_resolution else None,
            cost_center_id=int(cost_center_id) if cost_center_id else None,
            category=request.form.get('category')
        )
        
        try:
            db.session.add(service)
            db.session.commit()
            flash('Service created successfully!', 'success')
            return redirect(url_for(DETAIL, id=service.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating service: {str(e)}', 'danger')
    
    users = User.query.all()
    cost_centers = CostCenter.query.order_by(CostCenter.code).all()
    return render_template('services/form.html', users=users, service=None, cost_centers=cost_centers)

@services_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def detail(id):
    service = db.get_or_404(BusinessService, id)
    all_services = BusinessService.query.filter(BusinessService.id != id).all()
    
    # Context data for Service Context tab
    all_documents = Documentation.query.order_by(Documentation.name).all()
    all_policies = Policy.query.order_by(Policy.title).all()
    all_activities = SecurityActivity.query.order_by(SecurityActivity.name).all()
    all_certificates = Certificate.query.order_by(Certificate.name).all()
    
    # Query polymorphic links and attachments for this service
    service_links = Link.query.filter_by(owner_type='BusinessService', owner_id=id).all()
    service_attachments = Attachment.query.filter_by(linkable_type='BusinessService', linkable_id=id).all()
    
    # Generate full dependency maps
    upstream_map = get_full_dependency_tree(service, 'upstream')
    downstream_map = get_full_dependency_tree(service, 'downstream')

    # Unify and remove duplicates
    unique_edges = {}
    for edge in upstream_map + downstream_map:
        key = (edge['from'], edge['to'])
        if key not in unique_edges:
            unique_edges[key] = edge
            
    dependency_map = list(unique_edges.values())

    # Create risk node styles for Mermaid graph coloring
    related_service_ids = set()
    related_service_ids.add(service.id)
    for edge in dependency_map:
        related_service_ids.add(edge['from'])
        related_service_ids.add(edge['to'])
    
    node_styles = {}
    related_services = BusinessService.query.filter(BusinessService.id.in_(related_service_ids)).all()
    for srv in related_services:
        if srv.aggregated_risk_score > 0:
            node_styles[srv.id] = srv.risk_status_color

    # User list for Access Management
    all_users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    
    # Get unified access list (direct + inherited)
    effective_users = service.get_effective_users()

    return render_template('services/detail.html',
        service=service,
        dependency_map=dependency_map,
        node_styles=node_styles,
        upstream_map=upstream_map,
        downstream_map=downstream_map,
        all_services=all_services,
        all_documents=all_documents,
        all_policies=all_policies,
        all_activities=all_activities,
        service_links=service_links,
        service_attachments=service_attachments,
        service_policies=service.policies,
        service_activities=service.activities,
        all_users=all_users,
        effective_users=effective_users,
        all_certificates=all_certificates,
        all_credentials=Credential.query.order_by(Credential.name).all(),
        dependency_types=DependencyType
    )

from src.utils.logger import log_audit

@services_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_service(id):
    service = db.get_or_404(BusinessService, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for(DETAIL, id=id))
        service.name = request.form.get('name')
        service.description = request.form.get('description')
        service.owner_id = request.form.get('owner_id') if request.form.get('owner_id') else None
        service.criticality = request.form.get('criticality')
        service.status = request.form.get('status')
        
        sla_resp = request.form.get('sla_response_hours')
        service.sla_response_hours = int(sla_resp) if sla_resp else None
        
        sla_res = request.form.get('sla_resolution_hours')
        service.sla_resolution_hours = int(sla_res) if sla_res else None
        
        cost_center_id = request.form.get('cost_center_id')
        service.cost_center_id = int(cost_center_id) if cost_center_id else None

        service.category = request.form.get('category')
        
        try:
            db.session.commit()
            
            log_audit(
                event_type='service.updated',
                action='update',
                target_object=f"Service:{service.id}",
                target_info=service.name
            )
            
            flash('Service updated successfully!', 'success')
            return redirect(url_for(DETAIL, id=service.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating service: {str(e)}', 'danger')
            
    users = User.query.all()
    cost_centers = CostCenter.query.order_by(CostCenter.code).all()
    return render_template('services/form.html', users=users, service=service, cost_centers=cost_centers)

@services_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_service(id):
    service = db.get_or_404(BusinessService, id)
    try:
        service_info = service.name
        db.session.delete(service)
        db.session.commit()
        
        log_audit(
            event_type='service.deleted',
            action='delete',
            target_object=f"Service:{id}",
            target_info=service_info
        )
        
        flash('Service deleted successfully.', 'success')
        return redirect(url_for('services.list_services'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting service: {str(e)}', 'danger')
        return redirect(url_for(DETAIL, id=id))

@services_bp.route('/<int:id>/dependency/add', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_dependency(id):
    service = db.get_or_404(BusinessService, id)
    target_service_id = request.form.get('target_service_id')
    dependency_type = request.form.get('dependency_type') # 'upstream' (depends on) or 'downstream' (supports)
    label_value = request.form.get('dependency_label') or None

    if not target_service_id:
        flash('Please select a service.', 'warning')
        return redirect(url_for(DETAIL, id=id))

    target_service = db.session.get(BusinessService, target_service_id)
    if not target_service:
        flash('Target service not found.', 'danger')
        return redirect(url_for(DETAIL, id=id))

    if target_service.id == service.id:
        flash('Cannot depend on self.', 'warning')
        return redirect(url_for(DETAIL, id=id))

    # Resolve label enum
    label_enum = None
    if label_value:
        try:
            label_enum = DependencyType(label_value)
        except ValueError:
            flash('Invalid dependency label.', 'danger')
            return redirect(url_for(DETAIL, id=id))

    try:
        if dependency_type == 'upstream':
            parent_id, child_id = target_service.id, service.id
        else:
            parent_id, child_id = service.id, target_service.id

        existing = ServiceDependency.query.filter_by(parent_id=parent_id, child_id=child_id).first()
        if not existing:
            dep = ServiceDependency(parent_id=parent_id, child_id=child_id, label=label_enum)
            db.session.add(dep)
            db.session.commit()
            flash('Dependency added.', 'success')
        else:
            flash('Dependency already exists.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding dependency: {str(e)}', 'danger')

    return redirect(url_for(DETAIL, id=id))

@services_bp.route('/<int:id>/dependency/remove/<int:target_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def remove_dependency(id, target_id):
    dep_type = request.form.get('type') # 'upstream' or 'downstream'

    try:
        if dep_type == 'upstream':
            dep = ServiceDependency.query.filter_by(parent_id=target_id, child_id=id).first()
        else:
            dep = ServiceDependency.query.filter_by(parent_id=id, child_id=target_id).first()

        if dep:
            db.session.delete(dep)
            db.session.commit()
            flash('Dependency removed.', 'success')
        else:
            flash('Dependency not found.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing dependency: {str(e)}', 'danger')

    return redirect(url_for(DETAIL, id=id))

@services_bp.route('/<int:id>/component/add', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_component(id):
    service = db.get_or_404(BusinessService, id)
    comp_type = request.form.get('component_type')
    comp_id = request.form.get('component_id')
    notes = request.form.get('notes')
    
    if not comp_type or not comp_id:
        flash('Invalid component selection.', 'warning')
        return redirect(url_for(DETAIL, id=id) + '#infrastructure')
        
    # Create component link
    comp = ServiceComponent(
        service_id=service.id,
        component_type=comp_type,
        component_id=comp_id,
        notes=notes
    )
    
    try:
        db.session.add(comp)
        db.session.commit()
        flash('Component linked successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error linking component: {str(e)}', 'danger')

    return redirect(url_for(DETAIL, id=id) + '#infrastructure')

@services_bp.route('/component/<int:comp_id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_component(comp_id):
    comp = db.get_or_404(ServiceComponent, comp_id)
    service_id = comp.service_id
    try:
        db.session.delete(comp)
        db.session.commit()
        flash('Component removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing component: {str(e)}', 'danger')
    return redirect(url_for(DETAIL, id=service_id) + '#infrastructure')


@services_bp.route('/api/search-components/<component_type>', methods=['GET'])
@login_required
def search_components(component_type):
    """Search infrastructure components by type for TomSelect remote mode."""
    q = request.args.get('q', '').strip().lower()
    
    # Map component types to their models and display field
    model_map = {
        'Asset': (Asset, 'name'),
        'Software': (Software, 'name'),
        'License': (License, 'name'),
        'Supplier': (Supplier, 'name'),
        'Subscription': (Subscription, 'name'),
        'Configuration': (Configuration, 'name'),
    }
    
    if component_type not in model_map:
        return jsonify([])
    
    model, name_field = model_map[component_type]
    
    # Query with optional search filter
    query = model.query
    if q:
        query = query.filter(getattr(model, name_field).ilike(f'%{q}%'))
    
    # Limit results for performance
    items = query.limit(50).all()
    
    # Format for TomSelect: [{id: x, text: y}, ...]
    results = []
    for item in items:
        display_name = getattr(item, name_field, None) or f'{component_type} #{item.id}'
        results.append({
            'id': item.id,
            'text': display_name
        })
    
    return jsonify(results)


# --- Service Context Routes ---

@services_bp.route('/<int:id>/link-document', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def link_document(id):
    service = db.get_or_404(BusinessService, id)
    doc_id = request.form.get('document_id')
    if doc_id:
        doc = db.session.get(Documentation,doc_id)
        if doc and doc not in service.documents:
            service.documents.append(doc)
            db.session.commit()
            flash('Documentation linked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/unlink-document/<int:doc_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unlink_document(id, doc_id):
    service = db.get_or_404(BusinessService, id)
    doc = db.session.get(Documentation,doc_id)
    if doc and doc in service.documents:
        service.documents.remove(doc)
        db.session.commit()
        flash('Documentation unlinked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/link-policy', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def link_policy(id):
    service = db.get_or_404(BusinessService, id)
    policy_id = request.form.get('policy_id')
    if policy_id:
        policy = db.session.get(Policy,policy_id)
        if policy and policy not in service.policies:
            service.policies.append(policy)
            db.session.commit()
            flash('Policy linked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/unlink-policy/<int:policy_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unlink_policy(id, policy_id):
    service = db.get_or_404(BusinessService, id)
    policy = db.session.get(Policy,policy_id)
    if policy and policy in service.policies:
        service.policies.remove(policy)
        db.session.commit()
        flash('Policy unlinked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/link-activity', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def link_activity(id):
    service = db.get_or_404(BusinessService, id)
    activity_id = request.form.get('activity_id')
    if activity_id:
        activity = db.session.get(SecurityActivity,activity_id)
        if activity and activity not in service.activities:
            service.activities.append(activity)
            db.session.commit()
            flash('Security activity linked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/unlink-activity/<int:activity_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unlink_activity(id, activity_id):
    service = db.get_or_404(BusinessService, id)
    activity = db.session.get(SecurityActivity,activity_id)
    if activity and activity in service.activities:
        service.activities.remove(activity)
        db.session.commit()
        flash('Security activity unlinked.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/add-link', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_link(id):
    db.get_or_404(BusinessService, id)
    name = request.form.get('name')
    url = request.form.get('url')
    
    if name and url:
        link = Link(
            name=name,
            url=url,
            owner_type='BusinessService',
            owner_id=id
        )
        db.session.add(link)
        db.session.commit()
        flash('External link added.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/remove-link/<int:link_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def remove_link(id, link_id):
    link = db.get_or_404(Link, link_id)
    if link.owner_type == 'BusinessService' and link.owner_id == id:
        db.session.delete(link)
        db.session.commit()
        flash('External link removed.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/upload-attachment', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def upload_attachment(id):
    db.get_or_404(BusinessService, id)
    
    if 'file' not in request.files:
        flash('No file selected.', 'warning')
        return redirect(url_for(DETAIL, id=id) + '#context')

    file = request.files['file']
    if file.filename == '':
        flash('No file selected.', 'warning')
        return redirect(url_for(DETAIL, id=id) + '#context')
    
    # Secure the filename and generate a unique stored name
    original_filename = file.filename
    ext = os.path.splitext(original_filename)[1]
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    
    # Save to uploads directory
    upload_dir = os.path.join(current_app.root_path, '..', 'data', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_filename)
    file.save(file_path)
    
    # Create attachment record
    attachment = Attachment(
        filename=original_filename,
        secure_filename=stored_filename,
        linkable_type='BusinessService',
        linkable_id=id
    )
    db.session.add(attachment)
    db.session.commit()
    flash('File uploaded successfully.', 'success')

    return redirect(url_for(DETAIL, id=id) + '#context')


@services_bp.route('/<int:id>/remove-attachment/<int:att_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def remove_attachment(id, att_id):
    attachment = db.get_or_404(Attachment, att_id)
    if attachment.linkable_type == 'BusinessService' and attachment.linkable_id == id:
        # Optionally delete the file from disk
        try:
            file_path = os.path.join(current_app.root_path, '..', 'data', 'uploads', attachment.secure_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass  # File deletion is best-effort
        
        db.session.delete(attachment)
        db.session.commit()
        flash('Attachment removed.', 'success')
    return redirect(url_for(DETAIL, id=id) + '#context')

# ==========================================
# USER ACCESS MANAGEMENT
# ==========================================

@services_bp.route('/<int:id>/users/add', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_user_access(id):
    service = db.get_or_404(BusinessService, id)
    user_ids = request.form.getlist('user_ids')

    added = []
    for uid in user_ids:
        user = db.session.get(User, int(uid))
        if user and user not in service.users:
            service.users.append(user)
            added.append(user.name)

    if added:
        db.session.commit()
        flash(f'Added {len(added)} user(s) to {service.name}.', 'success')

    return redirect(url_for(DETAIL, id=id) + '#users')

@services_bp.route('/<int:id>/users/add-all', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def add_all_users(id):
    service = db.get_or_404(BusinessService, id)
    all_users = User.query.filter_by(is_archived=False).all()

    added = []
    for user in all_users:
        if user not in service.users:
            service.users.append(user)
            added.append(user.name)

    if added:
        db.session.commit()
        flash(f'Added {len(added)} users to {service.name}.', 'success')
    else:
        flash('All users already have access.', 'info')

    return redirect(url_for(DETAIL, id=id) + '#users')

@services_bp.route('/<int:id>/users/remove/<int:user_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def remove_user_access(id, user_id):
    service = db.get_or_404(BusinessService, id)
    user = db.get_or_404(User, user_id)
    
    if user in service.users:
        service.users.remove(user)
        db.session.commit()
        flash(f'User {user.name} removed from {service.name}.', 'warning')

    return redirect(url_for(DETAIL, id=id) + '#users')

@services_bp.route('/<int:id>/check_access/<int:user_id>', methods=['GET'])
@login_required
def check_user_access(id, user_id):
    """
    API endpoint to check if a user already has access to a service
    through inherited sources (subscriptions/licenses).
    
    Returns JSON: {'exists': bool, 'sources': [str]}
    """
    service = db.get_or_404(BusinessService, id)
    user = db.get_or_404(User, user_id)
    
    inherited_sources = []
    
    # Check components for inherited access
    for component in service.components:
        linked_obj = component.linked_object
        
        if component.component_type == 'Subscription' and linked_obj:
            if user in linked_obj.users:
                inherited_sources.append(f"Subscription: {linked_obj.name}")
        
        elif component.component_type == 'License' and linked_obj:
            if linked_obj.user_id == user.id:
                inherited_sources.append(f"License: {linked_obj.name}")
    
    return jsonify({
        'exists': len(inherited_sources) > 0,
        'sources': inherited_sources
    })

@services_bp.route('/<int:id>/link_certificate', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def link_certificate(id):
    service = db.get_or_404(BusinessService, id)
    cert_id = request.form.get('certificate_id')
    
    if cert_id:
        cert = db.session.get(Certificate,cert_id)
        if cert and cert not in service.certificates:
            service.certificates.append(cert)
            # Log audit
            log_audit(
                event_type='service.update',
                action='update',
                target_object=f"BusinessService:{service.id}",
                outcome='success',
                linked_certificate=cert.name,
                details=f"Linked certificate {cert.name} to service {service.name}"
            )
            db.session.commit()
            flash(f'Certificate "{cert.name}" linked successfully.', 'success')
        else:
             if cert in service.certificates:
                 flash('Certificate is already linked.', 'warning')
             else:
                 flash('Certificate not found.', 'danger')
    
    return redirect(url_for(DETAIL, id=id, _anchor='context'))

@services_bp.route('/<int:id>/unlink_certificate/<int:cert_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unlink_certificate(id, cert_id):
    service = db.get_or_404(BusinessService, id)
    cert = db.get_or_404(Certificate, cert_id)

    if cert in service.certificates:
        service.certificates.remove(cert)
        # Log audit
        log_audit(
            event_type='service.update',
            action='update',
            target_object=f"BusinessService:{service.id}",
            outcome='success',
            unlinked_certificate=cert.name,
            details=f"Unlinked certificate {cert.name} from service {service.name}"
        )
        db.session.commit()
        flash(f'Certificate "{cert.name}" unlinked successfully.', 'success')
    
    return redirect(url_for(DETAIL, id=id, _anchor='context'))


@services_bp.route('/<int:id>/link_credential', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def link_credential(id):
    service = db.get_or_404(BusinessService, id)
    cred_id = request.form.get('credential_id')
    
    if cred_id:
        cred = db.session.get(Credential,cred_id)
        if cred and cred not in service.credentials:
            service.credentials.append(cred)
            # Log audit
            log_audit(
                event_type='service.update',
                action='update',
                target_object=f"BusinessService:{service.id}",
                outcome='success',
                linked_credential=cred.name,
                details=f"Linked credential {cred.name} to service {service.name}"
            )
            db.session.commit()
            flash(f'Credential "{cred.name}" linked successfully.', 'success')
        else:
             if cred in service.credentials:
                 flash('Credential is already linked.', 'warning')
             else:
                 flash('Credential not found.', 'danger')
    
    return redirect(url_for(DETAIL, id=id, _anchor='context'))

@services_bp.route('/<int:id>/unlink_credential/<int:cred_id>', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unlink_credential(id, cred_id):
    service = db.get_or_404(BusinessService, id)
    cred = db.get_or_404(Credential, cred_id)

    if cred in service.credentials:
        service.credentials.remove(cred)
        # Log audit
        log_audit(
            event_type='service.update',
            action='update',
            target_object=f"BusinessService:{service.id}",
            outcome='success',
            unlinked_credential=cred.name,
            details=f"Unlinked credential {cred.name} from service {service.name}"
        )
        db.session.commit()
        flash(f'Credential "{cred.name}" unlinked successfully.', 'success')
    
    return redirect(url_for(DETAIL, id=id, _anchor='context'))
