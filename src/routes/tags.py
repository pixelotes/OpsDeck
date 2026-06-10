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

# Entity types that can carry a Tag (backref on Tag model) ->
# (label, icon, relationship attr, detail endpoint, id-arg name)
_TAG_USAGE = [
    ('Subscriptions', 'fa-sync-alt', 'subscriptions', 'subscriptions.subscription_detail', 'id'),
    ('Changes', 'fa-exchange-alt', 'changes', 'changes.detail_change', 'id'),
    ('Requests', 'fa-inbox', 'requests', 'requests.detail_request', 'id'),
    ('Security Incidents', 'fa-fire', 'security_incidents', 'compliance.incident_detail', 'id'),
    ('Documentation', 'fa-book', 'documentation', 'documentation.detail', 'id'),
    ('Links', 'fa-link', 'links', 'links.detail', 'id'),
    ('Maintenance Logs', 'fa-tools', 'maintenance_logs', 'maintenance.log_detail', 'id'),
    ('Purchases', 'fa-shopping-cart', 'purchases', 'purchases.purchase_detail', 'id'),
    ('Security Activities', 'fa-clipboard-check', 'security_activities', 'activities.activity_detail', 'id'),
    ('Activity Executions', 'fa-play', 'activity_executions', 'activities.execution_detail', 'id'),
    ('BCDR Test Logs', 'fa-vial', 'bcdr_test_logs', 'compliance.bcdr_test_log_detail', 'test_id'),
    ('Campaigns', 'fa-bullhorn', 'campaigns_tagged', 'campaigns.detail', 'id'),
]


def _tag_item_label(obj):
    """Best-effort human label for a tagged object across heterogeneous models."""
    for attr in ('name', 'title', 'description', 'version_notes'):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return f"#{obj.id}"

@tags_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def tags():
    all_tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    return render_template('tags/list.html', tags=all_tags)

@tags_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE)
def tag_detail(id):
    tag = db.get_or_404(Tag, id)
    sections = []
    for label, icon, relname, endpoint, arg in _TAG_USAGE:
        rel = getattr(tag, relname, None)
        if rel is None:
            continue
        items = sorted(
            ({'text': _tag_item_label(o), 'url': url_for(endpoint, **{arg: o.id})} for o in rel),
            key=lambda d: d['text'].lower()
        )
        if items:
            sections.append({'label': label, 'icon': icon, 'count': len(items), 'entries': items})
    total = sum(s['count'] for s in sections)
    return render_template('tags/detail.html', tag=tag, sections=sections, total=total)

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