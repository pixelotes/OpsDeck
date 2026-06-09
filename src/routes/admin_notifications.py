"""
Admin Notifications Blueprint

Provides an admin interface for managing system notification events.
Allows admins to enable/disable notifications and change templates.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..extensions import db
from ..models.notifications import NotificationEvent
from ..models.communications import EmailTemplate
from ..services.permissions_service import requires_permission, has_write_permission
from .main import login_required

admin_notifications_bp = Blueprint('admin_notifications', __name__)


@admin_notifications_bp.route('/', methods=['GET'])
@login_required
@requires_permission('administration')
def list_events():
    """List all notification events with their current configuration."""
    events = NotificationEvent.query.order_by(NotificationEvent.name).all()
    templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    return render_template('admin/notifications.html', events=events, templates=templates)


@admin_notifications_bp.route('/<int:event_id>/toggle', methods=['POST'])
@login_required
@requires_permission('administration')
def toggle_event(event_id):
    if not has_write_permission('administration'):
        flash('Write access required to toggle notifications.', 'danger')
        return redirect(url_for('admin_notifications.list_events'))
    """Toggle a notification event on/off."""
    event = db.get_or_404(NotificationEvent, event_id)
    event.enabled = not event.enabled
    db.session.commit()
    
    status = 'enabled' if event.enabled else 'disabled'
    flash(f'Notification "{event.name}" has been {status}.', 'success')
    return redirect(url_for('admin_notifications.list_events'))


@admin_notifications_bp.route('/<int:event_id>/update', methods=['POST'])
@login_required
@requires_permission('administration')
def update_event(event_id):
    if not has_write_permission('administration'):
        flash('Write access required to update notifications.', 'danger')
        return redirect(url_for('admin_notifications.list_events'))
    """Update a notification event's template and days offset."""
    event = db.get_or_404(NotificationEvent, event_id)
    
    # Update template
    template_id = request.form.get('template_id')
    if template_id:
        event.template_id = int(template_id) if template_id != '' else None
    else:
        event.template_id = None
    
    # Update days offset
    days_offset = request.form.get('days_offset')
    if days_offset:
        try:
            event.days_offset = int(days_offset)
        except ValueError:
            flash('Invalid days offset value.', 'danger')
            return redirect(url_for('admin_notifications.list_events'))
            
    # Update channels
    channels = []
    if 'channel_email' in request.form:
        channels.append('email')
    if 'channel_slack' in request.form:
        channels.append('slack')
    if 'channel_webhook' in request.form:
        channels.append('webhook')
    event.channels = channels if channels else ['email']  # Default to email

    # Update Slack target channel
    event.slack_target_channel = request.form.get('slack_target_channel') or None

    # Update Webhook URL
    event.webhook_url = request.form.get('webhook_url') or None
    
    db.session.commit()
    flash(f'Notification "{event.name}" has been updated.', 'success')
    return redirect(url_for('admin_notifications.list_events'))
