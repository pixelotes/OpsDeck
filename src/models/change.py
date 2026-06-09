from datetime import datetime
from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from sqlalchemy.orm import foreign
from sqlalchemy import and_

# Association table for Change-Tag Many-to-Many
change_tags = db.Table('change_tags',
    db.Column('change_id', db.Integer, db.ForeignKey('change.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Change(db.Model):
    """
    Change Management Audit-Ready Model.
    Tracks requests for changes to infrastructure, services, or assets.
    """
    id = db.Column(db.Integer, primary_key=True)
    external_ref = db.Column(db.String(255), unique=True, nullable=True, index=True)

    # --- Core Fields ---
    title = db.Column(db.String(200), nullable=False)
    change_type = db.Column(db.String(50), default='Standard') # Standard, Normal, Emergency
    priority = db.Column(db.String(50), default='Medium')      # Low, Medium, High, Critical
    risk_impact = db.Column(db.String(50), default='Low')      # Low, Medium, High
    status = db.Column(db.String(50), default='Draft', index=True)  # Draft, Pending Approval, Approved, In Progress, Completed, Failed, Cancelled
    requires_approval = db.Column(db.Boolean, default=True)    # Whether this change needs approval step
    
    # --- Planning & Execution (Markdown) ---
    description = db.Column(db.Text)          # What and Why
    implementation_plan = db.Column(db.Text)  # Detailed technical steps
    rollback_plan = db.Column(db.Text)        # GRC Critical: How to revert
    test_plan = db.Column(db.Text)            # Verification steps
    
    # --- Temporalization ---
    created_at = db.Column(db.DateTime, default=lambda: now())
    scheduled_start = db.Column(db.DateTime, nullable=True)
    scheduled_end = db.Column(db.DateTime, nullable=True)
    estimated_duration = db.Column(db.Integer, nullable=True) # In minutes
    
    executed_at = db.Column(db.DateTime, nullable=True) # Actual start
    closed_at = db.Column(db.DateTime, nullable=True)   # Actual end/close
    
    # --- Actors (Segregation of Duties) ---
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    requester = db.relationship('User', foreign_keys=[requester_id], backref='requested_changes')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_changes')
    approved_by = db.relationship('User', foreign_keys=[approved_by_id], backref='approved_changes')
    
    # --- Target (What is changing) ---
    service_id = db.Column(db.Integer, db.ForeignKey('business_service.id'), nullable=True, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=True, index=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)
    configuration_id = db.Column(db.Integer, db.ForeignKey('configuration.id'), nullable=True, index=True)
    configuration_version_id = db.Column(db.Integer, db.ForeignKey('configuration_version.id'), nullable=True, index=True)
    
    service = db.relationship('BusinessService', backref='changes')
    asset = db.relationship('Asset', backref='changes')
    software = db.relationship('Software', backref='changes')
    configuration = db.relationship('Configuration', backref='changes')
    configuration_version = db.relationship('ConfigurationVersion', backref='changes')
    
    # --- Integrations ---
    tags = db.relationship('Tag', secondary=change_tags, backref=db.backref('changes', lazy=LAZY_DYNAMIC))
    
    # Polymorphic Attachments (Evidence)
    attachments = db.relationship('Attachment',
                        primaryjoin="and_(Change.id==foreign(Attachment.linkable_id), "
                                    "Attachment.linkable_type=='Change')",
                        lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                        overlaps="attachments")
                        
    # Compliance Links (Evidence for controls)
    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Change.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Change'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    def __repr__(self):
        return f'<Change {self.id}: {self.title}>'
    
    @property
    def duration_display(self):
        """Format duration for display."""
        if not self.estimated_duration:
            return "N/A"
        hours = self.estimated_duration // 60
        minutes = self.estimated_duration % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
