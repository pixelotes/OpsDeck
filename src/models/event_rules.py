"""
Event Rule model — the configurable layer of the event engine.

An EventRule is a NotificationEvent with the *event itself* parameterised: instead
of a hardcoded event_code triggered by a polling job, a rule matches committed
database changes (captured in AuditLog) by entity type and action, and enqueues a
ScheduledCommunication through the existing delivery queue.

See ``src/services/event_engine.py`` for the evaluator that consumes AuditLog rows
and applies these rules.
"""
from src.utils.timezone_helper import now
from ..extensions import db


# Curated catalogue of "eventable" domain entities exposed in the rule UI.
# Keys are the SQLAlchemy class names recorded by the audit listener
# (AuditLog.entity_type); values are human-readable labels for the dropdown.
# Deliberately excludes join tables, settings and internal models to avoid noise.
# The UI sorts these by label; insertion order here does not matter.
# '*' is a wildcard matching every entity type — useful for a single rule that
# fires on, say, all deletions ({{ entity }}/{{ entity_type }} name the record).
ENTITY_CATALOG = {
    '*': 'All entities',
    'Asset': 'Asset',
    'Peripheral': 'Peripheral',
    'License': 'License',
    'Subscription': 'Subscription',
    'Credential': 'Credential',
    'Certificate': 'Certificate',
    'Supplier': 'Supplier',
    'Contract': 'Contract',
    'Risk': 'Risk',
    'Incident': 'Incident',
    'ComplianceRule': 'Compliance Rule',
    'Change': 'Change',
    'Request': 'Request',
    'Candidate': 'Candidate',
    'Policy': 'Policy',
    'User': 'User',
    'Group': 'Group',
    'Permission': 'Permission (access grant)',
}

# Maps entity_type -> detail-page path prefix (the detail route is /<prefix>/<id>).
# Used to build {{ event_url }} in event notifications. Entities without a clean
# detail page are omitted (no event_url is produced for them).
ENTITY_DETAIL_PATHS = {
    'Asset': '/assets',
    'Peripheral': '/peripherals',
    'Subscription': '/subscriptions',
    'Credential': '/credentials',
    'Certificate': '/certificates',
    'Contract': '/contracts',
    'Supplier': '/suppliers',
    'Request': '/requests',
    'Change': '/changes',
    'Risk': '/risk',
    'Candidate': '/hiring/candidate',
    'User': '/users',
    'Group': '/groups',
}

# Actions a rule can match. 'any' matches create/update/delete.
EVENT_ACTIONS = ['create', 'update', 'delete', 'any']

# How recipients are resolved (v1: static only).
RECIPIENT_MODES = ['emails', 'role', 'admins']


class EventRule(db.Model):
    """Maps a committed entity change (entity_type + action) to a notification."""
    __tablename__ = 'event_rule'

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Trigger (v1: entity_type + action only)
    entity_type = db.Column(db.String(100), nullable=False, index=True)  # AuditLog.entity_type
    action = db.Column(db.String(10), nullable=False, default='any')     # create/update/delete/any

    # Recipients (v1: static)
    recipient_mode = db.Column(db.String(20), nullable=False, default='admins')  # emails/role/admins
    recipient_emails = db.Column(db.Text, nullable=True)   # comma-separated, when mode='emails'
    recipient_role = db.Column(db.String(50), nullable=True)  # role slug, when mode='role'

    # Message
    template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=True)
    template = db.relationship('EmailTemplate')

    # Delivery channels (mirrors NotificationEvent; destination config lives per-rule)
    channels = db.Column(db.JSON, default=lambda: ["email"])
    slack_target_channel = db.Column(db.String(50), nullable=True)   # bot-API channel ID (C12345)
    slack_webhook_url = db.Column(db.String(500), nullable=True)     # incoming webhook (takes precedence)
    webhook_url = db.Column(db.String(500), nullable=True)
    discord_webhook_url = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    def __repr__(self):
        return f'<EventRule {self.entity_type}/{self.action} -> {self.name}>'

    def matches(self, entity_type, action):
        """True if this rule should fire for the given audit entry."""
        if not self.enabled:
            return False
        if self.entity_type != '*' and self.entity_type != entity_type:
            return False
        return self.action == 'any' or self.action == action
