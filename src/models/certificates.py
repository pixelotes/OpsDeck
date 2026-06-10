from datetime import datetime, timedelta
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .auth import User
from src.utils.timezone_helper import now, today


# Association table for Certificate <-> BusinessService
service_certificates = db.Table('service_certificates',
    db.Column('service_id', db.Integer, db.ForeignKey('business_service.id'), primary_key=True),
    db.Column('certificate_id', db.Integer, db.ForeignKey('certificates.id'), primary_key=True)
)

class Certificate(db.Model):
    """
    Represents a digital certificate entity (logical).
    Example: "Wildcard *.example.com"
    """
    __tablename__ = 'certificates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), default='SSL/TLS')  # SSL/TLS, SAML, Code Signing, etc.
    description = db.Column(db.Text)
    
    # Ownership (Polymorphic-ish, typically User or Group, simplified here to User for MVP as per request context implies straightforward owner)
    # The request mentioned owner_id/owner_type polymorphic. 
    # Let's align with Credentials model pattern if possible, or just User for now if simpler.
    # Request said: owner_id / owner_type: Polimórfico (User o Group).
    # I will implement it as fields.
    owner_id = db.Column(db.Integer, nullable=True) 
    owner_type = db.Column(db.String(50), default='User') # 'User', 'Group'

    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    # Relationship to Services
    services = db.relationship('BusinessService', secondary=service_certificates, backref=db.backref('certificates', lazy=LAZY_DYNAMIC))

    # Relationship to Versions
    versions = db.relationship('CertificateVersion', backref='certificate', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='desc(CertificateVersion.expires_at)')

    @property
    def owner(self):
        """Returns the owner object based on polymorphic relationship"""
        if self.owner_type == 'User' and self.owner_id:
            return db.session.get(User, self.owner_id)
        # Add Group logic if Groups model exists and is required, for MVP User is safest bet to implement first.
        return None
    
    @property
    def active_version(self):
        """Returns the currently active version (based on is_active=True and latest expiry)"""
        return self.versions.filter_by(is_active=True).first() # Versions are ordered by desc expires_at

    @property
    def status_color(self):
        """Returns status color based on active version expiration"""
        version = self.active_version
        if not version:
            return 'secondary' # No version
        
        days = version.days_until_expiry
        if days < 0:
            return 'danger' # Expired
        if days < 7:
            return 'danger' # Critical
        if days < 30:
            return 'warning' # Warning
        return 'success' # Good

    def __repr__(self):
        return f'<Certificate {self.name}>'


class CertificateVersion(db.Model):
    """
    Represents a specific issuance of a certificate (e.g. the one expiring in 2025).
    """
    __tablename__ = 'certificate_versions'

    id = db.Column(db.Integer, primary_key=True)
    certificate_id = db.Column(db.Integer, db.ForeignKey('certificates.id'), nullable=False)
    
    # Version Details
    version_notes = db.Column(db.String(255)) # e.g. "2024 Renewal"
    
    # Dates
    valid_from = db.Column(db.Date)
    expires_at = db.Column(db.Date, nullable=False)
    
    # Metadata
    issuer = db.Column(db.String(100)) # e.g. DigiCert
    common_name = db.Column(db.String(255))
    serial_number = db.Column(db.String(100))
    
    # Content storage
    public_body = db.Column(db.Text) # PEM
    private_key_location = db.Column(db.String(255)) # Description of location
    
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def days_until_expiry(self):
        if not self.expires_at:
            return 0
        # Convert date to datetime for calculation if needed, or strictly use date
        # expires_at is db.Date, today() gives date.
        today_date = today()
        delta = self.expires_at - today_date
        return delta.days
