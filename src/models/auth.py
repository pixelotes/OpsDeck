from src.utils.timezone_helper import now
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
import secrets

user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    users = db.relationship('User', secondary=user_groups, back_populates='groups')
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary='policy_version_groups', back_populates='groups_to_acknowledge')

from .core import CustomPropertiesMixin

class User(db.Model, CustomPropertiesMixin): # Add UserMixin here if using Flask-Login
    __tablename__ = 'user'
    __table_args__ = {'quote': True}  # Fuerza: SELECT * FROM "user"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False) # Make email unique and required for login
    personal_email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255)) # Can be nullable for users who don't log in
    api_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    role = db.Column(db.String(50), default='user') # e.g., 'user', 'editor', 'admin'
    department = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    assets = db.relationship('Asset', backref='user', lazy=True)
    peripherals = db.relationship('Peripheral', backref='user', lazy=True)
    licenses = db.relationship('License', backref='user', lazy=True)
    
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    hide_from_org_chart = db.Column(db.Boolean, default=False, nullable=False, index=True)
    
    acknowledgements = db.relationship('PolicyAcknowledgement', backref='user', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    groups = db.relationship('Group', secondary=user_groups, back_populates='users')
    
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary='policy_version_users', back_populates='users_to_acknowledge')
    
    course_assignments = db.relationship('CourseAssignment', backref='user', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(User.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='User')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
                            
    # Hierarchy & Mentorship
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    manager = db.relationship('User', remote_side='User.id', backref='direct_reports', foreign_keys=[manager_id])

    buddy_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    buddy = db.relationship('User', remote_side='User.id', foreign_keys=[buddy_id], backref='mentees')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        # Only check password if one is set
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

    def generate_token(self):
        self.api_token = secrets.token_hex(32)
        return self.api_token

    def can_be_archived(self):
        """
        Check if user can be archived. Returns (can_archive, error_messages).

        A user cannot be archived if they have:
        - Active (non-archived) assets assigned
        - Active (non-archived) peripherals assigned
        - Active (non-archived) licenses assigned
        - Active payment methods

        Returns:
            tuple: (bool, list) - (can_archive, list_of_error_messages)
        """
        errors = []

        # Check for active assets
        active_assets = [a for a in self.assets if not a.is_archived]
        if active_assets:
            errors.append(f"User has {len(active_assets)} active asset(s) assigned")

        # Check for active peripherals
        active_peripherals = [p for p in self.peripherals if not p.is_archived]
        if active_peripherals:
            errors.append(f"User has {len(active_peripherals)} active peripheral(s) assigned")

        # Check for active licenses
        active_licenses = [l for l in self.licenses if not l.is_archived]
        if active_licenses:
            errors.append(f"User has {len(active_licenses)} active license(s) assigned")

        # Check for payment methods
        if hasattr(self, 'payment_methods') and self.payment_methods:
            errors.append(f"User has {len(self.payment_methods)} payment method(s) registered")

        return (len(errors) == 0, errors)

    def prepare_for_archival(self):
        """
        Clean up non-critical relationships before archiving.

        This method:
        - Removes user from subscription assignments (subscription_users many-to-many)
        - Nullifies direct subscription.user_id references

        Critical relationships (assets, licenses, payment methods) are NOT cleaned
        and should be checked with can_be_archived() first.
        """
        from .procurement import Subscription

        # Clean up subscription assignments (many-to-many)
        # The 'access_subscriptions' backref comes from subscription_users table
        if hasattr(self, 'access_subscriptions'):
            for subscription in list(self.access_subscriptions):
                subscription.users.remove(self)

        # Nullify direct subscription ownership (Subscription.user_id)
        direct_subscriptions = Subscription.query.filter_by(user_id=self.id, is_archived=False).all()
        for subscription in direct_subscriptions:
            subscription.user_id = None


class UserKnownIP(db.Model):
    """Stores known IP addresses for users to enable MFA bypass."""
    __tablename__ = 'user_known_ips'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)  # IPv6 compatible
    created_at = db.Column(db.DateTime, default=lambda: now())
    last_seen = db.Column(db.DateTime, default=lambda: now())
    
    user = db.relationship('User', backref=db.backref('known_ips', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN))
    
    __table_args__ = (
        db.Index('idx_user_ip', 'user_id', 'ip_address'),
    )
    
    def __repr__(self):
        return f'<UserKnownIP {self.ip_address} for User {self.user_id}>'

class OrgChartSnapshot(db.Model):
    """
    Representa una fotografía estática de la estructura organizativa en una fecha.
    Se usa como evidencia de cumplimiento (ej. ISO 27001 A.5.2 Roles y Responsabilidades).
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False) # Ej: "Organigrama Q1 2024"
    created_at = db.Column(db.DateTime, default=lambda: now())
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    chart_data = db.Column(db.JSON, nullable=False)
    
    notes = db.Column(db.Text)
    
    created_by = db.relationship('User')

    # Relación inversa para Auditorías (Evidence)
    # Esto permite ver desde el Snapshot en qué auditorías se usó
    audit_links = db.relationship('AuditControlLink',
        primaryjoin="and_(OrgChartSnapshot.id==foreign(AuditControlLink.linkable_id), "
                    "AuditControlLink.linkable_type=='OrgChartSnapshot')",
        lazy=LAZY_DYNAMIC
    )
