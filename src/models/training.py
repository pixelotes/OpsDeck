from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from src.utils.timezone_helper import today, now

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(512))
    completion_days = db.Column(db.Integer, default=30) # Timeframe to complete after assignment
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    assignments = db.relationship('CourseAssignment', backref='course', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Course.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Course'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

class CourseAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assigned_date = db.Column(db.Date, nullable=False, default=lambda: today())
    due_date = db.Column(db.Date, nullable=False)
    
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    completion = db.relationship('CourseCompletion', backref='assignment', uselist=False, cascade=CASCADE_ALL_DELETE_ORPHAN)

class CourseCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    completion_date = db.Column(db.Date, nullable=False, default=lambda: today())
    notes = db.Column(db.Text)
    
    assignment_id = db.Column(db.Integer, db.ForeignKey('course_assignment.id'), nullable=False)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(CourseCompletion.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='CourseCompletion')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
