from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Tag
from .main import login_required

tags_bp = Blueprint('tags', __name__)

@tags_bp.route('/')
@login_required
def tags():
    all_tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    return render_template('tags/list.html', tags=all_tags)

@tags_bp.route('/archived')
@login_required
def archived_tags():
    all_tags = Tag.query.filter_by(is_archived=True).order_by(Tag.name).all()
    return render_template('tags/archived.html', tags=all_tags)


@tags_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_tag(id):
    tag = Tag.query.get_or_404(id)
    tag.is_archived = True
    db.session.commit()
    flash(f'Tag "{tag.name}" has been archived.')
    return redirect(url_for('tags.tags'))


@tags_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_tag(id):
    tag = Tag.query.get_or_404(id)
    tag.is_archived = False
    db.session.commit()
    flash(f'Tag "{tag.name}" has been restored.')
    return redirect(url_for('tags.archived_tags'))

@tags_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_tag():
    if request.method == 'POST':
        tag_name = request.form.get('name')
        if tag_name and not Tag.query.filter_by(name=tag_name).first():
            new_tag = Tag(name=tag_name)
            db.session.add(new_tag)
            db.session.commit()
            flash(f'Tag "{tag_name}" created successfully.')
        else:
            flash(f'Tag "{tag_name}" already exists or is invalid.', 'error')
        return redirect(url_for('tags.tags'))
    return render_template('tags/form.html')

@tags_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_tag(id):
    tag = Tag.query.get_or_404(id)
    if request.method == 'POST':
        new_name = request.form.get('name')
        if new_name:
            tag.name = new_name
            db.session.commit()
            flash('Tag updated successfully!')
            return redirect(url_for('tags.tags'))
    return render_template('tags/form.html', tag=tag)

@tags_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_tag(id):
    tag = Tag.query.get_or_404(id)
    db.session.delete(tag)
    db.session.commit()
    flash(f'Tag "{tag.name}" deleted successfully.')
    return redirect(url_for('tags.tags'))