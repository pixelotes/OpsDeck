"""
Campaign Routes

CRUD and management for mass communication campaigns.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from ..extensions import db
from ..models import User, Group
from ..models.communications import Campaign, ScheduledCommunication
from ..models.core import Tag
from ..services.permissions_service import requires_permission, has_write_permission
from ..utils.communications_context import validate_template_syntax
from .main import login_required
from src.utils.timezone_helper import now, today
from ..utils.sanitize import sanitize_email_html
from ..utils.json_api import json_endpoint


campaigns_bp = Blueprint('campaigns', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'communications'
DETAIL = 'campaigns.detail'
NEW_CAMPAIGN = 'campaigns.new_campaign'
CAMPAIGNS_FORM_HTML = 'campaigns/form.html'


# ==========================================
# CAMPAIGN CRUD
# ==========================================

@campaigns_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_campaigns():
    """List all campaigns with their status."""
    view = request.args.get('view', 'active')
    
    query = Campaign.query
    
    if view == 'archived':
        query = query.filter_by(status='archived')
    else:
        # Active view: show everything except archived
        query = query.filter(Campaign.status != 'archived')
        
    campaigns = query.order_by(Campaign.created_at.desc()).all()
    
    return render_template('campaigns/list.html', campaigns=campaigns, current_view=view)


@campaigns_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def new_campaign():
    """Create a new campaign (wizard form)."""
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create campaigns.', 'danger')
            return redirect(url_for('campaigns.list_campaigns'))
        title = request.form.get('title')
        subject = request.form.get('subject')
        # Sanitised on the way in: these bodies are rendered back into the app,
        # so script here would run in the session of whoever views them.
        body_html = sanitize_email_html(request.form.get('body_html'))
        send_to_all = request.form.get('send_to_all') == 'on'
        scheduled_at_str = request.form.get('scheduled_at')
        user_ids = request.form.getlist('user_ids')
        group_ids = request.form.getlist('group_ids')
        
        if not title or not subject or not body_html:
            flash('Title, subject, and body are required.', 'danger')
            return redirect(url_for(NEW_CAMPAIGN))
        
        # Validate Jinja2 syntax for subject
        is_valid, error = validate_template_syntax(subject)
        if not is_valid:
            flash(f'Subject template syntax error: {error}', 'danger')
            return redirect(url_for(NEW_CAMPAIGN))
        
        # Validate Jinja2 syntax for body
        is_valid, error = validate_template_syntax(body_html)
        if not is_valid:
            flash(f'Body template syntax error: {error}', 'danger')
            return redirect(url_for(NEW_CAMPAIGN))
        
        # Parse scheduled_at if provided
        scheduled_at = None
        if scheduled_at_str:
            try:
                scheduled_at = datetime.strptime(scheduled_at_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid date/time format.', 'danger')
                return redirect(url_for(NEW_CAMPAIGN))
        
        # Create campaign
        campaign = Campaign(
            title=title,
            subject=subject,
            body_html=body_html,
            send_to_all=send_to_all,
            scheduled_at=scheduled_at,
            created_by_id=session.get('user_id'),
            status='draft'
        )
        
        # Add target users
        if user_ids and not send_to_all:
            users = User.query.filter(User.id.in_([int(i) for i in user_ids])).all()
            campaign.target_users = users
        
        # Add target groups
        if group_ids and not send_to_all:
            groups = Group.query.filter(Group.id.in_([int(i) for i in group_ids])).all()
            campaign.target_groups = groups
        
        # Add tags
        tag_ids = request.form.getlist('tag_ids')
        if tag_ids:
            tags = Tag.query.filter(Tag.id.in_([int(i) for i in tag_ids])).all()
            campaign.tags = tags
        
        db.session.add(campaign)
        db.session.commit()
        
        flash(f'Campaign "{title}" created as draft.', 'success')
        return redirect(url_for(DETAIL, id=campaign.id))
    
    # GET - show form
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    return render_template(CAMPAIGNS_FORM_HTML, campaign=None, users=users, groups=groups, tags=tags)


@campaigns_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def detail(id):
    """Campaign detail/report view."""
    campaign = db.get_or_404(Campaign, id)
    
    # Get scheduled communications for this campaign
    communications = ScheduledCommunication.query.filter_by(
        target_type='campaign', target_id=id
    ).order_by(ScheduledCommunication.recipient_name).all()
    
    # If Draft and no communications yet, show preview of audience
    if campaign.status == 'draft' and not communications:
        audience = campaign.get_resolved_audience()
        # Create dummy objects for display
        for user in audience:
            communications.append({
                'recipient_name': user.name,
                'recipient_email': user.email,
                'status': 'target',  # Special status for UI
                'sent_at': None,
                'error_message': None
            })
        # Sort by name
        communications.sort(key=lambda x: x['recipient_name'])
    
    stats = campaign.get_communications_stats()
    
    return render_template('campaigns/detail.html', 
                           campaign=campaign, 
                           communications=communications,
                           stats=stats)


@campaigns_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def edit_campaign(id):
    """Edit a draft campaign."""
    campaign = db.get_or_404(Campaign, id)
    
    if campaign.status != 'draft':
        flash('Only draft campaigns can be edited.', 'warning')
        return redirect(url_for(DETAIL, id=id))
    
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update campaigns.', 'danger')
            return redirect(url_for(DETAIL, id=id))
        title = request.form.get('title')
        subject = request.form.get('subject')
        # Sanitised on the way in: these bodies are rendered back into the app,
        # so script here would run in the session of whoever views them.
        body_html = sanitize_email_html(request.form.get('body_html'))
        
        # Required field validation
        if not title or not subject or not body_html:
            flash('Title, subject, and body are required.', 'danger')
            users = User.query.filter_by(is_archived=False).order_by(User.name).all()
            groups = Group.query.order_by(Group.name).all()
            return render_template(CAMPAIGNS_FORM_HTML, campaign=campaign, users=users, groups=groups)
        
        # Validate Jinja2 syntax for subject
        is_valid, error = validate_template_syntax(subject)
        if not is_valid:
            flash(f'Subject template syntax error: {error}', 'danger')
            users = User.query.filter_by(is_archived=False).order_by(User.name).all()
            groups = Group.query.order_by(Group.name).all()
            return render_template(CAMPAIGNS_FORM_HTML, campaign=campaign, users=users, groups=groups)
        
        # Validate Jinja2 syntax for body
        is_valid, error = validate_template_syntax(body_html)
        if not is_valid:
            flash(f'Body template syntax error: {error}', 'danger')
            users = User.query.filter_by(is_archived=False).order_by(User.name).all()
            groups = Group.query.order_by(Group.name).all()
            return render_template(CAMPAIGNS_FORM_HTML, campaign=campaign, users=users, groups=groups)
        
        campaign.title = title
        campaign.subject = subject
        campaign.body_html = body_html
        campaign.send_to_all = request.form.get('send_to_all') == 'on'
        
        scheduled_at_str = request.form.get('scheduled_at')
        if scheduled_at_str:
            try:
                campaign.scheduled_at = datetime.strptime(scheduled_at_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                pass
        else:
            campaign.scheduled_at = None
        
        # Update target users
        user_ids = request.form.getlist('user_ids')
        if not campaign.send_to_all:
            users = User.query.filter(User.id.in_([int(i) for i in user_ids])).all() if user_ids else []
            campaign.target_users = users
        
        # Update target groups
        group_ids = request.form.getlist('group_ids')
        if not campaign.send_to_all:
            groups = Group.query.filter(Group.id.in_([int(i) for i in group_ids])).all() if group_ids else []
            campaign.target_groups = groups
        
        # Update tags
        tag_ids = request.form.getlist('tag_ids')
        tags = Tag.query.filter(Tag.id.in_([int(i) for i in tag_ids])).all() if tag_ids else []
        campaign.tags = tags
        
        db.session.commit()
        flash('Campaign updated.', 'success')
        return redirect(url_for(DETAIL, id=id))
    
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    tags = Tag.query.filter_by(is_archived=False).order_by(Tag.name).all()
    return render_template(CAMPAIGNS_FORM_HTML, campaign=campaign, users=users, groups=groups, tags=tags)


@campaigns_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_campaign(id):
    if not has_write_permission(MODULE):
        flash('Write access required to archive campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Archive a campaign (replaces delete).
    Only allowed from 'draft' or 'finished' states.
    """
    campaign = db.get_or_404(Campaign, id)
    
    if not campaign.can_be_archived:
        flash(f'Cannot archive campaign in "{campaign.status}" state. Cancel it first.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    
    campaign.status = 'archived'
    db.session.commit()
    
    flash(f'Campaign "{campaign.title}" archived.', 'success')
    return redirect(url_for('campaigns.list_campaigns'))


@campaigns_bp.route('/<int:id>/clone', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def clone_campaign(id):
    if not has_write_permission(MODULE):
        flash('Write access required to clone campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Clone a campaign - copies title (with -copy suffix), subject, and body.
    Does NOT copy recipients or scheduling.
    """
    original = db.get_or_404(Campaign, id)
    
    # Create new campaign with copied content
    new_campaign = Campaign(
        title=f"{original.title}-copy",
        subject=original.subject,
        body_html=original.body_html,
        send_to_all=False,  # Reset audience selection
        scheduled_at=None,  # Reset scheduling
        created_by_id=session.get('user_id'),
        status='draft'
    )
    
    db.session.add(new_campaign)
    db.session.commit()
    
    flash(f'Campaign cloned! Editing "{new_campaign.title}".', 'success')
    return redirect(url_for('campaigns.edit_campaign', id=new_campaign.id))


# ==========================================
# CAMPAIGN ACTIONS
# ==========================================

@campaigns_bp.route('/<int:id>/schedule', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def schedule_campaign(id):
    if not has_write_permission(MODULE):
        flash('Write access required to schedule campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Schedule/launch a campaign.
    This spawns individual ScheduledCommunication records for each recipient.
    """
    campaign = db.get_or_404(Campaign, id)
    
    if campaign.status != 'draft':
        flash('Campaign has already been scheduled or processed.', 'warning')
        return redirect(url_for(DETAIL, id=id))
    
    # Resolve audience
    audience = campaign.get_resolved_audience()
    
    if not audience:
        flash('No recipients found. Add users, groups, or enable "Send to All".', 'danger')
        return redirect(url_for(DETAIL, id=id))
    
    # Determine scheduled date
    if campaign.scheduled_at:
        scheduled_date = campaign.scheduled_at.date()
    else:
        scheduled_date = today()
    
    # Spawn communications
    created_count = 0
    for user in audience:
        comm = ScheduledCommunication(
            template_id=None,  # Campaign uses inline content
            target_type='campaign',
            target_id=campaign.id,
            scheduled_date=scheduled_date,
            recipient_email=user.email,
            recipient_name=user.name,
            recipient_user_id=user.id,
            recipient_type='target_user',
            status='pending'
        )
        db.session.add(comm)
        created_count += 1
    
    # Update campaign status
    campaign.status = 'scheduled'
    campaign.processed_at = now()
    
    db.session.commit()
    
    flash(f'Campaign scheduled! {created_count} emails queued for delivery.', 'success')
    return redirect(url_for(DETAIL, id=id))


@campaigns_bp.route('/<int:id>/cancel', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def cancel_campaign(id):
    if not has_write_permission(MODULE):
        flash('Write access required to cancel campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    🚨 PANIC BUTTON: Cancel all pending communications for this campaign.
    Only allowed from 'scheduled' or 'ongoing' states.
    Resets the campaign to draft status so it can be edited and re-scheduled.
    """
    campaign = db.get_or_404(Campaign, id)
    
    if not campaign.can_be_cancelled:
        flash(f'Cannot cancel campaign in "{campaign.status}" state.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    
    # Mass cancel pending communications
    cancelled_count = ScheduledCommunication.query.filter_by(
        target_type='campaign',
        target_id=id,
        status='pending'
    ).update({'status': 'cancelled'})
    
    # Reset campaign to draft status so it can be edited again
    campaign.status = 'draft'
    campaign.processed_at = None
    
    db.session.commit()
    
    if cancelled_count > 0:
        flash(f'🛑 {cancelled_count} pending emails cancelled. Campaign returned to draft.', 'warning')
    else:
        flash('Campaign returned to draft.', 'info')
    
    return redirect(url_for(DETAIL, id=id))


@campaigns_bp.route('/<int:id>/send_now', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def send_campaign_now(id):
    if not has_write_permission(MODULE):
        flash('Write access required to send campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Force immediate processing of a scheduled campaign.
    Triggers the sending of all pending communications right now.
    """
    from ..utils.communications_context import get_template_context, render_email_template
    from .. import notifications
    from flask import current_app
    
    campaign = db.get_or_404(Campaign, id)
    
    # Get pending communications
    pending = ScheduledCommunication.query.filter_by(
        target_type='campaign',
        target_id=id,
        status='pending'
    ).all()
    
    if not pending:
        flash('No pending emails to send.', 'info')
        return redirect(url_for(DETAIL, id=id))
    
    sent_count = 0
    failed_count = 0
    
    for comm in pending:
        try:
            context = get_template_context(comm)
            subject, body_html = render_email_template(campaign, context)
            
            success = notifications.send_email(
                current_app._get_current_object(),
                subject,
                body_html,
                [comm.recipient_email]
            )
            
            if success:
                comm.status = 'sent'
                comm.sent_at = now()
                sent_count += 1
            else:
                comm.status = 'failed'
                comm.error_message = 'Email sending failed'
                failed_count += 1
                
        except Exception as e:
            comm.status = 'failed'
            comm.error_message = str(e)[:500]
            failed_count += 1
    
    db.session.commit()
    
    flash(f'Sent {sent_count} emails, {failed_count} failed.', 'success' if failed_count == 0 else 'warning')
    return redirect(url_for(DETAIL, id=id))


@campaigns_bp.route('/<int:id>/retry_failed', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def retry_failed(id):
    if not has_write_permission(MODULE):
        flash('Write access required to retry campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Reset all failed communications for this campaign to pending,
    allowing them to be retried by the communications queue processor.
    """
    db.get_or_404(Campaign, id)  # 404s on an unknown campaign
    
    # Find all failed communications for this campaign
    failed_comms = ScheduledCommunication.query.filter_by(
        target_type='campaign',
        target_id=id,
        status='failed'
    ).all()
    
    if not failed_comms:
        flash('No failed emails to retry.', 'info')
        return redirect(url_for(DETAIL, id=id))
    
    retry_count = 0
    for comm in failed_comms:
        comm.status = 'pending'
        comm.retry_count = 0  # Reset retry counter for manual retry
        comm.next_retry_at = None  # Clear backoff - process immediately
        comm.error_message = None
        retry_count += 1
    
    db.session.commit()
    
    flash(f'🔄 {retry_count} failed email(s) queued for retry.', 'success')
    return redirect(url_for(DETAIL, id=id))


@campaigns_bp.route('/<int:id>/finish', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def finish_campaign(id):
    if not has_write_permission(MODULE):
        flash('Write access required to finish campaigns.', 'danger')
        return redirect(url_for(DETAIL, id=id))
    """
    Manually finish an ongoing campaign.
    Marks campaign as 'finished' and stops any further retry attempts.
    """
    campaign = db.get_or_404(Campaign, id)
    
    if campaign.status != 'ongoing':
        flash(f'Cannot finish campaign in "{campaign.status}" state.', 'warning')
        return redirect(url_for(DETAIL, id=id))
    
    # Mark for finish - any pending retry attempts will be ignored by status check
    campaign.status = 'finished'
    db.session.commit()
    
    flash('Campaign marked as finished.', 'success')
    return redirect(url_for(DETAIL, id=id))


@campaigns_bp.route('/<int:id>/stats', methods=['GET'])
@json_endpoint
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def get_stats(id):
    """
    API endpoint returning campaign stats and communications as JSON.
    Used for AJAX auto-refresh of the campaign detail page.
    Also calls update_auto_status to handle state transitions.
    """
    from flask import jsonify
    
    campaign = db.get_or_404(Campaign, id)
    
    # Update status based on progress (scheduled->ongoing->finished)
    if campaign.update_auto_status():
        db.session.commit()
    
    # Get stats
    stats = campaign.get_communications_stats()
    
    # Get communications list
    communications = ScheduledCommunication.query.filter_by(
        target_type='campaign', target_id=id
    ).order_by(ScheduledCommunication.recipient_name).all()
    
    comms_data = []
    for comm in communications:
        comms_data.append({
            'id': comm.id,
            'recipient_name': comm.recipient_name or 'Unknown',
            'recipient_email': comm.recipient_email,
            'status': comm.status,
            'sent_at': comm.sent_at.strftime('%d %b %H:%M') if comm.sent_at else None,
            'error_message': comm.error_message,
            'retry_count': comm.retry_count
        })
    
    return jsonify({
        'stats': stats,
        'communications': comms_data,
        'campaign_status': campaign.status
    })

