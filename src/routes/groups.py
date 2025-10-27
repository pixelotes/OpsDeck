from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Group, User
from .main import login_required
from .admin import admin_required

groups_bp = Blueprint('groups', __name__)

@groups_bp.route('/')
@login_required
def list_groups():
    groups = Group.query.order_by(Group.name).all()
    return render_template('groups/list.html', groups=groups)

@groups_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_group():
    if request.method == 'POST':
        group = Group(
            name=request.form['name'],
            description=request.form.get('description')
        )
        db.session.add(group)
        db.session.commit()
        flash(f'Group "{group.name}" created successfully.', 'success')
        return redirect(url_for('groups.list_groups'))
    
    return render_template('groups/form.html')

@groups_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_group(id):
    group = Group.query.get_or_404(id)
    if request.method == 'POST':
        group.name = request.form['name']
        group.description = request.form.get('description')
        
        # Handle user assignments
        user_ids = request.form.getlist('user_ids')
        group.users = User.query.filter(User.id.in_(user_ids)).filter_by(is_archived=False).all()
        
        db.session.commit()
        flash(f'Group "{group.name}" updated successfully.', 'success')
        return redirect(url_for('groups.list_groups'))

    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('groups/edit.html', group=group, users=users)