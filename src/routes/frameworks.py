# En src/routes/frameworks.py

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from src.models import db, Framework, FrameworkControl
from sqlalchemy.exc import IntegrityError
from ..services.permissions_service import requires_permission, has_write_permission


frameworks_bp = Blueprint('frameworks', __name__, url_prefix='/frameworks')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'compliance'
CONTROL_DETAIL = 'frameworks.control_detail'
FRAMEWORKS_FORM_HTML = 'frameworks/form.html'

# --- Main framework routes ---

@frameworks_bp.route('/', methods=['GET'])
@requires_permission(MODULE)
def list():
    """Lists every framework."""
    frameworks = Framework.query.order_by(Framework.name).all()
    return render_template('frameworks/list.html', frameworks=frameworks)

@frameworks_bp.route('/<int:id>', methods=['GET'])
@requires_permission(MODULE)
def detail(id):
    """Shows a framework and its controls."""
    framework = db.get_or_404(Framework, id)
    controls = framework.framework_controls.order_by(FrameworkControl.control_id).all()
    return render_template(
        'frameworks/detail.html',
        framework=framework,
        controls=controls
    )

@frameworks_bp.route('/new', methods=['GET', 'POST'])
@requires_permission(MODULE)
def create():
    if not has_write_permission(MODULE):
        flash('You do not have permission to create frameworks.', 'danger')
        return redirect(url_for('frameworks.list'))
    """Creates a custom framework."""
    if request.method == 'POST':
        # Read the fields by hand
        name = request.form.get('name')
        description = request.form.get('description')
        link = request.form.get('link')
        # A checkbox submits 'on' when ticked and nothing at all when not
        is_active = request.form.get('is_active') == 'on'
        
        # Validated by hand
        if not name:
            flash('Name is required.', 'danger')
            # Hand the values back so the form can be repopulated
            return render_template(
                FRAMEWORKS_FORM_HTML, 
                title="Nuevo Framework", 
                framework_data=request.form
            ), 400

        try:
            new_framework = Framework(
                name=name,
                description=description,
                link=link,
                is_active=is_active,
                is_custom=True
            )
            db.session.add(new_framework)
            db.session.commit()
            flash('Framework created successfully.', 'success')
            return redirect(url_for('frameworks.edit', id=new_framework.id))
        except IntegrityError:
            db.session.rollback()
            flash('A framework with that name already exists.', 'danger')
            return render_template(
                FRAMEWORKS_FORM_HTML, 
                title="Nuevo Framework", 
                framework_data=request.form
            ), 400
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating framework: {e}', 'danger')
            
    # GET request
    return render_template(FRAMEWORKS_FORM_HTML, title="Nuevo Framework")

@frameworks_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@requires_permission(MODULE)
def edit(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to edit frameworks.', 'danger')
        return redirect(url_for('frameworks.detail', id=id))
    """Edita un framework."""
    framework = db.get_or_404(Framework, id)
    
    if request.method == 'POST':
        # Enabling and disabling is allowed on every framework
        framework.is_active = request.form.get('is_active') == 'on'
        
        # Only 'custom' frameworks may have these fields edited
        if framework.is_custom:
            name = request.form.get('name')
            if not name:
                flash('Name is required.', 'danger')
                return render_template(
                    FRAMEWORKS_FORM_HTML,
                    framework=framework,
                    title="Editar Framework"
                ), 400
            
            framework.name = name
            framework.description = request.form.get('description')
            framework.link = request.form.get('link')
        
        try:
            db.session.commit()
            flash('Framework updated.', 'success')
            return redirect(url_for('frameworks.detail', id=id))
        except IntegrityError:
            db.session.rollback()
            flash('A framework with that name already exists.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating framework: {e}', 'danger')

    # GET request
    controls = framework.framework_controls.order_by(FrameworkControl.control_id).all()
    return render_template(
        FRAMEWORKS_FORM_HTML,
        framework=framework,  # Pasamos el objeto para rellenar el form
        controls=controls,
        title="Editar Framework"
    )

@frameworks_bp.route('/<int:id>/delete', methods=['POST'])
@requires_permission(MODULE)
def delete(id):
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'message': 'You do not have permission to delete frameworks.'}), 403
    """
    Elimina un framework (solo si es 'custom').
    Called by fetch() from the 'Danger Zone' button.
    """
    framework = db.get_or_404(Framework, id)
    if not framework.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden eliminar los frameworks incorporados.'}), 403
        
    try:
        db.session.delete(framework)
        db.session.commit()
        flash('Framework deleted successfully.', 'success')
        # Returns JSON carrying the URL to redirect to
        return jsonify({'success': True, 'redirect_url': url_for('frameworks.list')})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error al eliminar el framework: {e}'}), 500


