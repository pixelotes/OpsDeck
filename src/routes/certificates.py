from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import db, Certificate, CertificateVersion, User, BusinessService
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.logger import log_audit
from .main import login_required

certificates_bp = Blueprint('certificates', __name__, url_prefix='/certificates')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
CERTIFICATE_DETAIL = 'certificates.certificate_detail'
WRITE_REQUIRED = 'Write access required for this action.'

@certificates_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_certificates():
    certificates = Certificate.query.order_by(Certificate.name).all()
    # Eager load versions? Or just let lazy loading handle it for MVP list
    # actually for status color we need active version.
    return render_template('certificates/list.html', certificates=certificates)

@certificates_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def create_certificate():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for('certificates.list_certificates'))
        # 1. Create Certificate
        name = request.form.get('name')
        cert_type = request.form.get('type')
        description = request.form.get('description')
        owner_id = request.form.get('owner_id')
        service_ids = request.form.getlist('service_ids') # list of IDs

        cert = Certificate(
            name=name,
            type=cert_type,
            description=description,
            owner_id=owner_id if owner_id else None,
            owner_type='User' # Fixed for now
        )
        
        # 2. Associations with Services
        if service_ids:
            services = BusinessService.query.filter(BusinessService.id.in_(service_ids)).all()
            cert.services.extend(services)
        
        db.session.add(cert)
        db.session.flush() # Get ID

        # 3. Create Initial Version (if provided)
        # Assuming form has version fields too
        expires_at_str = request.form.get('expires_at')
        if expires_at_str:
            version = CertificateVersion(
                certificate_id=cert.id,
                version_notes="Initial Version",
                expires_at=datetime.strptime(expires_at_str, '%Y-%m-%d').date(),
                issuer=request.form.get('issuer'),
                common_name=request.form.get('common_name'),
                private_key_location=request.form.get('private_key_location'),
                is_active=True
            )
            db.session.add(version)

        db.session.commit()
        
        log_audit(
            event_type='certificate.created',
            action='create',
            target_object=f"Certificate:{cert.id}",
            target_info=cert.name
        )
        
        flash(f'Certificate "{cert.name}" created successfully.', 'success')
        return redirect(url_for(CERTIFICATE_DETAIL, id=cert.id))

    # GET
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    services = BusinessService.query.order_by(BusinessService.name).all()
    return render_template('certificates/form.html', users=users, services=services)

@certificates_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def certificate_detail(id):
    cert = db.get_or_404(Certificate, id)
    return render_template('certificates/detail.html', certificate=cert)

@certificates_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_certificate(id):
    cert = db.get_or_404(Certificate, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(CERTIFICATE_DETAIL, id=id))
        cert.name = request.form.get('name')
        cert.type = request.form.get('type')
        cert.description = request.form.get('description')
        owner_id = request.form.get('owner_id')
        cert.owner_id = owner_id if owner_id else None
        
        # Update Services
        service_ids = request.form.getlist('service_ids')
        # Clear existing? or sync?
        # simplest: clear and add
        cert.services = []
        if service_ids:
            services = BusinessService.query.filter(BusinessService.id.in_(service_ids)).all()
            cert.services.extend(services)

        db.session.commit()
        
        log_audit(event_type='certificate.updated', action='update', target_object=f"Certificate:{cert.id}")
        flash('Certificate updated.', 'success')
        return redirect(url_for(CERTIFICATE_DETAIL, id=cert.id))

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    services = BusinessService.query.order_by(BusinessService.name).all()
    return render_template('certificates/form.html', certificate=cert, users=users, services=services, is_edit=True)

@certificates_bp.route('/<int:id>/versions/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_version(id):
    cert = db.get_or_404(Certificate, id)
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash(WRITE_REQUIRED, 'danger')
                return redirect(url_for(CERTIFICATE_DETAIL, id=id))
        expires_at_str = request.form.get('expires_at')
        if not expires_at_str:
            flash('Expiration date is required.', 'danger')
            return redirect(request.url)

        # Deactivate old active versions?
        # Usually yes, or maybe we want overlapping?
        # Let's simple deactivate others if this is marked active (default)
        old_active = cert.versions.filter_by(is_active=True).all()
        for v in old_active:
            v.is_active = False
        
        version = CertificateVersion(
            certificate_id=cert.id,
            version_notes=request.form.get('version_notes'),
            expires_at=datetime.strptime(expires_at_str, '%Y-%m-%d').date(),
            issuer=request.form.get('issuer'),
            common_name=request.form.get('common_name'),
            serial_number=request.form.get('serial_number'),
            private_key_location=request.form.get('private_key_location'),
            is_active=True
        )
        db.session.add(version)
        db.session.commit()
        
        log_audit(event_type='certificate_version.created', action='create', target_object=f"Certificate:{cert.id}")
        flash('New version added.', 'success')
        return redirect(url_for(CERTIFICATE_DETAIL, id=cert.id))

    return render_template('certificates/version_form.html', certificate=cert)
