"""
Audit Log model for tracking all database changes.
"""
from ..extensions import db
from src.utils.timezone_helper import now


class AuditLog(db.Model):
    """
    Tracks all database changes (INSERT, UPDATE, DELETE) automatically.

    This model is populated by SQLAlchemy session events and should not be
    modified directly in application code.
    """
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: now(), index=True)

    # Who made the change
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    user_email = db.Column(db.String(255), nullable=True)  # Denormalized for fast queries
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6

    # What was changed
    action = db.Column(db.String(10), nullable=False, index=True)  # 'create', 'update', 'delete'
    entity_type = db.Column(db.String(100), nullable=False, index=True)  # Model class name
    entity_id = db.Column(db.Integer, nullable=True, index=True)
    entity_repr = db.Column(db.String(255), nullable=True)  # Human-readable representation

    # Change details (JSON for updates: {"field": {"old": x, "new": y}, ...})
    changes = db.Column(db.Text, nullable=True)

    # Event engine: false until the event evaluator has matched this row against
    # EventRules (set true once handled, so notifications are not repeated).
    event_processed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # Relationship to user (if available)
    user = db.relationship('User', foreign_keys=[user_id], backref='audit_logs')

    def __repr__(self):
        return f'<AuditLog {self.action} {self.entity_type}#{self.entity_id} by {self.user_email}>'

    @property
    def action_badge_class(self):
        """Returns Bootstrap badge class for the action type."""
        return {
            'create': 'success',
            'update': 'primary',
            'delete': 'danger'
        }.get(self.action, 'secondary')

    @property
    def action_icon(self):
        """Returns Font Awesome icon for the action type."""
        return {
            'create': 'fa-plus-circle',
            'update': 'fa-edit',
            'delete': 'fa-trash'
        }.get(self.action, 'fa-question-circle')
