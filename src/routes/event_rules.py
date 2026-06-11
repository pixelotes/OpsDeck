"""
Event Rules Blueprint

Admin interface for the event engine: rules that match committed entity changes
(captured in AuditLog) and fire notifications through the communications queue.
Lives under the Settings module.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..extensions import db
from ..models.event_rules import EventRule, ENTITY_CATALOG, EVENT_ACTIONS, RECIPIENT_MODES
from ..models.communications import EmailTemplate
from ..models.auth import User
from ..services.permissions_service import requires_permission, has_write_permission
from .main import login_required

event_rules_bp = Blueprint('event_rules', __name__)

MODULE = 'settings'
LIST_RULES = 'event_rules.list_rules'
MSG_WRITE_REQUIRED = 'Write access required to manage event rules.'


def _channels_from_form(form):
    """Read channel checkboxes (channel_<key>) into a list, defaulting to email."""
    channels = [key for key in ('email', 'slack', 'webhook', 'discord')
                if f'channel_{key}' in form]
    return channels if channels else ['email']


def _apply_form(rule, form):
    """Populate an EventRule from submitted form data."""
    rule.name = form.get('name', '').strip()
    rule.description = form.get('description') or None
    rule.entity_type = form.get('entity_type')
    rule.action = form.get('action') or 'any'
    rule.recipient_mode = form.get('recipient_mode') or 'admins'
    rule.recipient_emails = form.get('recipient_emails') or None
    rule.recipient_role = form.get('recipient_role') or None
    template_id = form.get('template_id')
    rule.template_id = int(template_id) if template_id else None
    rule.channels = _channels_from_form(form)
    rule.slack_target_channel = form.get('slack_target_channel') or None
    rule.webhook_url = form.get('webhook_url') or None
    rule.discord_webhook_url = form.get('discord_webhook_url') or None


def _validation_error(rule):
    """Return a user-facing error string if the rule is invalid, else None."""
    if not rule.name or not rule.entity_type:
        return 'Name and entity type are required.'
    # The Slack channel field is a channel ID (e.g. C12345) used with the bot
    # token, not a webhook URL — guard against the common mistake and the
    # varchar(50) overflow it would cause.
    sc = rule.slack_target_channel
    if sc and ('://' in sc or len(sc) > 50):
        return ('Slack Channel ID must be a short channel ID like "C12345" '
                '(or left empty to DM the recipient) — not a URL.')
    return None


@event_rules_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_rules():
    rules = EventRule.query.order_by(EventRule.entity_type, EventRule.name).all()
    templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    roles = sorted({u.role for u in User.query.with_entities(User.role).distinct() if u.role})
    return render_template(
        'admin/event_rules.html',
        rules=rules,
        templates=templates,
        entity_catalog=ENTITY_CATALOG,
        actions=EVENT_ACTIONS,
        recipient_modes=RECIPIENT_MODES,
        roles=roles,
    )


@event_rules_bp.route('/create', methods=['POST'])
@login_required
@requires_permission(MODULE)
def create_rule():
    if not has_write_permission(MODULE):
        flash(MSG_WRITE_REQUIRED, 'danger')
        return redirect(url_for(LIST_RULES))

    rule = EventRule()
    _apply_form(rule, request.form)
    error = _validation_error(rule)
    if error:
        flash(error, 'danger')
        return redirect(url_for(LIST_RULES))
    db.session.add(rule)
    db.session.commit()
    flash(f'Event rule "{rule.name}" created.', 'success')
    return redirect(url_for(LIST_RULES))


@event_rules_bp.route('/<int:rule_id>/update', methods=['POST'])
@login_required
@requires_permission(MODULE)
def update_rule(rule_id):
    if not has_write_permission(MODULE):
        flash(MSG_WRITE_REQUIRED, 'danger')
        return redirect(url_for(LIST_RULES))

    rule = db.get_or_404(EventRule, rule_id)
    _apply_form(rule, request.form)
    error = _validation_error(rule)
    if error:
        db.session.rollback()
        flash(error, 'danger')
        return redirect(url_for(LIST_RULES))
    db.session.commit()
    flash(f'Event rule "{rule.name}" updated.', 'success')
    return redirect(url_for(LIST_RULES))


@event_rules_bp.route('/<int:rule_id>/toggle', methods=['POST'])
@login_required
@requires_permission(MODULE)
def toggle_rule(rule_id):
    if not has_write_permission(MODULE):
        flash(MSG_WRITE_REQUIRED, 'danger')
        return redirect(url_for(LIST_RULES))

    rule = db.get_or_404(EventRule, rule_id)
    rule.enabled = not rule.enabled
    db.session.commit()
    flash(f'Event rule "{rule.name}" {"enabled" if rule.enabled else "disabled"}.', 'success')
    return redirect(url_for(LIST_RULES))


@event_rules_bp.route('/<int:rule_id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE)
def delete_rule(rule_id):
    if not has_write_permission(MODULE):
        flash(MSG_WRITE_REQUIRED, 'danger')
        return redirect(url_for(LIST_RULES))

    rule = db.get_or_404(EventRule, rule_id)
    name = rule.name
    db.session.delete(rule)
    db.session.commit()
    flash(f'Event rule "{name}" deleted.', 'success')
    return redirect(url_for(LIST_RULES))
