# En src/routes/frameworks.py

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from .main import login_required
from src.models import db, Framework, FrameworkControl
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from .admin import admin_required


frameworks_bp = Blueprint('frameworks', __name__, url_prefix='/frameworks')

# --- Rutas Principales del Framework ---

@frameworks_bp.route('/')
@login_required
def list():
    """Muestra la lista de todos los frameworks."""
    frameworks = Framework.query.order_by(Framework.name).all()
    return render_template('frameworks/list.html', frameworks=frameworks)

@frameworks_bp.route('/<int:id>')
@login_required
def detail(id):
    """Muestra los detalles de un framework y sus controles."""
    framework = Framework.query.get_or_404(id)
    controls = framework.framework_controls.order_by(FrameworkControl.control_id).all()
    return render_template(
        'frameworks/detail.html',
        framework=framework,
        controls=controls
    )

@frameworks_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    """Crea un nuevo framework personalizado."""
    if request.method == 'POST':
        # Obtener datos manualmente
        name = request.form.get('name')
        description = request.form.get('description')
        link = request.form.get('link')
        # Los checkboxes envían 'on' si están marcados, o None si no
        is_active = request.form.get('is_active') == 'on'
        
        # Validación manual
        if not name:
            flash('El nombre es obligatorio.', 'danger')
            # Devolvemos los datos para "repoblar" el formulario
            return render_template(
                'frameworks/form.html', 
                title="Nuevo Framework", 
                framework_data=request.form
            ), 400

        try:
            new_framework = Framework(
                name=name,
                description=description,
                link=link,
                is_active=is_active,
                is_custom=True  # Los creados por usuarios siempre son custom
            )
            db.session.add(new_framework)
            db.session.commit()
            flash('Framework creado con éxito.', 'success')
            return redirect(url_for('frameworks.edit', id=new_framework.id))
        except IntegrityError:
            db.session.rollback()
            flash('Ya existe un framework con ese nombre.', 'danger')
            return render_template(
                'frameworks/form.html', 
                title="Nuevo Framework", 
                framework_data=request.form
            ), 400
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear el framework: {e}', 'danger')
            
    # GET request
    return render_template('frameworks/form.html', title="Nuevo Framework")

@frameworks_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
@login_required
def edit(id):
    """Edita un framework."""
    framework = Framework.query.get_or_404(id)
    
    if request.method == 'POST':
        # Activar/Desactivar SÍ se permite para todos
        framework.is_active = request.form.get('is_active') == 'on'
        
        # Solo permitir edición de campos si es 'custom'
        if framework.is_custom:
            name = request.form.get('name')
            if not name:
                flash('El nombre es obligatorio.', 'danger')
                return render_template(
                    'frameworks/form.html',
                    framework=framework,
                    title="Editar Framework"
                ), 400
            
            framework.name = name
            framework.description = request.form.get('description')
            framework.link = request.form.get('link')
        
        try:
            db.session.commit()
            flash('Framework actualizado.', 'success')
            return redirect(url_for('frameworks.detail', id=id))
        except IntegrityError:
            db.session.rollback()
            flash('Ya existe un framework con ese nombre.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar el framework: {e}', 'danger')

    # GET request
    controls = framework.framework_controls.order_by(FrameworkControl.control_id).all()
    return render_template(
        'frameworks/form.html',
        framework=framework,  # Pasamos el objeto para rellenar el form
        controls=controls,
        title="Editar Framework"
    )

@frameworks_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(id):
    """
    Elimina un framework (solo si es 'custom').
    Llamado por fetch() desde el botón de 'Zona de Peligro'.
    """
    framework = Framework.query.get_or_404(id)
    if not framework.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden eliminar los frameworks incorporados.'}), 403
        
    try:
        db.session.delete(framework)
        db.session.commit()
        flash('Framework eliminado correctamente.', 'success')
        # Devolvemos JSON con la URL a la que redirigir
        return jsonify({'success': True, 'redirect_url': url_for('frameworks.list')})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error al eliminar el framework: {e}'}), 500


# --- Rutas para el Modal de Controles (AJAX) ---

@frameworks_bp.route('/control/add', methods=['POST'])
@login_required
@admin_required
def add_control():
    """Añade un nuevo control a un framework."""
    framework_id = request.form.get('framework_id')
    control_id_text = request.form.get('control_id_text')
    name = request.form.get('name')
    description = request.form.get('description')

    # Validación manual
    if not framework_id or not control_id_text or not name:
        return jsonify({'success': False, 'message': 'ID del Control y Nombre son obligatorios.'}), 400

    fw = Framework.query.get_or_404(framework_id)
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
        flash('Control añadido correctamente.', 'success')
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {e}'}), 500

@frameworks_bp.route('/control/<int:id>/get_data', methods=['GET'])
@login_required
def get_control_data(id):
    # Esta ruta no necesita 'forms' y puede quedar igual
    control = FrameworkControl.query.get_or_404(id)
    if not control.framework.is_custom:
         return jsonify({'error': 'No se pueden editar controles de frameworks incorporados.'}), 403
    return jsonify({
        'control_id_text': control.control_id,
        'name': control.name,
        'description': control.description or '', # Asegurarnos de no enviar 'None'
        'framework_id': control.framework_id
    })

@frameworks_bp.route('/control/<int:id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_control(id):
    """Actualiza un control."""
    control = FrameworkControl.query.get_or_404(id)
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
        flash('Control actualizado.', 'success')
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error: {e}'}), 500

@frameworks_bp.route('/control/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_control(id):
    """
    Elimina un control.
    Llamado por fetch() desde el botón de 'eliminar' de la fila.
    """
    control = FrameworkControl.query.get_or_404(id)
    if not control.framework.is_custom:
        return jsonify({'success': False, 'message': 'No se pueden eliminar controles de frameworks incorporados.'}), 403

    try:
        db.session.delete(control)
        db.session.commit()
        flash('Control eliminado.', 'success')
        # Devolvemos JSON para que la página se recargue
        return jsonify({'success': True, 'reload': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error al eliminar el control: {e}'}), 500