# --- Routes behind the controls modal (AJAX) ---

@frameworks_bp.route('/control/add', methods=['POST'])
@requires_permission(MODULE)
def add_control():
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'message': 'You do not have permission to modify controls.'}), 403
    """Adds a control to a framework."""
    framework_id = request.form.get('framework_id')
    control_id_text = request.form.get('control_id_text')
    name = request.form.get('name')
    description = request.form.get('description')

    # Validated by hand
    if not framework_id or not control_id_text or not name:
        return jsonify({'success': False, 'message': 'ID del Control y Nombre son obligatorios.'}), 400

    fw = db.get_or_404(Framework, framework_id)
    if not fw.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden añadir controles a frameworks incorporados.'}), 403

    try:
        new_control = FrameworkControl(
            framework_id=fw.id,
            control_id=control_id_text,
            name=name,
            description=description
        )
        db.session.add(new_control)
        db.session.commit()
        flash('Control added successfully.', 'success')
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {e}'}), 500

@frameworks_bp.route('/control/<int:id>/get_data', methods=['GET'])
@requires_permission(MODULE)
def get_control_data(id):
    # Esta ruta no necesita 'forms' y puede quedar igual
    control = db.get_or_404(FrameworkControl, id)
    if not control.framework.is_custom:
         return jsonify({'error': 'No se pueden editar controles de frameworks incorporados.'}), 403
    return jsonify({
        'control_id_text': control.control_id,
        'name': control.name,
        'description': control.description or '', # Asegurarnos de no enviar 'None'
        'framework_id': control.framework_id
    })

@frameworks_bp.route('/control/<int:id>/edit', methods=['POST'])
@requires_permission(MODULE)
def edit_control(id):
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'message': 'You do not have permission to modify controls.'}), 403
    """Actualiza un control."""
    control = db.get_or_404(FrameworkControl, id)
    if not control.framework.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden editar controles de frameworks incorporados.'}), 403
        
    control_id_text = request.form.get('control_id_text')
    name = request.form.get('name')
    description = request.form.get('description')

    if not control_id_text or not name:
        return jsonify({'success': False, 'message': 'ID del Control y Nombre son obligatorios.'}), 400
        
    try:
        control.control_id = control_id_text
        control.name = name
        control.description = description
        db.session.commit()
        flash('Control updated.', 'success')
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {e}'}), 500

@frameworks_bp.route('/control/<int:id>/delete', methods=['POST'])
@requires_permission(MODULE)
def delete_control(id):
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'message': 'You do not have permission to modify controls.'}), 403
    """
    Elimina un control.
    Called by fetch() from the row's delete button.
    """
    control = db.get_or_404(FrameworkControl, id)
    if not control.framework.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden eliminar controles de frameworks incorporados.'}), 403

    try:
        db.session.delete(control)
        db.session.commit()
        flash('Control deleted.', 'success')
        # Returns JSON so the page can reload itself
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error al eliminar el control: {e}'}), 500


# --- Cross-Framework Control Mapping Routes ---

@frameworks_bp.route('/control/<int:id>/detail', methods=['GET'])
@requires_permission(MODULE)
def control_detail(id):
    """Displays control detail with cross-mappings and linked evidence."""
    from ..models.core import Tag, Link, Documentation
    from ..models.policy import Policy
    from ..models.services import BusinessService
    from ..services.compliance_service import get_compliance_evaluator
    
    control = db.get_or_404(FrameworkControl, id)
    all_frameworks = Framework.query.order_by(Framework.name).all()
    all_tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    
    # Evaluate automation rules in real-time
    evaluator = get_compliance_evaluator()
    automated_evidence = []
    for rule in control.rules:
        if rule.enabled:
            result = evaluator.evaluate_rule(rule)
            automated_evidence.append({
                'rule': rule,
                'status': result['status'],
                'evidence': result.get('evidence'),
                'last_check': result.get('last_evidence_date'),
                'message': result.get('message', ''),
                'days_since': result.get('days_since', -1)
            })
    
    # Manual compliance links
    manual_links = control.compliance_links.all()
    
    # Load available items for the manual linking modal
    available_policies = Policy.query.order_by(Policy.title).all()
    available_services = BusinessService.query.order_by(BusinessService.name).all()
    available_docs = Documentation.query.order_by(Documentation.name).all()
    available_links = Link.query.order_by(Link.name).all()
    
    return render_template(
        'frameworks/control_detail.html',
        control=control,
        all_frameworks=all_frameworks,
        all_tags=all_tags,
        automated_evidence=automated_evidence,
        manual_links=manual_links,
        available_policies=available_policies,
        available_services=available_services,
        available_docs=available_docs,
        available_links=available_links
    )


