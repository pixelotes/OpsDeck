from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from sqlalchemy.orm import foreign
from sqlalchemy import and_

# Association table for Request-Tag Many-to-Many
request_tags = db.Table('request_tags',
    db.Column('request_id', db.Integer, db.ForeignKey('request.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

# Lifecycle states (service-desk style fulfillment flow)
REQUEST_STATUSES = ['Pending', 'Triage', 'In Progress', 'Completed', 'Closed', 'Cancelled']

class Request(db.Model):
    """
    Service Request model.
    Tracks fulfillment requests (access, hardware, software, information, etc.)
    through a triage-based service-desk workflow:
    Pending -> Triage -> In Progress -> Completed -> Closed (Cancelled is off-flow).
    """
    id = db.Column(db.Integer, primary_key=True)
    external_ref = db.Column(db.String(255), unique=True, nullable=True, index=True)

    # --- Core Fields ---
    title = db.Column(db.String(200), nullable=False)
    request_type = db.Column(db.String(50), default='General')  # General, Access, Hardware, Software, Information
    priority = db.Column(db.String(50), default='Medium')       # Low, Medium, High, Critical
    status = db.Column(db.String(50), default='Pending', index=True)  # See REQUEST_STATUSES

    # --- Content (Markdown) ---
    description = db.Column(db.Text)       # What is being requested
    justification = db.Column(db.Text)     # Why it is needed (business case)
    resolution_notes = db.Column(db.Text)  # How it was fulfilled / resolved

    # --- Temporalization ---
    created_at = db.Column(db.DateTime, default=lambda: now())
    due_date = db.Column(db.DateTime, nullable=True)

    triaged_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # --- Actors ---
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    triaged_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)

    requester = db.relationship('User', foreign_keys=[requester_id], backref='submitted_requests')
    assignee = db.relationship('User', foreign_keys=[assignee_id], backref='assigned_requests')
    triaged_by = db.relationship('User', foreign_keys=[triaged_by_id], backref='triaged_requests')

    # --- Target (What the request is about) ---
    service_id = db.Column(db.Integer, db.ForeignKey('business_service.id'), nullable=True, index=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=True, index=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)

    service = db.relationship('BusinessService', backref='requests')
    asset = db.relationship('Asset', backref='requests')
    software = db.relationship('Software', backref='requests')

    # --- Integrations ---
    tags = db.relationship('Tag', secondary=request_tags, backref=db.backref('requests', lazy=LAZY_DYNAMIC))

    # Polymorphic Attachments (Evidence)
    attachments = db.relationship('Attachment',
                        primaryjoin="and_(Request.id==foreign(Attachment.linkable_id), "
                                    "Attachment.linkable_type=='Request')",
                        lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                        overlaps="attachments")

    # Compliance Links (Evidence for controls)
    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Request.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Request'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    def __repr__(self):
        return f'<Request {self.id}: {self.title}>'
