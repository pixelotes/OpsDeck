from datetime import datetime, date
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment
from .auth import User

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(512))
    completion_days = db.Column(db.Integer, default=30) # Timeframe to complete after assignment
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    assignments = db.relationship('CourseAssignment', backref='course', lazy=True, cascade='all, delete-orphan')

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Course.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Course'
        ),
        lazy='dynamic', cascade='all, delete-orphan',
        overlaps="compliance_links"
    )

class CourseAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assigned_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    completion = db.relationship('CourseCompletion', backref='assignment', uselist=False, cascade='all, delete-orphan')

class CourseCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    completion_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.Text)
    
    assignment_id = db.Column(db.Integer, db.ForeignKey('course_assignment.id'), nullable=False)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(CourseCompletion.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='CourseCompletion')",
                            lazy=True, cascade='all, delete-orphan',
                            overlaps="attachments")
