from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from src.utils.timezone_helper import today, now

# --- Association Tables for BCDR ---
bcdr_plan_subscriptions = db.Table('bcdr_plan_subscriptions',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True)
)

bcdr_plan_assets = db.Table('bcdr_plan_assets',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('asset.id'), primary_key=True)
)

# Tags for BCDR Test Logs
bcdr_test_tags = db.Table('bcdr_test_tags',
    db.Column('test_log_id', db.Integer, db.ForeignKey('bcdr_test_log.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class BCDRPlan(db.Model):
    __tablename__ = 'bcdr_plan'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Relationships
    subscriptions = db.relationship('Subscription', secondary=bcdr_plan_subscriptions, backref='bcdr_plans')
    assets = db.relationship('Asset', secondary=bcdr_plan_assets, backref='bcdr_plans')
    test_logs = db.relationship('BCDRTestLog', backref='plan', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='BCDRTestLog.test_date.desc()')

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == BCDRPlan.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'BCDRPlan'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

class BCDRTestLog(db.Model):
    __tablename__ = 'bcdr_test_log'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('bcdr_plan.id'), nullable=False)
    test_date = db.Column(db.Date, nullable=False, default=lambda: today())
    status = db.Column(db.String(50), nullable=False) # In Progress, Passed, Failed
    notes = db.Column(db.Text)
    
    # Assignee (Executor)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    assignee = db.relationship('User', foreign_keys=[assignee_id])

    # Tags
    tags = db.relationship('Tag', secondary=bcdr_test_tags, backref=db.backref('bcdr_test_logs', lazy=LAZY_DYNAMIC))

    # Relationships
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(BCDRTestLog.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='BCDRTestLog')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
