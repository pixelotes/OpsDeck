from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, User
from .main import login_required

users_bp = Blueprint('users', __name__)

@users_bp.route('/')
@login_required
def users():
    users = User.query.filter_by(is_archived=False).all()
    return render_template('users/list.html', users=users)

@users_bp.route('/archived')
@login_required
def archived_users():
    users = User.query.filter_by(is_archived=True).all()
    return render_template('users/archived.html', users=users)


@users_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_user(id):
    user = User.query.get_or_404(id)
    user.is_archived = True
    db.session.commit()
    flash(f'User "{user.name}" has been archived.')
    return redirect(url_for('users.users'))


@users_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_user(id):
    user = User.query.get_or_404(id)
    user.is_archived = False
    db.session.commit()
    flash(f'User "{user.name}" has been restored.')
    return redirect(url_for('users.archived_users'))

@users_bp.route('/<int:id>')
@login_required
def user_detail(id):
    user = User.query.get_or_404(id)
    return render_template('users/detail.html', user=user)

@users_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_user():
    if request.method == 'POST':
        user = User(
            name=request.form['name'],
            email=request.form.get('email'),
            department=request.form.get('department'),
            job_title=request.form.get('job_title')
        )
        db.session.add(user)
        db.session.commit()
        flash('User created successfully!')
        return redirect(url_for('users.users'))

    return render_template('users/form.html')

@users_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(id):
    user = User.query.get_or_404(id)

    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form.get('email')
        user.department = request.form.get('department')
        user.job_title = request.form.get('job_title')
        db.session.commit()
        flash('User updated successfully!')
        return redirect(url_for('users.users'))

    return render_template('users/form.html', user=user)