from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import date, timedelta, datetime
from ..models import db, Course, User, Group, CourseAssignment, CourseCompletion, Attachment
from .main import login_required
from .admin import admin_required
import uuid
import os
from werkzeug.utils import secure_filename
from flask import current_app


training_bp = Blueprint('training', __name__)

@training_bp.route('/')
@login_required
def my_training():
    """Shows the logged-in user their assigned courses."""
    user_id = session.get('user_id')
    user = User.query.get(user_id) # Directly get the user from the session

    if not user:
        flash("Could not find your user profile to display training.", "warning")
        return render_template('training/my_training.html', assignments=[])

    assignments = CourseAssignment.query.filter_by(user_id=user.id).order_by(CourseAssignment.due_date).all()
    return render_template('training/my_training.html', assignments=assignments)

@training_bp.route('/courses')
@login_required
@admin_required
def list_courses():
    courses = Course.query.order_by(Course.title).all()
    return render_template('training/list_courses.html', courses=courses)

@training_bp.route('/courses/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_course():
    if request.method == 'POST':
        course = Course(
            title=request.form['title'],
            description=request.form.get('description'),
            link=request.form.get('link'),
            completion_days=int(request.form.get('completion_days', 30))
        )
        db.session.add(course)
        db.session.commit()
        flash('Course created successfully.', 'success')
        return redirect(url_for('training.list_courses'))
    return render_template('training/course_form.html')

@training_bp.route('/courses/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def course_detail(id):
    course = Course.query.get_or_404(id)
    if request.method == 'POST':
        user_ids = request.form.getlist('user_ids')
        group_ids = request.form.getlist('group_ids')
        
        users_to_assign = set(User.query.filter(User.id.in_(user_ids)).filter_by(is_archived=False).all())
        groups = Group.query.filter(Group.id.in_(group_ids)).all()
        for group in groups:
            users_to_assign.update(group.users)

        assigned_count = 0
        for user in users_to_assign:
            # Check if user is already assigned
            existing = CourseAssignment.query.filter_by(course_id=course.id, user_id=user.id).first()
            if not existing:
                due_date = date.today() + timedelta(days=course.completion_days)
                assignment = CourseAssignment(course_id=course.id, user_id=user.id, due_date=due_date)
                db.session.add(assignment)
                assigned_count += 1
        
        db.session.commit()
        flash(f'{assigned_count} user(s) have been assigned this training.', 'success')
        return redirect(url_for('training.course_detail', id=id))

    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('training/course_detail.html', course=course, users=users, groups=groups)

@training_bp.route('/completion/<int:assignment_id>/complete', methods=['POST'])
@login_required
def complete_course(assignment_id):
    assignment = CourseAssignment.query.get_or_404(assignment_id)
    notes = request.form.get('notes')
    
    completion = CourseCompletion(
        assignment_id=assignment.id,
        notes=notes
    )

    # Handle file upload for certificate
    if 'certificate' in request.files:
        file = request.files['certificate']
        if file.filename != '':
            original_filename = secure_filename(file.filename)
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
            
            attachment = Attachment(
                filename=original_filename,
                secure_filename=unique_filename
            )
            completion.attachment = attachment

    db.session.add(completion)
    db.session.commit()
    flash(f'Successfully marked "{assignment.course.title}" as complete!', 'success')
    return redirect(url_for('training.my_training'))


@training_bp.route('/assignment/<int:assignment_id>/admin_complete', methods=['POST'])
@login_required
@admin_required
def admin_complete_course(assignment_id):
    assignment = CourseAssignment.query.get_or_404(assignment_id)
    notes = request.form.get('notes')
    completion_date_str = request.form.get('completion_date')

    if not completion_date_str:
        flash('Completion date is required.', 'danger')
        return redirect(url_for('training.course_detail', id=assignment.course_id))
    
    try:
        completion_date = datetime.strptime(completion_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format for completion date.', 'danger')
        return redirect(url_for('training.course_detail', id=assignment.course_id))

    # Avoid creating a duplicate completion
    if assignment.completion:
        flash(f'"{assignment.course.title}" was already marked as complete for this user.', 'warning')
        return redirect(url_for('training.course_detail', id=assignment.course_id))
    
    completion = CourseCompletion(
        assignment_id=assignment.id,
        notes=notes,
        completion_date=completion_date
    )

    # Handle file upload for certificate
    if 'certificate' in request.files:
        file = request.files['certificate']
        if file.filename != '':
            original_filename = secure_filename(file.filename)
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
            
            attachment = Attachment(
                filename=original_filename,
                secure_filename=unique_filename
            )
            completion.attachment = attachment

    db.session.add(completion)
    db.session.commit()
    flash(f'Successfully marked "{assignment.course.title}" as complete for {assignment.user.name}!', 'success')
    return redirect(url_for('training.course_detail', id=assignment.course_id))