from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN

class Requirement(db.Model):
    """Requirements/Ideas for procurement - formerly Lead"""
    __tablename__ = 'lead'  # Keep existing table name for backward compatibility

    id = db.Column(db.Integer, primary_key=True)

    # Main fields
    name = db.Column(db.String(255), nullable=False)  # Renamed from company_name
    # Map company_name column to name for backward compatibility
    # Use synonym that maps to the same column
    _company_name_col = db.Column('company_name', db.String(255), nullable=False, default='')

    @property
    def company_name(self):
        """Backward compatibility: return name"""
        return self.name

    @company_name.setter
    def company_name(self, value):
        """Backward compatibility: set name"""
        self.name = value

    # Classification
    requirement_type = db.Column(db.String(50))  # 'Software', 'Hardware', 'Service', 'Consulting'
    priority = db.Column(db.String(20), default='Medium')  # 'Low', 'Medium', 'High', 'Critical'
    status = db.Column(db.String(50), default='New')  # 'New', 'Researching', 'Evaluating', 'Converted', 'Rejected'

    # Details
    description = db.Column(db.Text)  # Renamed from notes
    notes = db.synonym('description')  # Backward compatibility alias
    estimated_budget = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    needed_by = db.Column(db.Date)  # Target date

    # Legacy contact fields (kept for backward compatibility, optional)
    contact_name = db.Column(db.String(255))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))

    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: now())
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    actions = db.relationship('RequirementAction', backref='requirement', lazy=True,
                              cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='RequirementAction.created_at.desc()')
    evaluations = db.relationship('Opportunity', backref='source_requirement', lazy=True,
                                  foreign_keys='Opportunity.requirement_id')

# Event listener to keep name and _company_name_col in sync
from sqlalchemy import event

@event.listens_for(Requirement, 'before_insert')
@event.listens_for(Requirement, 'before_update')
def sync_company_name(mapper, connection, target):
    """Ensure _company_name_col matches name for backward compatibility"""
    target._company_name_col = target.name

# Backward compatibility alias
Lead = Requirement


class RequirementAction(db.Model):
    """Actions/notes on a requirement"""
    __tablename__ = 'requirement_action'

    id = db.Column(db.Integer, primary_key=True)
    requirement_id = db.Column(db.Integer, db.ForeignKey('lead.id'), nullable=False)
    action_type = db.Column(db.String(50), default='Note')  # 'Note', 'Research', 'Meeting', 'Decision', 'Email'
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())
    edited_at = db.Column(db.DateTime)
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))


class Opportunity(db.Model):
    """Evaluations of potential solutions/suppliers"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default='Evaluating')  # e.g., Evaluating, PoC, Negotiating, Won, Lost
    potential_value = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    estimated_close_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())

    # Foreign keys
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    primary_contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'))
    requirement_id = db.Column(db.Integer, db.ForeignKey('lead.id'))  # Link to source requirement
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'))
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'))

    # Relationships
    activities = db.relationship('Activity', backref='opportunity', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='Activity.activity_date.desc()')
    tasks = db.relationship('OpportunityTask', backref='opportunity', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='OpportunityTask.created_at.asc()')

class Activity(db.Model):
    """Activity log entries for opportunities"""
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False, default='Meeting')  # e.g., Meeting, Call, Email, Note
    activity_date = db.Column(db.DateTime, default=lambda: now())
    notes = db.Column(db.Text, nullable=False)
    edited_at = db.Column(db.DateTime)
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)

    # Relationship
    opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id'), nullable=False)


class OpportunityTask(db.Model):
    """Tasks/checklist for an evaluation"""
    __tablename__ = 'opportunity_task'

    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id'), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=lambda: now())
    completed_at = db.Column(db.DateTime)
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(50))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    opportunities = db.relationship('Opportunity', backref='primary_contact', foreign_keys='Opportunity.primary_contact_id')
