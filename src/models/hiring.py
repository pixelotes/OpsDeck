from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN

class HiringStage(db.Model):
    """Kanban stages for the hiring pipeline."""
    __tablename__ = 'hiring_stage'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Applied", "Interview", "Offer"
    order = db.Column(db.Integer, default=0)  # For sorting columns
    is_hired_stage = db.Column(db.Boolean, default=False)  # Marker for the final stage
    
    # Relationship
    candidates = db.relationship('Candidate', backref='stage', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)

class Candidate(db.Model):
    """Candidate records for recruitment tracking."""
    __tablename__ = 'candidate'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    position = db.Column(db.String(100))  # e.g., "DevOps Engineer"
    expected_salary = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    
    # Kanban Location
    stage_id = db.Column(db.Integer, db.ForeignKey('hiring_stage.id'), nullable=False)
    
    # Metadata
    resume_link = db.Column(db.String(255))  # Optional external link or file path
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    is_archived = db.Column(db.Boolean, default=False)
