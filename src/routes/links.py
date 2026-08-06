from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Link, Tag, User, Group, Software
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..utils.redirects import safe_redirect_target

links_bp = Blueprint('links', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'knowledge_policy'
DETAIL = 'links.detail'

@links_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_links():
    """Lists links, with filters."""
    
    # Read the filter parameters off the URL
    search_name = request.args.get('search_name', '')
    search_tags = request.args.getlist('tags') # getlist() handles the multi-select

    # Query base
    query = Link.query

    # Aplicar filtro por nombre
    if search_name:
        query = query.filter(Link.name.ilike(f'%{search_name}%'))

    # Aplicar filtro por tags
    if search_tags:
        # Join the tag table and filter by the selected tag names
        query = query.join(Link.tags).filter(Tag.name.in_(search_tags))

    # Ejecutar la query
    links = query.order_by(Link.name).all()
    
    # All tags, for the filter dropdown
    all_tags = Tag.query.order_by(Tag.name).all()

    return render_template(
        'links/list.html', 
        links=links,
        all_tags=all_tags,
        search_name=search_name,
        search_tags=search_tags
    )

@links_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def detail(id):
    """Shows one link."""
    link = db.get_or_404(Link, id)
    return render_template('links/detail.html', link=link)

@links_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_link():
    """Creates a link."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create links.', 'danger')
            return redirect(url_for('links.list_links'))
        # Resolve the polymorphic owner
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

        # Create the base record
        link = Link(
            name=request.form['name'],
            description=request.form.get('description'),
            url=request.form['url'],
            owner_type=owner_type,
            owner_id=owner_id,
            software_id=request.form.get('software_id') or None
        )
        
        # Assign tags
        tag_ids = request.form.getlist('tags')
        link.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        
        db.session.add(link)
        db.session.commit()

        flash('Link created.', 'success')
        return redirect(url_for(DETAIL, id=link.id))

    # --- GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('links/form.html', users=users, groups=groups, software=software, tags=tags)


@links_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_link(id):
    """Edita un enlace existente."""
    link = db.get_or_404(Link, id)

    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update links.', 'danger')
            return redirect(url_for(DETAIL, id=id))
        # Resolve the polymorphic owner
        owner_full = request.form.get('owner')
        if owner_full:
            try:
                link.owner_type, owner_id_str = owner_full.split('-', 1)
                link.owner_id = int(owner_id_str)
            except ValueError:
                flash('Invalid owner.', 'danger')
                return redirect(safe_redirect_target(request.referrer))
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
        flash('Link updated.', 'success')
        return redirect(url_for(DETAIL, id=link.id))

    # --- GET ---
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    software = Software.query.order_by(Software.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    
    return render_template('links/form.html', link=link, users=users, groups=groups, software=software, tags=tags)

@links_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_link(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete links.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """Deletes a link."""
    link = db.get_or_404(Link, id)
    
    db.session.delete(link)
    db.session.commit()
    flash('Link deleted.', 'success')
    return redirect(url_for('links.list_links'))
