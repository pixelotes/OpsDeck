from datetime import timedelta
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from src.utils.timezone_helper import today, now

# Cadence (frequency) → approximate interval in days. ad-hoc has no fixed schedule.
# Tolerates both the form values ('semi-annual', 'annual', ...) and the
# capitalized/legacy variants used elsewhere ('Yearly', 'Semiannual', ...).
FREQUENCY_TO_DAYS = {
    'weekly': 7,
    'biweekly': 14,
    'bi-weekly': 14,
    'monthly': 30,
    'quarterly': 90,
    'semi-annual': 180,
    'semiannual': 180,
    'annual': 365,
    'yearly': 365,
    'annually': 365,
    'ad-hoc': None,
    'adhoc': None,
}


def frequency_to_days(frequency):
    """Map a cadence string to its interval in days (None if no fixed schedule)."""
    if not frequency:
        return None
    return FREQUENCY_TO_DAYS.get(frequency.strip().lower().replace(' ', '-'))

# --- Association Tables for Security Activities ---

activity_participants = db.Table('activity_participants',
    db.Column('activity_id', db.Integer, db.ForeignKey('security_activity.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

activity_tags = db.Table('activity_tags',
    db.Column('activity_id', db.Integer, db.ForeignKey('security_activity.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

# Tags for Execution Logs
activity_execution_tags = db.Table('activity_execution_tags',
    db.Column('execution_id', db.Integer, db.ForeignKey('activity_execution.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class ActivityRelatedObject(db.Model):
    """
    Polymorphic association table for linking SecurityActivity to other system objects
    (Software, Assets, Documentation, etc.)
    """
    __tablename__ = 'activity_related_object'
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('security_activity.id'), nullable=False)
    related_object_id = db.Column(db.Integer, nullable=False, index=True)
    related_object_type = db.Column(db.String(50), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Relationship back to the activity
    activity = db.relationship('SecurityActivity', backref='related_object_links')
    
    @property
    def related_object(self):
        """Resolves the polymorphic relationship to the related object."""
        from .assets import Asset, Peripheral, Software, License
        from .procurement import Supplier, Subscription
        from .core import Link, Documentation
        from .policy import Policy
        from .training import Course
        from .bcdr import BCDRPlan
        from .security import SecurityIncident, Risk
        
        model_map = {
            'Asset': Asset,
            'Peripheral': Peripheral,
            'Software': Software,
            'License': License,
            'Supplier': Supplier,
            'Subscription': Subscription,
            'Link': Link,
            'Documentation': Documentation,
            'Policy': Policy,
            'Course': Course,
            'BCDRPlan': BCDRPlan,
            'SecurityIncident': SecurityIncident,
            'Risk': Risk,
        }
        
        model = model_map.get(self.related_object_type)
        if model:
            return db.session.get(model, self.related_object_id)
        return None

class SecurityActivity(db.Model):
    """
    Container for recurring security tasks (pentesting, access reviews, etc.)
    Follows the BCDRPlan pattern from bcdr.py
    """
    __tablename__ = 'security_activity'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    frequency = db.Column(db.String(50))  # 'monthly', 'quarterly', 'annual', etc.
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Polymorphic owner (User or Group) - following Link pattern from core.py
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50))  # 'User' or 'Group'
    
    # Relationships
    
    # Many-to-Many: Participants (Users who participate in this activity)
    participants = db.relationship('User', secondary=activity_participants, backref='security_activities')
    
    # Many-to-Many: Tags
    tags = db.relationship('Tag', secondary=activity_tags, backref=db.backref('security_activities', lazy=LAZY_DYNAMIC))
    
    # One-to-Many: Execution history
    executions = db.relationship('ActivityExecution', backref='activity', lazy=LAZY_DYNAMIC, 
                                cascade=CASCADE_ALL_DELETE_ORPHAN, 
                                order_by='ActivityExecution.execution_date.desc()')
    
    # Polymorphic: Attachments
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(SecurityActivity.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='SecurityActivity')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
    
    # Polymorphic: Compliance Links (following pattern from security.py)
    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == SecurityActivity.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'SecurityActivity'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )
    
    @property
    def owner(self):
        """Returns the User or Group object based on owner_type and owner_id."""
        from .auth import User, Group
        if self.owner_type == 'User' and self.owner_id:
            return db.session.get(User, self.owner_id)
        if self.owner_type == 'Group' and self.owner_id:
            return db.session.get(Group, self.owner_id)
        return None

    @property
    def last_execution(self):
        """Most recent execution record, or None if never performed."""
        return self.executions.first()

    @property
    def last_execution_date(self):
        """Date of the most recent execution, or None if never performed."""
        last = self.last_execution
        return last.execution_date if last else None

    @property
    def frequency_days(self):
        """Cadence interval in days (None for ad-hoc / unrecognized frequency)."""
        return frequency_to_days(self.frequency)

    @property
    def next_due_date(self):
        """
        When this activity should next be performed: the last execution date
        (or the creation date if never performed) plus the cadence interval.
        Returns None for ad-hoc activities with no fixed schedule.
        """
        days = self.frequency_days
        if not days:
            return None
        reference = self.last_execution_date or self.created_at.date()
        return reference + timedelta(days=days)

    @property
    def days_until_due(self):
        """Days until the next due date (negative if overdue). None for ad-hoc."""
        due = self.next_due_date
        if due is None:
            return None
        return (due - today()).days

class ActivityExecution(db.Model):
    """
    Execution record for a SecurityActivity
    Follows the BCDRTestLog pattern from bcdr.py
    """
    __tablename__ = 'activity_execution'
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('security_activity.id'), nullable=False)
    executor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    execution_date = db.Column(db.Date, nullable=False, default=lambda: today())
    status = db.Column(db.String(50), nullable=False)  # 'in_progress', 'success', 'failed', 'issue_detected'
    outcome_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Relationships
    executor = db.relationship('User', foreign_keys=[executor_id])
    
    # Tags
    tags = db.relationship('Tag', secondary=activity_execution_tags, backref=db.backref('activity_executions', lazy=LAZY_DYNAMIC))

    # Polymorphic: Attachments (for evidence files)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(ActivityExecution.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='ActivityExecution')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
