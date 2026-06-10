from datetime import datetime
from sqlalchemy import and_
from sqlalchemy.orm import foreign
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .auth import User
from src.utils.timezone_helper import now, to_utc


# Association table for Credential <-> BusinessService
service_credentials = db.Table('service_credentials',
    db.Column('service_id', db.Integer, db.ForeignKey('business_service.id'), primary_key=True),
    db.Column('credential_id', db.Integer, db.ForeignKey('credentials.id'), primary_key=True)
)

class Credential(db.Model):
    """
    Credential lifecycle tracker.
    Stores metadata about credentials (API keys, OAuth tokens, etc.)
    but NEVER stores the actual secret values - only masked representations.
    """
    __tablename__ = 'credentials'
    
    # Indexes for efficient queries
    __table_args__ = (
        db.Index('idx_credential_owner', 'owner_type', 'owner_id'),
        db.Index('idx_credential_software', 'software_id'),
    )
    
    # ==========================================
    # PRIMARY FIELDS
    # ==========================================
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'API Key', 'OAuth', 'Service Account', 'SSH Key', 'Password', 'Certificate'
    break_glass = db.Column(db.Boolean, default=False, nullable=False)  # Critical/High Privilege marker
    description = db.Column(db.Text)
    
    # ==========================================
    # POLYMORPHIC OWNERSHIP
    # ==========================================
    owner_id = db.Column(db.Integer, nullable=False)
    owner_type = db.Column(db.String(50), nullable=False)  # 'User', 'Group'
    
    # ==========================================
    # ASSOCIATIONS (Nullable FKs)
    # ==========================================
    # service_id removed in favor of M2M relationship
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True)
    license_id = db.Column(db.Integer, db.ForeignKey('license.id'), nullable=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=True)
    
    # Relationships for reverse visibility
    services = db.relationship('BusinessService', secondary='service_credentials', backref=db.backref('credentials', lazy=LAZY_DYNAMIC))
    software = db.relationship('Software', backref=db.backref('credentials', lazy=LAZY_DYNAMIC))
    license = db.relationship('License', backref=db.backref('credentials', lazy=LAZY_DYNAMIC))
    asset = db.relationship('Asset', backref=db.backref('credentials', lazy=LAZY_DYNAMIC))
    
    # ==========================================
    # TIMESTAMPS
    # ==========================================
    created_at = db.Column(db.DateTime, default=lambda: now(), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now(), nullable=False)
    
    # ==========================================
    # RELATIONSHIPS
    # ==========================================
    secrets = db.relationship(
        'CredentialSecret',
        backref='credential',
        lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        order_by='CredentialSecret.created_at.desc()'
    )
    
    # ==========================================
    # PROPERTIES
    # ==========================================
    @property
    def active_secret(self):
        """Returns the currently active CredentialSecret (is_active=True)"""
        return self.secrets.filter_by(is_active=True).first()
    
    @property
    def owner(self):
        """Returns the owner object based on polymorphic relationship"""
        if self.owner_type == 'User':
            return db.session.get(User, self.owner_id)
        # Add other owner types as needed (Group, etc.)
        return None
    
    @property
    def target_name(self):
        """Returns a human-readable target name (Service/Software/License/Asset)"""
        # For M2M services, we might return the first one or a count
        if self.services:
            count = len(self.services)
            if count == 1:
                return self.services[0].name
            elif count > 1:
                return f"{count} Services"
        
        # Fallback to other relations
        if self.software_id:
            from .assets import Software
            software = db.session.get(Software, self.software_id)
            return software.name if software else f"Software #{self.software_id}"
        elif self.license_id:
            from .assets import License
            license = db.session.get(License, self.license_id)
            return license.name if license else f"License #{self.license_id}"
        elif self.asset_id:
            from .assets import Asset
            asset = db.session.get(Asset, self.asset_id)
            return asset.name if asset else f"Asset #{self.asset_id}"
        return "N/A"
    
    def __repr__(self):
        return f'<Credential {self.name} ({self.type})>'
class CredentialSecret(db.Model):
    """
    Stores masked secret values with expiration tracking.
    NEVER stores full secret values - only masked representations.
    """
    __tablename__ = 'credential_secrets'
    
    # Indexes for efficient queries
    __table_args__ = (
        db.Index('idx_secret_credential', 'credential_id', 'is_active'),
        db.Index('idx_secret_expiry', 'expires_at', 'is_active'),
    )
    
    # ==========================================
    # PRIMARY FIELDS
    # ==========================================
    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey('credentials.id'), nullable=False)
    
    # Masked value (e.g., "********1234")
    masked_value = db.Column(db.String(255), nullable=False)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: now(), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Active flag (only one secret should be active per credential)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # ==========================================
    # METHODS
    # ==========================================
    def set_secret(self, raw_value):
        """
        Masks the secret value and stores only the masked representation.
        NEVER stores the full value.
        
        Args:
            raw_value (str): The raw secret value to mask
            
        Logic:
            - If len(raw_value) <= 4: stores "****"
            - Else: stores asterisks + last 4 characters, capped at 16 chars total

        Example:
            "mySecretKey1234" -> "***********1234"
            "aVeryLongSecretValue1234" -> "************1234"
            "abc" -> "****"
        """
        MAX_LENGTH = 16
        if not raw_value:
            self.masked_value = "****"
            return

        if len(raw_value) <= 4:
            self.masked_value = "****"
        else:
            # Create masked value: asterisks + last 4 chars, capped at MAX_LENGTH
            num_asterisks = min(len(raw_value) - 4, MAX_LENGTH - 4)
            self.masked_value = ('*' * num_asterisks) + raw_value[-4:]
    
    @property
    def is_expired(self):
        """Check if this secret has expired"""
        if not self.expires_at:
            return False
        # Convert naive expires_at to timezone-aware before comparison
        expires_at_aware = to_utc(self.expires_at)
        return now() > expires_at_aware
    
    @property
    def days_until_expiry(self):
        """Calculate days until expiration (negative if expired)"""
        if not self.expires_at:
            return None
        # Convert naive expires_at to timezone-aware before subtraction
        expires_at_aware = to_utc(self.expires_at)
        delta = expires_at_aware - now()
        return delta.days
    
    @property
    def expiry_status(self):
        """Returns status: 'active', 'expiring_soon', 'expired'"""
        if not self.expires_at:
            return 'active'
        
        days = self.days_until_expiry
        if days < 0:
            return 'expired'
        elif days <= 7:
            return 'expiring_soon'
        elif days <= 30:
            return 'expiring_warning'
        return 'active'
    
    def __repr__(self):
        return f'<CredentialSecret {self.masked_value} (Active: {self.is_active})>'