"""
Notification Event Configuration Model

Maps system events (like license expiry, subscription renewal) to email templates,
allowing admins to configure which notifications are enabled and which templates to use.
"""
from datetime import datetime
from src.utils.timezone_helper import now
from ..extensions import db


class NotificationEvent(db.Model):
    """
    Maps system events to email templates for centralized notification management.
    Allows admins to enable/disable specific notifications and change templates.
    Supports multiple delivery channels (email, slack).
    """
    __tablename__ = 'notification_event'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Event identification
    event_code = db.Column(db.String(50), unique=True, nullable=False)  # e.g., 'LICENSE_EXPIRING'
    name = db.Column(db.String(100), nullable=False)  # Human-readable name
    description = db.Column(db.Text)  # Explanation of when this event triggers
    
    # Link to the email template to use
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    template = db.relationship('EmailTemplate', backref='notification_events')
    
    # Control switches
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    
    # Optional: days before event to trigger (for expiry-type events)
    # Positive = days before, e.g., 7 means "7 days before expiry"
    days_offset = db.Column(db.Integer, default=7)
    
    # Multi-channel delivery configuration
    # JSON array of channels: ["email"], ["slack"], or ["email", "slack"]
    channels = db.Column(db.JSON, default=lambda: ["email"])
    
    # Optional: Fixed Slack channel ID for broadcast notifications (e.g., "C12345" for #devops)
    # If empty/null, DM will be sent to the user resolved by email
    slack_target_channel = db.Column(db.String(50), nullable=True)
    
    # Webhook URL for automated integrations (POST requests with JSON payload)
    webhook_url = db.Column(db.String(500), nullable=True)

    # Discord incoming-webhook URL (POST {"content": "..."}); Discord replies 204 on success
    discord_webhook_url = db.Column(db.String(500), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    
    def __repr__(self):
        return f'<NotificationEvent {self.event_code}>'

