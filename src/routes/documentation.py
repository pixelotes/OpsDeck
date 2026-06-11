import os
import uuid
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from werkzeug.utils import secure_filename
from ..models import db, Documentation, Tag, User, Group, Software, Attachment
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..utils.redirects import safe_redirect_target

documentation_bp = Blueprint('documentation', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'knowledge_policy'
DETAIL = 'documentation.detail'

@documentation_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_docs():
    """Muestra la lista de documentación, con filtros."""
    
    # Obtener parámetros de filtro de la URL
    search_name = request.args.get('search_name', '')
    search_tags = request.args.getlist('tags') # .getlist() para select múltiple

    # Query base
    query = Documentation.query

    # Aplicar filtro por nombre
    if search_name:
        query = query.filter(Documentation.name.ilike(f'%{search_name}%'))

    # Aplicar filtro por tags
    if search_tags:
        # Unir con la tabla Tag y filtrar por los nombres de tag seleccionados
        query = query.join(Documentation.tags).filter(Tag.name.in_(search_tags))

    # Ejecutar la query
    documentation = query.order_by(Documentation.name).all()
    
    # Obtener todos los tags para el dropdown del filtro
    all_tags = Tag.query.order_by(Tag.name).all()

    return render_template(
        'documentation/list.html', 
        documentation=documentation,
        all_tags=all_tags,
        search_name=search_name,
        search_tags=search_tags
    )

@documentation_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def detail(id):
    """Muestra los detalles de una entrada de documentación."""
    doc = db.get_or_404(Documentation, id)
    return render_template('documentation/detail.html', doc=doc)

@documentation_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_doc():
    """Crea una nueva entrada de documentación."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create documentation.', 'danger')
            return redirect(url_for('documentation.list_docs'))
        # Procesar propietario polimórfico
        owner_full = request.form.get('owner')
        owner_type = None
        owner_id = None
        if owner_full:
            try:
                owner_type, owner_id = owner_full.split('-', 1)
                owner_id = int(owner_id)
            except ValueError:
                flash('Invalid owner.', 'danger')
                return redirect(safe_redirect_target(request.referrer))

        # Crear el objeto base
        doc = Documentation(
            name=request.form['name'],
            description=request.form.get('description'),
            external_link=request.form.get('external_link'),
            owner_type=owner_type,
            owner_id=owner_id,
            software_id=request.form.get('software_id') or None
        )
        
        # Asignar tags
        tag_ids = request.form.getlist('tags')
        doc.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        
        db.session.add(doc)
        db.session.commit() # Commit para obtener doc.id

        # Manejar subida de archivo
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
                    linkable_type='Documentation',
                    linkable_id=doc.id
                )
                db.session.add(attachment)
                db.session.commit()

        flash('Documentation entry created.', 'success')
        return redirect(url_for(DETAIL, id=doc.id))

    # --- Lógica GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('documentation/form.html', users=users, groups=groups, software=software, tags=tags)


@documentation_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_doc(id):
    """Edita una entrada de documentación existente."""
    doc = db.get_or_404(Documentation, id)

    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update documentation.', 'danger')
            return redirect(url_for(DETAIL, id=id))
        # Procesar propietario polimórfico
        owner_full = request.form.get('owner')
        if owner_full:
            try:
                doc.owner_type, owner_id_str = owner_full.split('-', 1)
                doc.owner_id = int(owner_id_str)
            except ValueError:
                flash('Invalid owner.', 'danger')
                return redirect(safe_redirect_target(request.referrer))
        else:
            doc.owner_type = None
            doc.owner_id = None

        # Actualizar campos
        doc.name = request.form['name']
        doc.description = request.form.get('description')
        doc.external_link = request.form.get('external_link')
        doc.software_id = request.form.get('software_id') or None
        
        # Actualizar tags
        tag_ids = request.form.getlist('tags')
        doc.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

        # Manejar subida de archivo (reemplaza si existe)
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                # (Opcional: borrar archivo antiguo si existe)
                # ...

                original_filename = secure_filename(file.filename)
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex}{file_ext}"
                
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
                
                attachment = Attachment(
                    filename=original_filename,
                    secure_filename=unique_filename,
                    linkable_type='Documentation',
                    linkable_id=doc.id
                )
                db.session.add(attachment)

        db.session.commit()
        flash('Documentation entry updated.', 'success')
        return redirect(url_for(DETAIL, id=doc.id))

    # --- Lógica GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('documentation/form.html', doc=doc, users=users, groups=groups, software=software, tags=tags)

@documentation_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_doc(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete documentation.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """Elimina una entrada de documentación."""
    doc = db.get_or_404(Documentation, id)
    
    # (Opcional: eliminar archivos físicos de adjuntos)
    # for att in doc.attachments:
    #     try:
    #         os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], att.secure_filename))
    #     except OSError:
    #         pass # Ignorar si el archivo no existe
            
    db.session.delete(doc)
    db.session.commit()
    flash('Documentation entry deleted.', 'success')
    return redirect(url_for('documentation.list_docs'))

@documentation_bp.route('/api/search', methods=['GET'])
@login_required
@requires_permission(MODULE)
def search_api():
    """Search documentation by title or filename for TomSelect."""
    from flask import jsonify
    
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    
    # Search by name (which is the title field)
    docs = Documentation.query.filter(
        (Documentation.name.ilike(f'%{query}%'))
    ).limit(20).all()
    
    return jsonify([
        {
            'id': d.id,
            'title': d.name,
            'filename': d.external_link or 'Internal'
        } 
        for d in docs
    ])
