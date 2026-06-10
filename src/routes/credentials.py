from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import db, User
from ..models.credentials import Credential, CredentialSecret
from ..models.services import BusinessService
from ..models.assets import Software, License, Asset
from ..services.permissions_service import requires_permission, has_write_permission
from .main import login_required

credentials_bp = Blueprint('credentials', __name__, url_prefix='/credentials')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
DETAIL_CREDENTIAL = 'credentials.detail_credential'
CREDENTIALS_FORM_HTML = 'credentials/form.html'

# Credential types constant
CREDENTIAL_TYPES = ['API Key', 'OAuth', 'Service Account', 'SSH Key', 'Password', 'Certificate']

@credentials_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_credentials():
    """
    List all credentials with filtering support and pagination.
    Filters: type, status (active/expiring_soon/expired), owner/name search
    """
    # Get pagination and filter parameters
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('type', '')
    filter_status = request.args.get('status', '')
    filter_owner = request.args.get('owner', '')
    
    # Base query
    query = Credential.query
    
    # Apply type filter
    if filter_type:
        query = query.filter_by(type=filter_type)
    
    # Apply owner/name search filter
    if filter_owner:
        query = query.join(User, (Credential.owner_id == User.id) & (Credential.owner_type == 'User'))
        query = query.filter(
            db.or_(
                User.name.ilike(f'%{filter_owner}%'),
                Credential.name.ilike(f'%{filter_owner}%')
            )
        )
    
    # For status filtering, we need to get all first then filter
    # This is because status is computed from the relationship
    if filter_status:
        # Get all matching credentials
        all_credentials = query.order_by(Credential.name.asc()).all()
        
        # Filter by status
        filtered_credentials = []
        for cred in all_credentials:
            secret = cred.active_secret
            if secret:
                if filter_status == secret.expiry_status:
                    filtered_credentials.append(cred)
            elif filter_status == 'active':
                # Credentials without secrets could be considered "active"
                filtered_credentials.append(cred)
        
        # Manual pagination for filtered results
        per_page = 15
        total = len(filtered_credentials)
        start = (page - 1) * per_page
        end = start + per_page
        credentials_page = filtered_credentials[start:end]
        
        # Create a simple pagination object
        class SimplePagination:
            def __init__(self, items, page, per_page, total):
                self.items = items
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total + per_page - 1) // per_page
                self.has_prev = page > 1
                self.has_next = page < self.pages
                self.prev_num = page - 1 if self.has_prev else None
                self.next_num = page + 1 if self.has_next else None
        
        credentials = SimplePagination(credentials_page, page, per_page, total)
    else:
        # Use SQLAlchemy pagination
        credentials = query.order_by(Credential.name.asc()).paginate(page=page, per_page=15, error_out=False)
    
    # Prepare current filters for template
    current_filters = {
        'type': filter_type,
        'status': filter_status,
        'owner': filter_owner
    }
    
    return render_template(
        'credentials/list.html',
        credentials=credentials,
        credential_types=CREDENTIAL_TYPES,
        current_filters=current_filters
    )

@credentials_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def detail_credential(id):
    """
    Show credential details including active secret and secret history.
    """
    credential = db.get_or_404(Credential, id)
    
    # Get all secrets ordered by created_at descending (newest first)
    secrets = credential.secrets.order_by(CredentialSecret.created_at.desc()).all()
    
    return render_template(
        'credentials/detail.html',
        credential=credential,
        secrets=secrets
    )

