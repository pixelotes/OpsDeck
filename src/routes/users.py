import os
import uuid
from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from ..models import db, User, Attachment
from .main import login_required
from weasyprint import HTML

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

@users_bp.route('/<int:id>/inventory/generate', methods=['POST'])
@login_required
def generate_inventory(id):
    """
    Genera un snapshot en PDF del inventario del usuario y lo guarda
    como un adjunto enlazado a ese usuario.
    """
    user = User.query.get_or_404(id)
    
    # 1. Renderizar la plantilla HTML específica para el PDF
    html_content = render_template(
        'users/inventory_pdf.html', 
        user=user,
        generated_at=datetime.now()
    )
    
    # 2. Generar los bytes del PDF en memoria
    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
    except Exception as e:
        current_app.logger.error(f"Error al generar PDF con WeasyPrint: {e}")
        flash('Error al generar el PDF. Revisa los logs.', 'danger')
        return redirect(url_for('users.user_detail', id=id))

    # 3. Definir nombres de archivo
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M')
    original_filename = f"Inventory_{user.name.replace(' ', '_')}_{timestamp}.pdf"
    secure_filename_to_save = f"{uuid.uuid4().hex}.pdf"
    
    # 4. Guardar el archivo físico
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], secure_filename_to_save)
    
    try:
        with open(save_path, 'wb') as f:
            f.write(pdf_bytes)
    except OSError as e:
        current_app.logger.error(f"Error al guardar archivo PDF: {e}")
        flash('Error al guardar el archivo de inventario.', 'danger')
        return redirect(url_for('users.user_detail', id=id))

    # 5. Crear el registro 'Attachment' en la BD
    attachment = Attachment(
        filename=original_filename,
        secure_filename=secure_filename_to_save,
        linkable_type='User',
        linkable_id=user.id
    )
    
    db.session.add(attachment)
    db.session.commit()
    
    flash('Snapshot de inventario generado y guardado.', 'success')
    return redirect(url_for('users.user_detail', id=id))