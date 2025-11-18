import os
import uuid
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from werkzeug.utils import secure_filename
from ..models import db, Link, Tag, User, Group, Software
from .main import login_required
from .admin import admin_required

links_bp = Blueprint('links', __name__)

@links_bp.route('/')
@login_required
def list_links():
    """Muestra la lista de enlaces, con filtros."""
    
    # Obtener parámetros de filtro de la URL
    search_name = request.args.get('search_name', '')
    search_tags = request.args.getlist('tags') # .getlist() para select múltiple

    # Query base
    query = Link.query

    # Aplicar filtro por nombre
    if search_name:
        query = query.filter(Link.name.ilike(f'%{search_name}%'))

    # Aplicar filtro por tags
    if search_tags:
        # Unir con la tabla Tag y filtrar por los nombres de tag seleccionados
        query = query.join(Link.tags).filter(Tag.name.in_(search_tags))

    # Ejecutar la query
    links = query.order_by(Link.name).all()
    
    # Obtener todos los tags para el dropdown del filtro
    all_tags = Tag.query.order_by(Tag.name).all()

    return render_template(
        'links/list.html', 
        links=links,
        all_tags=all_tags,
        search_name=search_name,
        search_tags=search_tags
    )

@links_bp.route('/<int:id>')
@login_required
def detail(id):
    """Muestra los detalles de un enlace."""
    link = Link.query.get_or_404(id)
    return render_template('links/detail.html', link=link)

@links_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_link():
    """Crea un nuevo enlace."""
    if request.method == 'POST':
        # Procesar propietario polimórfico
        owner_full = request.form.get('owner')
        owner_type = None
        owner_id = None
        if owner_full:
            try:
                owner_type, owner_id = owner_full.split('-', 1)
                owner_id = int(owner_id)
            except ValueError:
                flash('Propietario (Owner) inválido.', 'danger')
                return redirect(request.referrer)

        # Crear el objeto base
        link = Link(
            name=request.form['name'],
            description=request.form.get('description'),
            url=request.form['url'],
            owner_type=owner_type,
            owner_id=owner_id,
            software_id=request.form.get('software_id') or None
        )
        
        # Asignar tags
        tag_ids = request.form.getlist('tags')
        link.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        
        db.session.add(link)
        db.session.commit()

        flash('Enlace creado.', 'success')
        return redirect(url_for('links.detail', id=link.id))

    # --- Lógica GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('links/form.html', users=users, groups=groups, software=software, tags=tags)


@links_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_link(id):
    """Edita un enlace existente."""
    link = Link.query.get_or_404(id)

    if request.method == 'POST':
        # Procesar propietario polimórfico
        owner_full = request.form.get('owner')
        if owner_full:
            try:
                link.owner_type, owner_id_str = owner_full.split('-', 1)
                link.owner_id = int(owner_id_str)
            except ValueError:
                flash('Propietario (Owner) inválido.', 'danger')
                return redirect(request.referrer)
        else:
            link.owner_type = None
            link.owner_id = None

        # Actualizar campos
        link.name = request.form['name']
        link.description = request.form.get('description')
        link.url = request.form['url']
        link.software_id = request.form.get('software_id') or None
        
        # Actualizar tags
        tag_ids = request.form.getlist('tags')
        link.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

        db.session.commit()
        flash('Enlace actualizado.', 'success')
        return redirect(url_for('links.detail', id=link.id))

    # --- Lógica GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('links/form.html', link=link, users=users, groups=groups, software=software, tags=tags)

@links_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_link(id):
    """Elimina un enlace."""
    link = Link.query.get_or_404(id)
    
    db.session.delete(link)
    db.session.commit()
    flash('Enlace eliminado.', 'success')
    return redirect(url_for('links.list_links'))
