from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import date, timedelta, datetime
from ..models import db, Course, User, Group, CourseAssignment, CourseCompletion, Attachment
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
import uuid
import os
from werkzeug.utils import secure_filename
from flask import current_app
from src.utils.timezone_helper import today
from ..utils.redirects import safe_redirect_target



training_bp = Blueprint('training', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'knowledge_policy'
COURSE_DETAIL = 'training.course_detail'

@training_bp.route('/', methods=['GET'])
@login_required
def my_training():
    """Shows the logged-in user their assigned courses."""
    user_id = session.get('user_id')
    user = db.session.get(User,user_id) # Directly get the user from the session

    if not user:
        flash("Could not find your user profile to display training.", "warning")
        return render_template('training/my_training.html', assignments=[])

    assignments = CourseAssignment.query.filter_by(user_id=user.id).order_by(CourseAssignment.due_date).all()
    return render_template('training/my_training.html', assignments=assignments)

@training_bp.route('/courses', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_courses():
    courses = Course.query.order_by(Course.title).all()
    return render_template('training/list_courses.html', courses=courses)

@training_bp.route('/courses/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_course():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create courses.', 'danger')
            return redirect(url_for('training.list_courses'))
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
@requires_permission(MODULE)
def course_detail(id):
    course = db.get_or_404(Course, id)
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to assign courses.', 'danger')
            return redirect(url_for(COURSE_DETAIL, id=id))
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
                due_date = today() + timedelta(days=course.completion_days)
                assignment = CourseAssignment(course_id=course.id, user_id=user.id, due_date=due_date)
                db.session.add(assignment)
                assigned_count += 1
        
        db.session.commit()
        flash(f'{assigned_count} user(s) have been assigned this training.', 'success')
        return redirect(url_for(COURSE_DETAIL, id=id))

    users = User.query.order_by(User.name).filter_by(is_archived=False).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('training/course_detail.html', course=course, users=users, groups=groups)

@training_bp.route('/completion/<int:assignment_id>/complete', methods=['POST'])
@login_required
def complete_course(assignment_id):
    assignment = db.get_or_404(CourseAssignment, assignment_id)
    notes = request.form.get('notes')
    
    completion = CourseCompletion(
        assignment_id=assignment.id,
        notes=notes
    )

    # 1. Añade y "flushea" la finalización PRIMERO para que obtenga un ID
    db.session.add(completion)
    db.session.flush()  # Esto asigna completion.id sin terminar la transacción

    # 2. Maneja la subida del archivo
    if 'certificate' in request.files:
        file = request.files['certificate']
        if file.filename != '':
            original_filename = secure_filename(file.filename)
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
            
            # 3. Crea el adjunto y enlázalo usando el ID de la finalización
            attachment = Attachment(
                filename=original_filename,
                secure_filename=unique_filename,
                linkable_id=completion.id,        # <-- Enlace correcto
                linkable_type='CourseCompletion'  # <-- Enlace correcto
            )
            db.session.add(attachment) # Añade el adjunto a la sesión

    # 4. Comete la transacción (guarda la finalización Y el adjunto)
    db.session.commit()

    flash(f'Successfully marked "{assignment.course.title}" as complete!', 'success')
    return redirect(url_for('training.my_training'))


@training_bp.route('/assignment/<int:assignment_id>/admin_complete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def admin_complete_course(assignment_id):
    if not has_write_permission(MODULE):
        assignment = db.get_or_404(CourseAssignment, assignment_id)
        flash('Write access required to mark courses as complete.', 'danger')
        return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))
    assignment = db.get_or_404(CourseAssignment, assignment_id)
    notes = request.form.get('notes')
    completion_date_str = request.form.get('completion_date')

    if not completion_date_str:
        flash('Completion date is required.', 'danger')
        return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))
    
    try:
        completion_date = datetime.strptime(completion_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format for completion date.', 'danger')
        return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))

    # Avoid creating a duplicate completion
    if assignment.completion:
        flash(f'"{assignment.course.title}" was already marked as complete for this user.', 'warning')
        return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))
    
    completion = CourseCompletion(
        assignment_id=assignment.id,
        notes=notes,
        completion_date=completion_date
    )
    db.session.add(completion)
    db.session.flush()  # Get completion.id before creating the attachment

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
                secure_filename=unique_filename,
                linkable_type='CourseCompletion',
                linkable_id=completion.id
            )
            db.session.add(attachment)

    db.session.commit()
    flash(f'Successfully marked "{assignment.course.title}" as complete for {assignment.user.name}!', 'success')
    return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))

@training_bp.route('/completion/<int:completion_id>/edit', methods=['POST'])
@login_required
@requires_permission(MODULE)
def edit_completion(completion_id):
    if not has_write_permission(MODULE):
        completion = db.get_or_404(CourseCompletion, completion_id)
        flash('Write access required to edit completion records.', 'danger')
        return redirect(url_for(COURSE_DETAIL, id=completion.assignment.course_id))
    """
    Edita una finalización de curso existente.
    """
    completion = db.get_or_404(CourseCompletion, completion_id)
    assignment = completion.assignment
    
    if not completion:
        flash('Completion record not found.', 'danger')
        return redirect(safe_redirect_target(request.referrer))

    # Actualizar campos
    completion.completion_date = datetime.strptime(request.form['completion_date'], '%Y-%m-%d').date()
    completion.notes = request.form.get('notes')

    # Gestionar subida de nuevo certificado
    if 'certificate' in request.files:
        file = request.files['certificate']
        if file.filename != '':
            # 1. Eliminar el certificado antiguo si existe
            if completion.attachments:
                old_attachment = completion.attachments[0]
                try:
                    os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'], old_attachment.secure_filename))
                except OSError as e:
                    current_app.logger.warning(f"Could not delete old certificate file: {e}")
                db.session.delete(old_attachment)
            
            # 2. Guardar el nuevo certificado
            original_filename = secure_filename(file.filename)
            file_ext = os.path.splitext(original_filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename))
            
            # 3. Crear el nuevo registro de Attachment
            new_attachment = Attachment(
                filename=original_filename,
                secure_filename=unique_filename,
                linkable_type='CourseCompletion',
                linkable_id=completion.id
            )
            db.session.add(new_attachment)

    db.session.commit()
    flash(f'Completion for "{assignment.course.title}" (User: {assignment.user.name}) has been updated.', 'success')
    return redirect(url_for(COURSE_DETAIL, id=assignment.course_id))