@frameworks_bp.route('/control/<int:id>/soa', methods=['POST'])
@requires_permission(MODULE)
def update_control_soa(id):
    """Updates the Statement of Applicability for a framework control."""
    if not has_write_permission(MODULE):
        flash('Write access required to update SOA.', 'danger')
        return redirect(url_for(CONTROL_DETAIL, id=id))

    control = db.get_or_404(FrameworkControl, id)

    control.is_applicable = request.form.get('is_applicable') == 'on'
    if not control.is_applicable:
        control.soa_justification = request.form.get('soa_justification', '')
    else:
        control.soa_justification = None

    try:
        db.session.commit()
        flash('Statement of Applicability updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating SOA: {str(e)}', 'danger')

    return redirect(url_for(CONTROL_DETAIL, id=id))


@frameworks_bp.route('/control/<int:id>/map', methods=['POST'])
@requires_permission(MODULE)
def map_control(id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to modify control mappings.', 'danger')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    """Links a control to another control (cross-framework mapping)."""
    control = db.get_or_404(FrameworkControl, id)
    target_control_id = request.form.get('target_control_id')
    
    if not target_control_id:
        flash('Please select a target control.', 'warning')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    
    target_control = db.session.get(FrameworkControl,target_control_id)
    if not target_control:
        flash('Target control not found.', 'danger')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    
    if target_control.id == control.id:
        flash('Cannot map a control to itself.', 'warning')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    
    # Check if already mapped
    if target_control in control.mapped_targets or control in target_control.mapped_targets:
        flash('These controls are already mapped.', 'info')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    
    try:
        control.mapped_targets.append(target_control)
        db.session.commit()
        flash(f'Mapped to {target_control.framework.name} {target_control.control_id}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating mapping: {e}', 'danger')
    
    return redirect(url_for(CONTROL_DETAIL, id=id))


@frameworks_bp.route('/control/<int:id>/unmap/<int:target_id>', methods=['POST'])
@requires_permission(MODULE)
def unmap_control(id, target_id):
    if not has_write_permission(MODULE):
        flash('You do not have permission to modify control mappings.', 'danger')
        return redirect(url_for(CONTROL_DETAIL, id=id))
    """Removes a cross-framework mapping between two controls."""
    control = db.get_or_404(FrameworkControl, id)
    target_control = db.get_or_404(FrameworkControl, target_id)
    
    try:
        # Check both directions since mapping can be in either direction
        if target_control in control.mapped_targets:
            control.mapped_targets.remove(target_control)
        elif control in target_control.mapped_targets:
            target_control.mapped_targets.remove(control)
        else:
            flash('Mapping not found.', 'warning')
            return redirect(url_for(CONTROL_DETAIL, id=id))
        
        db.session.commit()
        flash('Mapping removed.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing mapping: {e}', 'danger')
    
    return redirect(url_for(CONTROL_DETAIL, id=id))


@frameworks_bp.route('/api/search-controls', methods=['GET'])
@requires_permission(MODULE)
def search_controls():
    """API to search controls for cross-mapping (for TomSelect)."""
    q = request.args.get('q', '').strip().lower()
    framework_id = request.args.get('framework_id', type=int)
    exclude_id = request.args.get('exclude_id', type=int)  # Current control to exclude
    
    query = FrameworkControl.query
    
    # Filter by framework if specified
    if framework_id:
        query = query.filter(FrameworkControl.framework_id == framework_id)
    
    # Exclude current control
    if exclude_id:
        query = query.filter(FrameworkControl.id != exclude_id)
    
    # Search in control_id and name
    if q:
        query = query.filter(
            db.or_(
                FrameworkControl.control_id.ilike(f'%{q}%'),
                FrameworkControl.name.ilike(f'%{q}%')
            )
        )
    
    controls = query.limit(50).all()
    
    results = []
    for ctrl in controls:
        results.append({
            'id': ctrl.id,
            'text': f"[{ctrl.framework.name}] {ctrl.control_id} - {ctrl.name[:50]}"
        })
    
    return jsonify(results)