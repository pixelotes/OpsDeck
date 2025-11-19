from datetime import datetime, date
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment
from .auth import User, Group

policy_version_users = db.Table('policy_version_users',
    db.Column('policy_version_id', db.Integer, db.ForeignKey('policy_version.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

policy_version_groups = db.Table('policy_version_groups',
    db.Column('policy_version_id', db.Integer, db.ForeignKey('policy_version.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class Policy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100)) # e.g., 'IT Security', 'HR', 'General'
    description = db.Column(db.Text)
    link = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to its versions
    versions = db.relationship('PolicyVersion', backref='policy', lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Policy.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Policy')",
                            lazy=True, cascade='all, delete-orphan',
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Policy.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Policy'
        ),
        lazy='dynamic', cascade='all, delete-orphan',
        overlaps="compliance_links"
    )

class PolicyVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version_number = db.Column(db.String(50), nullable=False) # e.g., '1.0', '1.1', '2.0'
    status = db.Column(db.String(50), default='Draft') # 'Draft', 'Active', 'Archived'
    content = db.Column(db.Text) # The full text of the policy
    effective_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date) # Optional: when the policy version is no longer valid
    acknowledgements = db.relationship('PolicyAcknowledgement', backref='version', lazy=True, cascade='all, delete-orphan')
    users_to_acknowledge = db.relationship('User', secondary=policy_version_users, back_populates='policy_versions_to_acknowledge')
    groups_to_acknowledge = db.relationship('Group', secondary=policy_version_groups, back_populates='policy_versions_to_acknowledge')

    # Relationship back to the main policy document
    policy_id = db.Column(db.Integer, db.ForeignKey('policy.id'), nullable=False)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(PolicyVersion.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='PolicyVersion')",
                            lazy=True, cascade='all, delete-orphan',
                            overlaps="attachments")

class PolicyAcknowledgement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_version.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    acknowledged_at = db.Column(db.DateTime, default=datetime.utcnow)