@credentials_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_credential():
    """
    Create a new credential with its first secret.
    """
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for('credentials.list_credentials'))
        # Extract form data
        name = request.form.get('name')
        cred_type = request.form.get('type')
        owner_id = request.form.get('owner_id')
        owner_type = request.form.get('owner_type', 'User')
        description = request.form.get('description', '')
        break_glass = request.form.get('break_glass') == 'on'
        secret_value = request.form.get('secret_value')
        expires_at_str = request.form.get('expires_at')
        
        # Validate required fields
        if not name or not cred_type or not owner_id or not secret_value:
            flash('Please fill in all required fields.', 'danger')
            usuarios = User.query.filter_by(is_archived=False).order_by(User.name).all()
            return render_template(
                CREDENTIALS_FORM_HTML,
                credential=None,
                credential_types=CREDENTIAL_TYPES,
                usuarios=usuarios
            )
        
        # Parse expiry date
        expires_at = None
        if expires_at_str:
            try:
                expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d')
            except ValueError:
                flash('Invalid expiry date format.', 'danger')
                usuarios = User.query.filter_by(is_archived=False).order_by(User.name).all()
                return render_template(
                    CREDENTIALS_FORM_HTML,
                    credential=None,
                    credential_types=CREDENTIAL_TYPES,
                    usuarios=usuarios
                )
        
        # Create the credential
        new_credential = Credential(
            name=name,
            type=cred_type,
            owner_id=int(owner_id),
            owner_type=owner_type,
            description=description,
            break_glass=break_glass
        )
        
        # Handle target assignment (polymorphic)
        target_type = request.form.get('target_type')
        target_id = request.form.get('target_id')
        
        if target_type and target_id:
            target_id = int(target_id)
            if target_type == 'service':
                new_credential.service_id = target_id
                new_credential.software_id = None
                new_credential.license_id = None
                new_credential.asset_id = None
            elif target_type == 'software':
                new_credential.software_id = target_id
                new_credential.service_id = None
                new_credential.license_id = None
                new_credential.asset_id = None
            elif target_type == 'license':
                new_credential.license_id = target_id
                new_credential.service_id = None
                new_credential.software_id = None
                new_credential.asset_id = None
            elif target_type == 'asset':
                new_credential.asset_id = target_id
                new_credential.service_id = None
                new_credential.software_id = None
                new_credential.license_id = None
        
        db.session.add(new_credential)
        db.session.flush()  # Get the credential ID
        
        # Create the first secret (masked)
        new_secret = CredentialSecret(
            credential_id=new_credential.id,
            expires_at=expires_at,
            is_active=True
        )
        new_secret.set_secret(secret_value)  # This masks the value
        
        db.session.add(new_secret)
        db.session.commit()
        
        flash(f'Credential "{name}" created successfully!', 'success')
        return redirect(url_for(DETAIL_CREDENTIAL, id=new_credential.id))
    
    # GET request - show form
    usuarios = User.query.filter_by(is_archived=False).order_by(User.name).all()
    services = BusinessService.query.filter(BusinessService.status != 'Retired').order_by(BusinessService.name).all()
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
    licenses = License.query.filter_by(is_archived=False).order_by(License.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    
    # Convert to dictionaries for JSON serialization
    services_dict = [{'id': s.id, 'name': s.name} for s in services]
    software_dict = [{'id': s.id, 'name': s.name} for s in software_items]
    licenses_dict = [{'id': l.id, 'name': l.name} for l in licenses]
    assets_dict = [{'id': a.id, 'name': a.name} for a in assets]
    
    return render_template(
        CREDENTIALS_FORM_HTML,
        credential=None,
        credential_types=CREDENTIAL_TYPES,
        usuarios=usuarios,
        services=services_dict,
        software_items=software_dict,
        licenses=licenses_dict,
        assets=assets_dict
    )

@credentials_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_credential(id):
    """
    Edit an existing credential's metadata (not the secret).
    Use rotate_secret to change the actual secret value.
    """
    credential = db.get_or_404(Credential, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for(DETAIL_CREDENTIAL, id=id))
        # Extract form data
        name = request.form.get('name')
        cred_type = request.form.get('type')
        owner_id = request.form.get('owner_id')
        owner_type = request.form.get('owner_type', 'User')
        description = request.form.get('description', '')
        break_glass = request.form.get('break_glass') == 'on'
        
        # Validate required fields
        if not name or not cred_type or not owner_id:
            flash('Please fill in all required fields.', 'danger')
            usuarios = User.query.filter_by(is_archived=False).order_by(User.name).all()
            return render_template(
                CREDENTIALS_FORM_HTML,
                credential=credential,
                credential_types=CREDENTIAL_TYPES,
                usuarios=usuarios
            )
        
        # Update credential
        credential.name = name
        credential.type = cred_type
        credential.owner_id = int(owner_id)
        credential.owner_type = owner_type
        credential.description = description
        credential.break_glass = break_glass
        
        # Handle target assignment (polymorphic)
        target_type = request.form.get('target_type')
        target_id = request.form.get('target_id')
        
        # Clear all targets first
        credential.service_id = None
        credential.software_id = None
        credential.license_id = None
        credential.asset_id = None
        
        # Set the selected target
        if target_type and target_id:
            target_id = int(target_id)
            if target_type == 'service':
                credential.service_id = target_id
            elif target_type == 'software':
                credential.software_id = target_id
            elif target_type == 'license':
                credential.license_id = target_id
            elif target_type == 'asset':
                credential.asset_id = target_id
        
        db.session.commit()
        
        flash(f'Credential "{name}" updated successfully!', 'success')
        return redirect(url_for(DETAIL_CREDENTIAL, id=credential.id))
    
    # GET request - show form
    usuarios = User.query.filter_by(is_archived=False).order_by(User.name).all()
    services = BusinessService.query.filter(BusinessService.status != 'Retired').order_by(BusinessService.name).all()
    software_items = Software.query.filter_by(is_archived=False).order_by(Software.name).all()
    licenses = License.query.filter_by(is_archived=False).order_by(License.name).all()
    assets = Asset.query.filter_by(is_archived=False).order_by(Asset.name).all()
    
    # Convert to dictionaries for JSON serialization
    services_dict = [{'id': s.id, 'name': s.name} for s in services]
    software_dict = [{'id': s.id, 'name': s.name} for s in software_items]
    licenses_dict = [{'id': l.id, 'name': l.name} for l in licenses]
    assets_dict = [{'id': a.id, 'name': a.name} for a in assets]
    
    return render_template(
        CREDENTIALS_FORM_HTML,
        credential=credential,
        credential_types=CREDENTIAL_TYPES,
        usuarios=usuarios,
        services=services_dict,
        software_items=software_dict,
        licenses=licenses_dict,
        assets=assets_dict
    )

@credentials_bp.route('/<int:id>/rotate', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def rotate_secret(id):
    """
    Rotate the secret for a credential.
    Deactivates all existing secrets and creates a new active one.
    """
    credential = db.get_or_404(Credential, id)
    
    # Extract form data
    new_secret_value = request.form.get('new_secret_value')
    expires_at_str = request.form.get('expires_at')
    
    if not new_secret_value:
        flash('Secret value is required for rotation.', 'danger')
        return redirect(url_for(DETAIL_CREDENTIAL, id=id))
    
    # Parse expiry date
    expires_at = None
    if expires_at_str:
        try:
            expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d')
        except ValueError:
            flash('Invalid expiry date format.', 'danger')
            return redirect(url_for(DETAIL_CREDENTIAL, id=id))
    
    # Transaction: Deactivate all existing secrets
    for secret in credential.secrets.all():
        secret.is_active = False
    
    # Create new active secret
    new_secret = CredentialSecret(
        credential_id=credential.id,
        expires_at=expires_at,
        is_active=True
    )
    new_secret.set_secret(new_secret_value)  # This masks the value
    
    db.session.add(new_secret)
    db.session.commit()
    
    flash(f'Secret rotated successfully for "{credential.name}".', 'success')
    return redirect(url_for(DETAIL_CREDENTIAL, id=id))

@credentials_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def delete_credential(id):
    """
    Delete a credential and all its associated secrets (cascade).
    """
    credential = db.get_or_404(Credential, id)
    credential_name = credential.name
    
    db.session.delete(credential)
    db.session.commit()
    
    flash(f'Credential "{credential_name}" has been deleted.', 'info')
    return redirect(url_for('credentials.list_credentials'))
