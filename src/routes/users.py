import os
import uuid
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from ..models import db, User, Attachment, OrgChartSnapshot
from ..models.core import CustomFieldDefinition, OrganizationSettings

from .main import login_required
from weasyprint import HTML
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now


users_bp = Blueprint('users', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'administration'
USERS = 'users.users'
USER_DETAIL = 'users.user_detail'

@users_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def users():
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    return render_template('users/list.html', users=users)

@users_bp.route('/org-chart', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def org_chart():
    users = User.query.filter_by(is_archived=False, hide_from_org_chart=False).all()

    # Build nested tree for OrgChart.js
    user_map = {}
    for u in users:
        user_map[u.id] = {
            'id': u.id,
            'name': u.name,
            'title': u.job_title or 'No Title',
            'department': u.department or '',
            'url': url_for(USER_DETAIL, id=u.id),
            'children': []
        }

    roots = []
    for u in users:
        node = user_map[u.id]
        if u.manager_id and u.manager_id in user_map:
            user_map[u.manager_id]['children'].append(node)
        else:
            roots.append(node)

    # Remove empty children arrays so leaf nodes don't show expand arrows
    def prune_empty_children(node):
        if node.get('children'):
            for child in node['children']:
                prune_empty_children(child)
        else:
            node.pop('children', None)
    for node in user_map.values():
        prune_empty_children(node)

    # If multiple roots, wrap them under a virtual root
    if len(roots) == 1:
        org_tree = roots[0]
    elif roots:
        org_settings = OrganizationSettings.query.first()
        org_name = (org_settings.legal_name if org_settings and org_settings.legal_name else 'Organization')
        org_tree = {'id': 0, 'name': org_name, 'title': org_name, 'className': 'virtual-root', 'children': roots}
    else:
        org_tree = None

    import json
    org_tree_json = json.dumps(org_tree) if org_tree else 'null'

    return render_template('users/org_chart.html', users=users, org_tree_json=org_tree_json)

@users_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def archived_users():
    users = User.query.filter_by(is_archived=True).all()
    return render_template('users/archived.html', users=users)


@users_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_user(id):
    user = db.get_or_404(User, id)

    # Validate that user can be archived
    can_archive, errors = user.can_be_archived()

    if not can_archive:
        for error in errors:
            flash(error, 'danger')
        flash(f'Cannot archive user "{user.name}". Please resolve the issues above first.', 'danger')
        return redirect(url_for(USER_DETAIL, id=id))

    # Clean up non-critical relationships
    user.prepare_for_archival()

    # Archive the user
    user.is_archived = True
    db.session.commit()

    flash(f'User "{user.name}" has been archived successfully.', 'warning')
    return redirect(url_for(USERS))


@users_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_user(id):
    user = db.get_or_404(User, id)
    user.is_archived = False
    db.session.commit()
    flash(f'User "{user.name}" has been restored.', 'success')
    return redirect(url_for('users.archived_users'))

@users_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def user_detail(id):
    user = db.get_or_404(User, id)
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='User').all()
    return render_template('users/detail.html', user=user, custom_field_definitions=custom_field_definitions)

@users_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_user():
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='User').all()

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(USERS))
        manager_id = request.form.get('manager_id')
        buddy_id = request.form.get('buddy_id')

        user = User(
            name=request.form['name'],
            email=request.form.get('email'),
            department=request.form.get('department'),
            job_title=request.form.get('job_title'),
            manager_id=int(manager_id) if manager_id else None,
            buddy_id=int(buddy_id) if buddy_id else None
        )
        db.session.add(user)
        db.session.commit()
        
        # Save custom properties after user has ID
        user.save_custom_properties(request.form)
        db.session.commit()
        
        flash('User created successfully!', 'success')
        return redirect(url_for(USERS))

    return render_template('users/form.html', users=users, custom_field_definitions=custom_field_definitions)

@users_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_user(id):
    user = db.get_or_404(User, id)

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    custom_field_definitions = CustomFieldDefinition.query.filter_by(entity_type='User').all()

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(USER_DETAIL, id=id))
        user.name = request.form['name']
        user.email = request.form.get('email')
        user.department = request.form.get('department')
        user.job_title = request.form.get('job_title')
        
        manager_id = request.form.get('manager_id')
        user.manager_id = int(manager_id) if manager_id else None
        
        buddy_id = request.form.get('buddy_id')
        user.buddy_id = int(buddy_id) if buddy_id else None
        
        # Handle org chart visibility toggle
        user.hide_from_org_chart = request.form.get('hide_from_org_chart') == 'on'
        
        user.save_custom_properties(request.form)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for(USERS))

    return render_template('users/form.html', user=user, users=users, custom_field_definitions=custom_field_definitions)


