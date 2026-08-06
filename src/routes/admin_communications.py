"""
Admin Communications Routes

CRUD operations for EmailTemplates and PackCommunication management.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import current_user
from ..extensions import db
from ..models.communications import EmailTemplate
from ..services.permissions_service import requires_permission, has_write_permission
from .. import notifications
from ..utils.communications_context import validate_template_syntax, render_email_template
from .main import login_required
from src.utils.timezone_helper import today
from ..utils.sanitize import sanitize_email_html
from ..utils.json_api import json_endpoint


admin_communications_bp = Blueprint('admin_communications', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'hr_people'
LIST_TEMPLATES = 'admin_communications.list_templates'
ADMIN_EMAIL_TEMPLATE_FORM_HTML = 'admin/email_template_form.html'


# ==========================================
# EMAIL TEMPLATE CRUD
# ==========================================

@admin_communications_bp.route('/templates', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_templates():
    """List all email templates."""
    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    return render_template('admin/email_templates_list.html', templates=templates)


@admin_communications_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def new_template():
    """Create a new email template."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create templates.', 'danger')
            return redirect(url_for(LIST_TEMPLATES))
        name = request.form.get('name')
        subject = request.form.get('subject')
        # Sanitised on the way in: these bodies are rendered back into the app,
        # so script here would run in the session of whoever views them.
        body_html = sanitize_email_html(request.form.get('body_html'))
        category = request.form.get('category', 'general')
        
        if not name or not subject or not body_html:
            flash('Name, subject, and body are required.', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=None)
        
        # Validate Jinja2 syntax before saving
        is_valid, error = validate_template_syntax(body_html)
        if not is_valid:
            flash(f'Template syntax error: {error}', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=None)
        
        # Check for duplicate name
        if EmailTemplate.query.filter_by(name=name).first():
            flash(f'A template named "{name}" already exists.', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=None)
        
        template = EmailTemplate(
            name=name,
            subject=subject,
            body_html=body_html,
            category=category
        )
        db.session.add(template)
        db.session.commit()
        
        flash(f'Email template "{name}" created successfully.', 'success')
        return redirect(url_for(LIST_TEMPLATES))
    
    return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=None)


@admin_communications_bp.route('/templates/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE)
def edit_template(id):
    """Edit an existing email template."""
    template = db.get_or_404(EmailTemplate, id)

    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update templates.', 'danger')
            return redirect(url_for('admin_communications.edit_template', id=id))
        name = request.form.get('name')
        subject = request.form.get('subject')
        # Sanitised on the way in: these bodies are rendered back into the app,
        # so script here would run in the session of whoever views them.
        body_html = sanitize_email_html(request.form.get('body_html'))
        category = request.form.get('category', 'general')
        is_active = request.form.get('is_active') == 'on'
        
        if not name or not subject or not body_html:
            flash('Name, subject, and body are required.', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=template)
        
        # Validate Jinja2 syntax before saving
        is_valid, error = validate_template_syntax(body_html)
        if not is_valid:
            flash(f'Template syntax error: {error}', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=template)
        
        # Check if system template (prevent updates)
        if template.is_system:
            flash(f'Cannot edit system template "{template.name}".', 'danger')
            return redirect(url_for(LIST_TEMPLATES))
        
        # Check for duplicate name (excluding current template)
        existing = EmailTemplate.query.filter_by(name=name).first()
        if existing and existing.id != id:
            flash(f'A template named "{name}" already exists.', 'danger')
            return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=template)
        
        template.name = name
        template.subject = subject
        template.body_html = body_html
        template.category = category
        template.is_active = is_active
        
        db.session.commit()
        
        flash(f'Email template "{name}" updated successfully.', 'success')
        return redirect(url_for(LIST_TEMPLATES))
    
    return render_template(ADMIN_EMAIL_TEMPLATE_FORM_HTML, template=template)


@admin_communications_bp.route('/templates/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_template(id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete templates.', 'danger')
        return redirect(url_for(LIST_TEMPLATES))
    """Delete an email template."""
    template = db.get_or_404(EmailTemplate, id)

    # Check if system template

    if template.is_system:
        flash(f'Cannot delete system template "{template.name}".', 'danger')
        return redirect(url_for(LIST_TEMPLATES))

    # Check if template is used in any pack communications
    if template.pack_communications:
        flash(f'Cannot delete template "{template.name}" - it is used in {len(template.pack_communications)} pack communication(s).', 'danger')
        return redirect(url_for(LIST_TEMPLATES))
    
    # Check if template is used in any scheduled communications
    if template.scheduled_communications:
        flash(f'Cannot delete template "{template.name}" - it is used in {len(template.scheduled_communications)} scheduled communication(s).', 'danger')
        return redirect(url_for(LIST_TEMPLATES))
    
    name = template.name
    db.session.delete(template)
    db.session.commit()
    
    flash(f'Email template "{name}" deleted.', 'success')
    return redirect(url_for(LIST_TEMPLATES))


@admin_communications_bp.route('/templates/<int:id>/toggle', methods=['POST'])
@login_required
@requires_permission(MODULE)
def toggle_template(id):
    if not has_write_permission(MODULE):
        flash('Write access required to toggle templates.', 'danger')
        return redirect(url_for(LIST_TEMPLATES))
    """Toggle template active status."""
    template = db.get_or_404(EmailTemplate, id)

    # Check if system template

    if template.is_system:
        flash(f'Cannot deactivate system template "{template.name}".', 'danger')
        return redirect(url_for(LIST_TEMPLATES))

    template.is_active = not template.is_active
    db.session.commit()
    
    status = 'activated' if template.is_active else 'deactivated'
    flash(f'Email template "{template.name}" {status}.', 'info')
    return redirect(url_for(LIST_TEMPLATES))


@admin_communications_bp.route('/templates/<int:id>/test-send', methods=['POST'])
@json_endpoint
@login_required
@requires_permission(MODULE)
def test_send_template(id):
    if not has_write_permission(MODULE):
        return jsonify({'success': False, 'message': 'Write access required to send test emails.'}), 403
    """Send a test email to the current admin user with dummy data."""
    template = db.get_or_404(EmailTemplate, id)

    # Get recipient email from request or fallback to current user
    recipient_email = None
    if request.is_json:
        recipient_email = request.json.get('email')
    
    if not recipient_email and current_user.email:
        recipient_email = current_user.email
        
    if not recipient_email:
        return jsonify({'success': False, 'message': 'No recipient email provided.'}), 400
    
    # Build dummy context for test rendering
    dummy_context = {
        'user': {
            'name': 'John Doe',
            'email': recipient_email,
            'job_title': 'Software Engineer'
        },
        'manager': {
            'name': 'Jane Smith',
            'email': 'jane.smith@example.com'
        },
        'buddy': {
            'name': 'Bob Wilson',
            'email': 'bob.wilson@example.com'
        },
        'new_hire_name': 'John Doe',
        'start_date': today(),
        'departure_date': today(),
        'today': today(),
        'pack': type('Pack', (), {'name': 'Sample Pack', 'description': 'Test pack description'})(),
    }
    
    try:
        subject, body_html = render_email_template(template, dummy_context)
        
        success = notifications.send_email(
            current_app,
            f"[TEST] {subject}",
            body_html,
            [recipient_email]
        )
        
        if success:
            return jsonify({'success': True, 'message': f'Test email sent to {recipient_email}'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send email. Check SMTP configuration.'}), 500
        
        if success:
            return jsonify({'success': True, 'message': f'Test email sent to {current_user.email}'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send email. Check SMTP configuration.'}), 500
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400

