from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from ..models import db, AppUser
from .main import login_required
from functools import wraps

admin_bp = Blueprint('admin', __name__)

# Admin authorization decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        user = AppUser.query.get(user_id) if user_id else None
        if not user or user.role != 'admin':
            flash('This area requires administrator privileges.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    users = AppUser.query.order_by(AppUser.username).all()
    return render_template('admin/list_users.html', users=users)

@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if AppUser.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
        else:
            new_user = AppUser(username=username, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'User "{username}" created successfully.', 'success')
            return redirect(url_for('admin.list_users'))

    return render_template('admin/form_user.html')

@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    user_to_delete = AppUser.query.get_or_404(id)
    if user_to_delete.username == 'admin':
        flash('The default admin user cannot be deleted.', 'danger')
        return redirect(url_for('admin.list_users'))
        
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'User "{user_to_delete.username}" has been deleted.', 'success')
    return redirect(url_for('admin.list_users'))