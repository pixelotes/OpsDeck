from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN

class HiringStage(db.Model):
    """Kanban stages for the hiring pipeline.

    The three booleans exist so that behaviour keys off data rather than off the label.
    Names used to be load-bearing in three places — deletion guards, the board's
    archiving filter and the template's disabled button — which meant renaming 'Hired'
    quietly took its behaviour with it. Renaming is now purely cosmetic, so a pipeline
    can be relabelled or translated without losing its semantics.
    """
    __tablename__ = 'hiring_stage'

    id = db.Column(db.Integer, primary_key=True)
    # Unique so a second 'Hired' cannot exist: duplicated system stages are impossible
    # to remove through the UI, since deletion refuses to touch them.
    name = db.Column(db.String(100), nullable=False)  # e.g., "Applied", "Interview", "Offer"
    order = db.Column(db.Integer, default=0)  # For sorting columns

    # Moving a candidate here starts onboarding.
    is_hired_stage = db.Column(db.Boolean, default=False)
    # Part of the standard pipeline: cannot be deleted, whatever it is called.
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    # The candidate's process is over here, so the board stops showing stale ones.
    is_terminal = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        db.UniqueConstraint('name', name='uq_hiring_stage_name'),
    )

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
    stage_id = db.Column(db.Integer, db.ForeignKey('hiring_stage.id'), nullable=False, index=True)
    
    # Metadata
    resume_link = db.Column(db.String(255))  # Optional external link or file path
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    is_archived = db.Column(db.Boolean, default=False)
