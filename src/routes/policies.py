from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import date, datetime
from ..models import db, Policy, PolicyVersion, User, Group, PolicyAcknowledgement, AppUser
from .main import login_required
from .admin import admin_required

policies_bp = Blueprint('policies', __name__)

@policies_bp.route('/')
@login_required
def list_policies():
    policies = Policy.query.order_by(Policy.title).all()
    return render_template('policies/list.html', policies=policies)

@policies_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_policy():
    if request.method == 'POST':
        policy = Policy(
            title=request.form['title'],
            category=request.form.get('category'),
            description=request.form.get('description'),
            link=request.form.get('link')
        )
        db.session.add(policy)
        db.session.commit()
        
        # Create the initial version
        version = PolicyVersion(
            policy_id=policy.id,
            version_number='1.0',
            status='Draft',
            content=request.form['content'],
            effective_date=date.today()
        )
        
        # Assign users and groups
        user_ids = request.form.getlist('user_ids')
        group_ids = request.form.getlist('group_ids')
        version.users_to_acknowledge = User.query.filter(User.id.in_(user_ids)).all()
        version.groups_to_acknowledge = Group.query.filter(Group.id.in_(group_ids)).all()

        db.session.add(version)
        db.session.commit()
        flash('Policy and its initial version have been created.', 'success')
        return redirect(url_for('policies.detail', id=policy.id))

    users = User.query.order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('policies/form.html', users=users, groups=groups)

@policies_bp.route('/<int:id>')
@login_required
def detail(id):
    policy = Policy.query.get_or_404(id)
    users = User.query.order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('policies/detail.html', policy=policy, users=users, groups=groups)

@policies_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_policy(id):
    policy = Policy.query.get_or_404(id)
    latest_version = PolicyVersion.query.filter_by(policy_id=id).order_by(PolicyVersion.effective_date.desc()).first()

    if request.method == 'POST':
        policy.title = request.form['title']
        policy.category = request.form.get('category')
        policy.description = request.form.get('description')
        policy.link = request.form.get('link')
        
        if latest_version:
            user_ids = request.form.getlist('user_ids')
            group_ids = request.form.getlist('group_ids')
            latest_version.users_to_acknowledge = User.query.filter(User.id.in_(user_ids)).all()
            latest_version.groups_to_acknowledge = Group.query.filter(Group.id.in_(group_ids)).all()

        db.session.commit()
        flash('Policy details have been updated.', 'success')
        return redirect(url_for('policies.detail', id=policy.id))
    
    users = User.query.order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('policies/edit_policy.html', policy=policy, users=users, groups=groups, latest_version=latest_version)


@policies_bp.route('/<int:id>/new_version', methods=['GET', 'POST'])
@login_required
@admin_required
def new_version(id):
    policy = Policy.query.get_or_404(id)
    if request.method == 'POST':
        content = request.form['content']
        
        if not content or not content.strip():
            flash('Policy content cannot be empty.', 'danger')
            return render_template('policies/version_form.html', policy=policy)

        version = PolicyVersion(
            policy_id=id,
            version_number=request.form['version_number'],
            status='Draft',
            content=content,
            effective_date=datetime.strptime(request.form['effective_date'], '%Y-%m-%d').date()
        )
        db.session.add(version)
        db.session.commit()
        flash(f'New version "{version.version_number}" has been created.', 'success')
        return redirect(url_for('policies.detail', id=id))
        
    users = User.query.order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('policies/version_form.html', policy=policy, users=users, groups=groups)

@policies_bp.route('/version/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_version(id):
    version = PolicyVersion.query.get_or_404(id)
    policy = version.policy
    if request.method == 'POST':
        content = request.form['content']

        if not content or not content.strip():
            flash('Policy content cannot be empty.', 'danger')
            return render_template('policies/version_form.html', policy=policy, version=version)
            
        version.version_number = request.form['version_number']
        version.effective_date = datetime.strptime(request.form['effective_date'], '%Y-%m-%d').date()
        version.content = content
        
        # Handle user and group assignments
        user_ids = request.form.getlist('user_ids')
        group_ids = request.form.getlist('group_ids')
        version.users_to_acknowledge = User.query.filter(User.id.in_(user_ids)).all()
        version.groups_to_acknowledge = Group.query.filter(Group.id.in_(group_ids)).all()

        db.session.commit()
        flash(f'Version "{version.version_number}" has been updated.', 'success')
        return redirect(url_for('policies.detail', id=policy.id))
    
    users = User.query.order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('policies/version_form.html', policy=policy, version=version, users=users, groups=groups)

@policies_bp.route('/version/<int:id>/activate', methods=['POST'])
@login_required
@admin_required
def activate_version(id):
    version_to_activate = PolicyVersion.query.get_or_404(id)
    policy = version_to_activate.policy

    # Deactivate all other versions for this policy
    for version in policy.versions:
        if version.status == 'Active':
            version.status = 'Archived'
            version.end_date = date.today()

    # Activate the new one
    version_to_activate.status = 'Active'
    version_to_activate.end_date = None
    
    db.session.commit()
    flash(f'Version "{version_to_activate.version_number}" is now active.', 'success')
    return redirect(url_for('policies.detail', id=policy.id))

@policies_bp.route('/version/<int:id>')
@login_required
def view_version(id):
    version = PolicyVersion.query.get_or_404(id)
    return render_template('policies/view_version.html', version=version)

@policies_bp.route('/version/<int:id>/acknowledge', methods=['POST'])
@login_required
def acknowledge_version(id):
    version = PolicyVersion.query.get_or_404(id)
    user_id = session.get('user_id')
    
    app_user = AppUser.query.get(user_id)
    user = User.query.filter_by(name=app_user.username).first()

    if not user:
        flash('Could not find a matching business user to log acknowledgement.', 'danger')
        return redirect(url_for('policies.view_version', id=id))

    existing = PolicyAcknowledgement.query.filter_by(policy_version_id=id, user_id=user.id).first()
    if not existing:
        ack = PolicyAcknowledgement(policy_version_id=id, user_id=user.id)
        db.session.add(ack)
        db.session.commit()
        flash(f'You have successfully acknowledged version {version.version_number} of this policy.', 'success')
    else:
        flash('You have already acknowledged this policy version.', 'info')
        
    return redirect(url_for('policies.view_version', id=id))

@policies_bp.route('/policy/<int:policy_id>/remove_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def remove_user_from_policy(policy_id, user_id):
    policy = Policy.query.get_or_404(policy_id)
    latest_version = PolicyVersion.query.filter_by(policy_id=policy_id).order_by(PolicyVersion.effective_date.desc()).first()
    if latest_version:
        user = User.query.get_or_404(user_id)
        if user in latest_version.users_to_acknowledge:
            latest_version.users_to_acknowledge.remove(user)
            db.session.commit()
            flash(f'User "{user.name}" removed from policy.', 'success')
    return redirect(url_for('policies.detail', id=policy_id))

@policies_bp.route('/policy/<int:policy_id>/remove_group/<int:group_id>', methods=['POST'])
@login_required
@admin_required
def remove_group_from_policy(policy_id, group_id):
    policy = Policy.query.get_or_404(policy_id)
    latest_version = PolicyVersion.query.filter_by(policy_id=policy_id).order_by(PolicyVersion.effective_date.desc()).first()
    if latest_version:
        group = Group.query.get_or_404(group_id)
        if group in latest_version.groups_to_acknowledge:
            latest_version.groups_to_acknowledge.remove(group)
            db.session.commit()
            flash(f'Group "{group.name}" removed from policy.', 'success')
    return redirect(url_for('policies.detail', id=policy_id))