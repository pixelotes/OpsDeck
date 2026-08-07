from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from ..services.risk_scale import DEFAULT_LEVELS, RiskScale

# Association table for Risk Assessment - Change Mitigation M2M
risk_assessment_changes = db.Table('risk_assessment_changes',
    db.Column('assessment_id', db.Integer, db.ForeignKey('risk_assessment.id'), primary_key=True),
    db.Column('change_id', db.Integer, db.ForeignKey('change.id'), primary_key=True),
    db.Index('ix_risk_assessment_changes_change_id', 'change_id')
)


class RiskAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False) # e.g., "Q1 2024 Assessment"
    status = db.Column(db.String(50), default='Draft') # Draft, In Review, Locked
    created_at = db.Column(db.DateTime, default=lambda: now())
    locked_at = db.Column(db.DateTime, nullable=True)
    
    # Snapshot of global metrics at closure time
    total_residual_risk = db.Column(db.Integer) 
    
    items = db.relationship('RiskAssessmentItem', backref='assessment', cascade=CASCADE_ALL_DELETE_ORPHAN)

    # Relationship to Changes that mitigate risks in this assessment
    mitigating_changes = db.relationship('Change', secondary=risk_assessment_changes, 
                                       backref=db.backref('risk_assessments', lazy=LAZY_DYNAMIC))


    @property
    def current_total_risk(self):
        """Calculates sum of residual scores for current items (dynamic)."""
        return sum(item.residual_score for item in self.items)

    def calculate_total_risk(self):
        """Saves the current total risk to the database field."""
        self.total_residual_risk = self.current_total_risk
        return self.total_residual_risk

class RiskAssessmentItem(db.Model):
    """
    Represents a risk at a specific point in time.
    IMPORTANT: Fields here are COPIES of live risk values.
    """
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey('risk_assessment.id'), nullable=False, index=True)
    original_risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'), nullable=True, index=True) # Optional link to original
    
    # Relationship to original risk for assessment history access
    original_risk = db.relationship('Risk', backref=db.backref('assessment_items', lazy=LAZY_DYNAMIC))
    
    # --- SNAPSHOT DATA (Frozen values) ---
    risk_description = db.Column(db.Text)
    threat_type_name = db.Column(db.String(100)) # Copy of ThreatType name
    category_list = db.Column(db.String(255)) # Comma-separated categories
    
    # Scores
    inherent_impact = db.Column(db.Integer)
    inherent_likelihood = db.Column(db.Integer)
    residual_impact = db.Column(db.Integer)
    residual_likelihood = db.Column(db.Integer)

    # The matrix these were chosen from, stamped when the item is written — see the same
    # pair on Risk. An assessment is a snapshot of a judgement made on a day; re-reading
    # it through a matrix adopted later would change what that judgement said.
    impact_levels = db.Column(db.Integer, default=DEFAULT_LEVELS, nullable=False,
                              server_default=str(DEFAULT_LEVELS))
    likelihood_levels = db.Column(db.Integer, default=DEFAULT_LEVELS, nullable=False,
                                  server_default=str(DEFAULT_LEVELS))
    
    treatment_strategy = db.Column(db.String(50))
    mitigation_notes = db.Column(db.Text) # Specific notes for this assessment

    # --- Relationships ---
    evidence = db.relationship('RiskAssessmentEvidence', backref='item', cascade=CASCADE_ALL_DELETE_ORPHAN)

    @property
    def scale(self):
        return RiskScale(self.impact_levels or DEFAULT_LEVELS,
                         self.likelihood_levels or DEFAULT_LEVELS)

    @property
    def residual_score(self):
        return self.scale.score(self.residual_impact, self.residual_likelihood)

    @property
    def inherent_score(self):
        return self.scale.score(self.inherent_impact, self.inherent_likelihood)

    @property
    def residual_percent(self):
        return self.scale.percent(self.residual_impact, self.residual_likelihood)

    @property
    def criticality_level(self):
        return self.scale.level_for(self.residual_impact, self.residual_likelihood)

class RiskAssessmentEvidence(db.Model):
    """
    Polymorphic table to link evidence (Policies, Assets, etc.) or file attachments to an assessment item.
    Either (linkable_type + linkable_id) OR attachment_id should be set.
    """
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('risk_assessment_item.id'), nullable=False, index=True)
    
    # Option 1: Link to OpsDeck object (Policy, Asset, etc.)
    linkable_type = db.Column(db.String(50), nullable=True)
    linkable_id = db.Column(db.Integer, nullable=True)
    
    # Option 2: Link to uploaded file
    attachment_id = db.Column(db.Integer, db.ForeignKey('attachment.id'), nullable=True, index=True)
    attachment = db.relationship('Attachment')
    
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def display_name(self):
        """Returns a readable name for the evidence item."""
        if self.attachment_id and self.attachment:
            return self.attachment.filename
        elif self.linkable_type and self.linked_object:
            obj = self.linked_object
            if hasattr(obj, 'title'):
                return obj.title
            elif hasattr(obj, 'name'):
                return obj.name
            return f"{self.linkable_type} #{self.linkable_id}"
        return "Unknown Evidence"

    @property
    def linked_object(self):
        """Resolves the linked object dynamically."""
        if not self.linkable_type:
            return None
            
        from . import Policy, Asset, Documentation, Link, BCDRPlan, Software, Supplier, Course, Change
        from .services import BusinessService
        
        model_map = {
            'Policy': Policy,
            'Asset': Asset,
            'Documentation': Documentation,
            'Link': Link,
            'BCDRPlan': BCDRPlan,
            'Software': Software,
            'Supplier': Supplier,
            'Course': Course,
            'BusinessService': BusinessService,
            'Change': Change
        }
        
        model = model_map.get(self.linkable_type)
        if model:
            return db.session.get(model, self.linkable_id)
        return None
