from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Group, User
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

groups_bp = Blueprint('groups', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'administration'
LIST_GROUPS = 'groups.list_groups'

@groups_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_groups():
    groups = Group.query.order_by(Group.name).all()
    return render_template('groups/list.html', groups=groups)

@groups_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_group():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(LIST_GROUPS))
        group = Group(
            name=request.form['name'],
            description=request.form.get('description')
        )
        db.session.add(group)
        db.session.commit()
        flash(f'Group "{group.name}" created successfully.', 'success')
        return redirect(url_for(LIST_GROUPS))
    
    return render_template('groups/form.html')

@groups_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_group(id):
    group = db.get_or_404(Group, id)
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(LIST_GROUPS))
        group.name = request.form['name']
        group.description = request.form.get('description')
        
        # Handle user assignments
        user_ids = request.form.getlist('user_ids')
        group.users = User.query.filter(User.id.in_(user_ids)).filter_by(is_archived=False).all()
        
        db.session.commit()
        flash(f'Group "{group.name}" updated successfully.', 'success')
        return redirect(url_for(LIST_GROUPS))

    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('groups/edit.html', group=group, users=users)