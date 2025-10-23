from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from ..models import db, User
from .main import login_required
from functools import wraps

admin_bp = Blueprint('admin', __name__)

# Admin authorization decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            # ... redirect to login
            return redirect(url_for('main.login'))

        user = User.query.get(user_id) # ALWAYS fetch from DB

        if not user or user.role != 'admin':
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    return render_template('admin/list_users.html', users=users)

@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

        if User.query.filter_by(email=email).first():
            flash('User with that email already exists.', 'danger')
        else:
            new_user = User(name=name, email=email, role=role)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash(f'User "{name}" created successfully.', 'success')
            return redirect(url_for('admin.list_users'))

    return render_template('admin/form_user.html')

@admin_bp.route('/users/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id):
    user = User.query.get_or_404(id)
    if user.name == 'admin':
        flash('The default admin user cannot be edited.', 'danger')
        return redirect(url_for('admin.list_users'))

    if request.method == 'POST':
        new_email = request.form.get('email')
        
        # Check if email is being changed and if the new one is already taken
        if new_email != user.email and User.query.filter_by(email=new_email).first():
            flash('That email is already in use.', 'danger')
            return render_template('admin/edit_user.html', user=user)

        user.name = request.form.get('name')
        user.email = new_email
        user.role = request.form.get('role')
        
        password = request.form.get('password')
        if password:
            user.set_password(password)

        db.session.commit()
        flash(f'User "{user.name}" has been updated.', 'success')
        return redirect(url_for('admin.list_users'))

    return render_template('admin/edit_user.html', user=user)


@admin_bp.route('/users/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(id):
    user_to_delete = User.query.get_or_404(id)
    if user_to_delete.name == 'admin':
        flash('The default admin user cannot be deleted.', 'danger')
        return redirect(url_for('admin.list_users'))
        
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'User "{user_to_delete.name}" has been deleted.', 'success')
    return redirect(url_for('admin.list_users'))