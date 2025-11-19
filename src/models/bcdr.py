from datetime import datetime, date
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment

# --- Association Tables for BCDR ---
bcdr_plan_subscriptions = db.Table('bcdr_plan_subscriptions',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True)
)

bcdr_plan_assets = db.Table('bcdr_plan_assets',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('asset.id'), primary_key=True)
)

class BCDRPlan(db.Model):
    __tablename__ = 'bcdr_plan'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    subscriptions = db.relationship('Subscription', secondary=bcdr_plan_subscriptions, backref='bcdr_plans')
    assets = db.relationship('Asset', secondary=bcdr_plan_assets, backref='bcdr_plans')
    test_logs = db.relationship('BCDRTestLog', backref='plan', lazy='dynamic', cascade='all, delete-orphan', order_by='BCDRTestLog.test_date.desc()')

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == BCDRPlan.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'BCDRPlan'
        ),
        lazy='dynamic', cascade='all, delete-orphan'
    )

class BCDRTestLog(db.Model):
    __tablename__ = 'bcdr_test_log'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('bcdr_plan.id'), nullable=False)
    test_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(50), nullable=False) # In Progress, Passed, Failed
    notes = db.Column(db.Text)
    
    # Relationships
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(BCDRTestLog.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='BCDRTestLog')",
                            lazy=True, cascade='all, delete-orphan')
