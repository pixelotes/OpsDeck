from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Tag
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

tags_bp = Blueprint('tags', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
TAGS = 'tags.tags'

@tags_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def tags():
    all_tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    return render_template('tags/list.html', tags=all_tags)

@tags_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE)
def archived_tags():
    all_tags = Tag.query.filter_by(is_archived=True).order_by(Tag.name).all()
    return render_template('tags/archived.html', tags=all_tags)


@tags_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def archive_tag(id):
    if not has_write_permission(MODULE):
        flash('Write access required to archive tags.', 'danger')
        return redirect(url_for(TAGS))
    tag = db.get_or_404(Tag, id)
    tag.is_archived = True
    db.session.commit()
    flash(f'Tag "{tag.name}" has been archived.', 'warning')
    return redirect(url_for(TAGS))


@tags_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE)
def unarchive_tag(id):
    if not has_write_permission(MODULE):
        flash('Write access required to restore tags.', 'danger')
        return redirect(url_for('tags.archived_tags'))
    tag = db.get_or_404(Tag, id)
    tag.is_archived = False
    db.session.commit()
    flash(f'Tag "{tag.name}" has been restored.', 'success')
    return redirect(url_for('tags.archived_tags'))

@tags_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_tag():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create tags.', 'danger')
            return redirect(url_for(TAGS))
        tag_name = request.form.get('name')
        if tag_name and not Tag.query.filter_by(name=tag_name).first():
            new_tag = Tag(name=tag_name)
            db.session.add(new_tag)
            db.session.commit()
            flash(f'Tag "{tag_name}" created successfully.', 'success')
        else:
            flash(f'Tag "{tag_name}" already exists or is invalid.', 'danger')
        return redirect(url_for(TAGS))
    return render_template('tags/form.html')

@tags_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_tag(id):
    tag = db.get_or_404(Tag, id)
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update tags.', 'danger')
            return redirect(url_for(TAGS))
        new_name = request.form.get('name')
        if new_name:
            tag.name = new_name
            db.session.commit()
            flash('Tag updated successfully!', 'success')
            return redirect(url_for(TAGS))
    return render_template('tags/form.html', tag=tag)

@tags_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_tag(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete tags.', 'danger')
        return redirect(url_for(TAGS))
    tag = db.get_or_404(Tag, id)
    db.session.delete(tag)
    db.session.commit()
    flash(f'Tag "{tag.name}" deleted successfully.', 'success')
    return redirect(url_for(TAGS))