@users_bp.route('/<int:id>/inventory/generate', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def generate_inventory(id):
    """
    Genera un snapshot en PDF del inventario del usuario y lo guarda
    como un adjunto enlazado a ese usuario.
    """
    user = db.get_or_404(User, id)
    
    # 1. Renderizar la plantilla HTML específica para el PDF
    html_content = render_template(
        'users/inventory_pdf.html', 
        user=user,
        generated_at=now()
    )
    
    # 2. Generar los bytes del PDF en memoria
    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
    except Exception as e:
        current_app.logger.error(f"Error generating PDF with WeasyPrint: {e}")
        flash('Error generating PDF. Check logs.', 'danger')
        return redirect(url_for(USER_DETAIL, id=id))

    # 3. Definir nombres de archivo
    timestamp = now().strftime('%Y-%m-%d_%H%M')
    original_filename = f"Inventory_{user.name.replace(' ', '_')}_{timestamp}.pdf"
    secure_filename_to_save = f"{uuid.uuid4().hex}.pdf"
    
    # 4. Guardar el archivo físico
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secure_filename_to_save)
    
    try:
        with open(save_path, 'wb') as f:
            f.write(pdf_bytes)
    except OSError as e:
        current_app.logger.error(f"Error saving PDF file: {e}")
        flash('Error saving inventory file.', 'danger')
        return redirect(url_for(USER_DETAIL, id=id))

    # 5. Crear el registro 'Attachment' en la BD
    attachment = Attachment(
        filename=original_filename,
        secure_filename=secure_filename_to_save,
        linkable_type='User',
        linkable_id=user.id
    )
    
    db.session.add(attachment)
    db.session.commit()
    
    flash('Inventory snapshot generated and saved.', 'success')
    return redirect(url_for(USER_DETAIL, id=id))

@users_bp.route('/<int:id>/generate-token', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def generate_token(id):
    """Generates a new API token for the user."""
    user = db.get_or_404(User, id)
    user.generate_token()
    db.session.commit()
    
    # Log the action
    current_app.logger.info(
        f"API Token generated for user {user.email}",
        extra={
            "event.action": "user.token_generated",
            "user.id": user.id,
            "user.email": user.email,
            "source.ip": request.remote_addr
        }
    )
    
    flash('New API Token generated successfully.', 'success')
    return redirect(url_for(USER_DETAIL, id=id))

@users_bp.route('/org-chart/snapshot', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def create_org_snapshot():
    if request.method == 'POST':
        name = request.form.get('name') or f'Org Chart - {now().strftime("%Y-%m-%d")}'
        notes = request.form.get('notes')
        
        # 1. Build hierarchy (filter out hidden users)
        users = User.query.filter_by(is_archived=False, hide_from_org_chart=False).all()
        
        data_list = []
        for u in users:
            data_list.append({
                'id': u.id,
                'name': u.name,
                'title': u.job_title,
                'manager_id': u.manager_id,
                'department': u.department,
                'email': u.email
            })
        
        # 2. Save to DB
        snapshot = OrgChartSnapshot(
            name=name,
            chart_data=data_list,
            created_by_id=1, # FIXME: session.get('user_id') but ensuring it's an int
            notes=notes
        )
        # Handle user_id from session safely
        if 'user_id' in from_flask_session_proxy():
             snapshot.created_by_id = from_flask_session_proxy()['user_id']

        db.session.add(snapshot)
        db.session.commit()
        
        flash('Organizational structure snapshot saved successfully.', 'success')
        return redirect(url_for('users.list_org_snapshots'))
    return redirect(url_for('users.org_chart'))

def from_flask_session_proxy():
    from flask import session
    return session

@users_bp.route('/org-chart/snapshots', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_org_snapshots():
    snapshots = OrgChartSnapshot.query.order_by(OrgChartSnapshot.created_at.desc()).all()
    return render_template('users/org_snapshots_list.html', snapshots=snapshots)

@users_bp.route('/org-chart/snapshots/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def view_org_snapshot(id):
    snapshot = db.get_or_404(OrgChartSnapshot, id)

    # Build nested tree from flat chart_data for OrgChart.js
    flat = snapshot.chart_data or []
    node_map = {}
    for u in flat:
        node_map[u['id']] = {
            'id': u['id'],
            'name': u['name'],
            'title': u.get('title') or 'No Title',
            'department': u.get('department') or '',
            'children': []
        }

    roots = []
    for u in flat:
        node = node_map[u['id']]
        mid = u.get('manager_id')
        if mid and mid in node_map:
            node_map[mid]['children'].append(node)
        else:
            roots.append(node)

    def prune_empty_children(node):
        if node.get('children'):
            for child in node['children']:
                prune_empty_children(child)
        else:
            node.pop('children', None)
    for node in node_map.values():
        prune_empty_children(node)

    if len(roots) == 1:
        snap_tree = roots[0]
    elif roots:
        org_settings = OrganizationSettings.query.first()
        org_name = (org_settings.legal_name if org_settings and org_settings.legal_name else 'Organization')
        snap_tree = {'id': 0, 'name': org_name, 'title': org_name, 'className': 'virtual-root', 'children': roots}
    else:
        snap_tree = None

    import json
    snap_tree_json = json.dumps(snap_tree) if snap_tree else 'null'

    return render_template('users/org_snapshot_detail.html', snapshot=snapshot, snap_tree_json=snap_tree_json)