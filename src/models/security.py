from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .core import Attachment
from .auth import User
from src.utils.timezone_helper import today, now

class ComplianceLink(db.Model):
    """
    Polymorphic association table.
    Vincula un control (ej. 'A.5.7') con un objeto 
    (ej. un Asset, una Policy) y explica CÓMO lo cumple.
    """
    __tablename__ = 'compliance_link'
    id = db.Column(db.Integer, primary_key=True)
    
    # Side 1: the control being satisfied
    framework_control_id = db.Column(db.Integer, db.ForeignKey('framework_control.id'), nullable=False)
    
    # Side 2: the polymorphic object that satisfies it
    linkable_id = db.Column(db.Integer, nullable=False, index=True)
    linkable_type = db.Column(db.String(50), nullable=False, index=True)

    description = db.Column(db.Text, nullable=False)

    # --- Relaciones ---
    
    # Back-reference so the links are reachable from FrameworkControl
    framework_control = db.relationship(
        'FrameworkControl',
        backref=db.backref('compliance_links', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    )

    @property
    def linked_object(self):
        """Resolves the polymorphic relationship to the linked object."""
        # Import models inside the method to avoid circular imports
        from .assets import Asset, Peripheral, Software, License, MaintenanceLog
        from .procurement import Supplier, Purchase, Budget, Subscription
        from .core import Link, Documentation
        from .policy import Policy
        from .training import Course
        from .bcdr import BCDRPlan
        from .activities import SecurityActivity, ActivityExecution
        from .services import BusinessService
        from .onboarding import OnboardingProcess, OffboardingProcess
        
        # Map types to models
        model_map = {
            'Asset': Asset,
            'Peripheral': Peripheral,
            'Software': Software,
            'License': License,
            'MaintenanceLog': MaintenanceLog,
            'Supplier': Supplier,
            'Purchase': Purchase,
            'Budget': Budget,
            'Subscription': Subscription,
            'Link': Link,
            'Documentation': Documentation,
            'Policy': Policy,
            'Course': Course,
            'BCDRPlan': BCDRPlan,
            'SecurityIncident': SecurityIncident,
            'SecurityAssessment': SecurityAssessment,
            'Risk': Risk,
            'AssetInventory': AssetInventory,
            'SecurityActivity': SecurityActivity,
            'ActivityExecution': ActivityExecution,
            'BusinessService': BusinessService,
            'Onboarding': OnboardingProcess,
            'Offboarding': OffboardingProcess
        }
        
        model = model_map.get(self.linkable_type)
        if model:
            return db.session.get(model, self.linkable_id)
        return None

incident_assets = db.Table('incident_assets',
    db.Column('incident_id', db.Integer, db.ForeignKey('security_incident.id'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('asset.id'), primary_key=True)
)

incident_users = db.Table('incident_users',
    db.Column('incident_id', db.Integer, db.ForeignKey('security_incident.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

incident_subscriptions = db.Table('incident_subscriptions',
    db.Column('incident_id', db.Integer, db.ForeignKey('security_incident.id'), primary_key=True),
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True)
)

incident_suppliers = db.Table('incident_suppliers',
    db.Column('incident_id', db.Integer, db.ForeignKey('security_incident.id'), primary_key=True),
    db.Column('supplier_id', db.Integer, db.ForeignKey('supplier.id'), primary_key=True)
)

# Tags for Incidents
incident_tags = db.Table('incident_tags',
    db.Column('incident_id', db.Integer, db.ForeignKey('security_incident.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class SecurityIncident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    external_ref = db.Column(db.String(255), unique=True, nullable=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    incident_date = db.Column(db.DateTime, default=lambda: now())
    status = db.Column(db.String(50), default='Investigating', index=True) # Investigating, Contained, Resolved, Closed
    severity = db.Column(db.String(50), default='SEV-3') # SEV-0 (Critical) to SEV-3 (Low)
    impact = db.Column(db.String(50), default='Minor') # Minor, Moderate, Significant, Extensive
    data_breach = db.Column(db.Boolean, default=False)
    third_party_impacted = db.Column(db.Boolean, default=False)
    review = db.relationship('PostIncidentReview', backref='incident', uselist=False, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    created_at = db.Column(db.DateTime, default=lambda: now())
    resolved_at = db.Column(db.DateTime)
    
    # Relationships
    reported_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)

    reported_by = db.relationship('User', foreign_keys=[reported_by_id])
    owner = db.relationship('User', foreign_keys=[owner_id])

    # Assignee (Resolver)
    assignee_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    assignee = db.relationship('User', foreign_keys=[assignee_id])

    # Tags
    tags = db.relationship('Tag', secondary=incident_tags, backref=db.backref('security_incidents', lazy=LAZY_DYNAMIC))

    affected_assets = db.relationship('Asset', secondary=incident_assets, backref='incidents')
    affected_users = db.relationship('User', secondary=incident_users, backref='incidents')
    affected_subscriptions = db.relationship('Subscription', secondary=incident_subscriptions, backref='incidents')
    affected_suppliers = db.relationship('Supplier', secondary=incident_suppliers, backref='incidents')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(SecurityIncident.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='SecurityIncident')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
    
    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(SecurityIncident.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='SecurityIncident')",
                            lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="compliance_links")

class PostIncidentReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('security_incident.id'), unique=True, nullable=False)
    summary = db.Column(db.Text)
    lead_up = db.Column(db.Text)
    fault = db.Column(db.Text)
    impact_analysis = db.Column(db.Text)
    detection = db.Column(db.Text)
    response = db.Column(db.Text)
    recovery = db.Column(db.Text)
    lessons_learned = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    
    # Locking mechanism for finalized reports
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    locked_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    locked_by = db.relationship('User', foreign_keys=[locked_by_id])

    # Relationships
    timeline_events = db.relationship('IncidentTimelineEvent', backref='review', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='IncidentTimelineEvent.order')

class IncidentTimelineEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('post_incident_review.id'), nullable=False)
    event_time = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

class RiskAffectedItem(db.Model):
    __tablename__ = 'risk_affected_item'
    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'), nullable=False)
    linkable_type = db.Column(db.String(50), nullable=False)
    linkable_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def item(self):
        # Import models inside to avoid circular imports
        from .assets import Asset, Peripheral, Software, License, MaintenanceLog
        from .procurement import Supplier, Purchase, Budget, Subscription
        from .core import Link, Documentation
        from .auth import Group
        from .policy import Policy
        from .training import Course
        from .bcdr import BCDRPlan
        from .activities import SecurityActivity, ActivityExecution
        from .services import BusinessService
        
        model_map = {
            'User': User,
            'Group': Group,
            'Asset': Asset,
            'Peripheral': Peripheral,
            'Software': Software,
            'License': License,
            'MaintenanceLog': MaintenanceLog,
            'Supplier': Supplier,
            'Purchase': Purchase,
            'Budget': Budget,
            'Subscription': Subscription,
            'Link': Link,
            'Documentation': Documentation,
            'Policy': Policy,
            'Course': Course,
            'BCDRPlan': BCDRPlan,
            'SecurityActivity': SecurityActivity,
            'ActivityExecution': ActivityExecution,
            'SecurityIncident': SecurityIncident,
            'SecurityAssessment': SecurityAssessment,
            'Risk': Risk,
            'AssetInventory': AssetInventory,
            'BusinessService': BusinessService,
        }
        
        model = model_map.get(self.linkable_type)
        if model:
            return db.session.get(model, self.linkable_id)
        return None


class RiskReference(db.Model):
    """
    Polymorphic association table for linking Risk to context/reference objects.
    Restricted to Policy, Documentation, and Link types.
    """
    __tablename__ = 'risk_reference'
    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'), nullable=False)
    linkable_type = db.Column(db.String(50), nullable=False)  # 'Policy', 'Documentation', 'Link'
    linkable_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def item(self):
        """Resolves the polymorphic relationship to the reference object."""
        from .core import Link, Documentation
        from .policy import Policy
        
        model_map = {
            'Policy': Policy,
            'Documentation': Documentation,
            'Link': Link,
        }
        
        model = model_map.get(self.linkable_type)
        if model:
            return db.session.get(model, self.linkable_id)
        return None


# Standard CIA Triad + Extended risk categories
RISK_CATEGORIES = [
    'Confidentiality', 'Integrity', 'Availability',
    'Traceability', 'Authenticity', 'Legal', 'Reputational'
]

# Category color mapping for UI
RISK_CATEGORY_COLORS = {
    'Confidentiality': 'danger',
    'Integrity': 'primary',
    'Availability': 'warning',
    'Traceability': 'info',
    'Authenticity': 'secondary',
    'Legal': 'dark',
    'Reputational': 'success'
}

risk_category_association = db.Table('risk_category_association',
    db.Column('risk_id', db.Integer, db.ForeignKey('risk.id'), primary_key=True),
    db.Column('category', db.String(50), primary_key=True)
)

risk_mitigation_activities = db.Table('risk_mitigation_activities',
    db.Column('risk_id', db.Integer, db.ForeignKey('risk.id'), primary_key=True),
    db.Column('activity_id', db.Integer, db.ForeignKey('security_activity.id'), primary_key=True)
)

class ThreatType(db.Model):
    """
    Catalogue of standardised threat types, e.g. ransomware, fire or human error.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(50)) # Ej: 'Adversarial', 'Accidental', 'Structural', 'Environmental'
    description = db.Column(db.Text)
    
    # Reverse relationship
    risks = db.relationship('Risk', backref='threat_type', lazy=True)

    def __repr__(self):
        return f'<ThreatType {self.name}>'

class RiskCatalog(db.Model):
    """
    Library of standard risks (e.g., MAGERIT, ISO 27005 Catalog).
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.String(50))
    description = db.Column(db.Text)
    is_custom = db.Column(db.Boolean, default=True)
    
    # Relationships
    catalog_risks = db.relationship('CatalogRisk', backref='catalog', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)

    def __repr__(self):
        return f'<RiskCatalog {self.name}>'

class CatalogRisk(db.Model):
    """
    A template risk item within a catalog.
    """
    id = db.Column(db.Integer, primary_key=True)
    catalog_id = db.Column(db.Integer, db.ForeignKey('risk_catalog.id'), nullable=False)
    
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Taxonomy
    threat_type_id = db.Column(db.Integer, db.ForeignKey('threat_type.id'))
    threat_type = db.relationship('ThreatType')
    
    # Suggested base scores (can be overridden on import)
    suggested_impact = db.Column(db.Integer, default=5)
    suggested_likelihood = db.Column(db.Integer, default=5)

    def __repr__(self):
        return f'<CatalogRisk {self.name}>'

class Risk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    risk_description = db.Column(db.Text, nullable=False)  # Short name/title
    extended_description = db.Column(db.Text, nullable=True)  # Detailed explanation
    
    # --- NUEVO CAMPO: Amenaza ---
    threat_type_id = db.Column(db.Integer, db.ForeignKey('threat_type.id'), nullable=True)
    
    # Import Source Tracking
    source_catalog_risk_id = db.Column(db.Integer, db.ForeignKey('catalog_risk.id'), nullable=True)
    source_catalog_risk = db.relationship('CatalogRisk')
    
    # Management
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    owner = db.relationship('User', foreign_keys=[owner_id])

    status = db.Column(db.String(50), default='Identified', index=True) # Identified, Assessed, In Treatment, Mitigated, Accepted, Closed
    treatment_strategy = db.Column(db.String(50)) # Mitigate, Accept, Transfer, Avoid
    next_review_date = db.Column(db.Date)
    
    # Quantitative Scoring (1-5)
    inherent_impact = db.Column(db.Integer, default=5)
    inherent_likelihood = db.Column(db.Integer, default=5)
    
    residual_impact = db.Column(db.Integer, default=5)
    residual_likelihood = db.Column(db.Integer, default=5)
    
    mitigation_plan = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=lambda: now())
    link = db.Column(db.String(512))
    
    # Relationships
    affected_items = db.relationship('RiskAffectedItem', backref='risk', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    # Context & References (Policy, Documentation, Link)
    references = db.relationship('RiskReference', backref='risk', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    # Multiple categories (CIA Triad + extended)
    categories = db.relationship(
        'RiskCategory',
        backref='risk',
        lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN
    )
    
    # Mitigation activities (Many-to-Many with SecurityActivity)
    mitigation_activities = db.relationship(
        'SecurityActivity',
        secondary=risk_mitigation_activities,
        backref=db.backref('mitigated_risks', lazy=LAZY_DYNAMIC),
        lazy=LAZY_DYNAMIC
    )
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Risk.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Risk')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(Risk.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='Risk')",
                            lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="compliance_links")

    @property
    def inherent_score(self):
        return (self.inherent_impact or 0) * (self.inherent_likelihood or 0)

    @property
    def residual_score(self):
        return (self.residual_impact or 0) * (self.residual_likelihood or 0)

    @property
    def criticality_level(self):
        score = self.residual_score
        if score >= 20:
            return 'Critical'
        elif score >= 15:
            return 'High'
        elif score >= 5:
            return 'Medium'
        return 'Low'

    @property
    def is_overdue(self):
        if self.next_review_date and self.next_review_date < today():
            return True
        return False

    @property
    def risk_reduction_percentage(self):
        if self.inherent_score > 0:
            reduction = self.inherent_score - self.residual_score
            return round((reduction / self.inherent_score) * 100, 1)
        return 0.0

    @property
    def category_list(self):
        """Return list of category names for this risk."""
        return [c.category for c in self.categories]

    @property
    def affected_asset_ids(self):
        """Return list of IDs of affected assets."""
        return [item.linkable_id for item in self.affected_items if item.linkable_type == 'Asset']

    def get_category_colors(self):
        """Return dict of category name -> Bootstrap color class."""
        return {c.category: RISK_CATEGORY_COLORS.get(c.category, 'secondary') for c in self.categories}


class RiskCategory(db.Model):
    """Stores multiple categories for a single Risk."""
    __tablename__ = 'risk_category'
    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)


class RiskHistory(db.Model):
    """
    Audit trail for tracking changes to Risk fields.
    Automatically populated via SQLAlchemy event listener.
    """
    __tablename__ = 'risk_history'
    id = db.Column(db.Integer, primary_key=True)
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: now(), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.String(500))
    new_value = db.Column(db.String(500))

    # Relationships
    risk = db.relationship('Risk', backref=db.backref('history', lazy=LAZY_DYNAMIC, order_by='RiskHistory.timestamp.desc()'))
    user = db.relationship('User')

    def __repr__(self):
        return f'<RiskHistory {self.risk_id}: {self.field_changed} {self.old_value} -> {self.new_value}>'


# --- Event Listener for Risk Audit Trail ---
from sqlalchemy import event
from flask import session as flask_session, has_request_context


# Fields to track for audit
RISK_TRACKED_FIELDS = [
    'inherent_impact', 'inherent_likelihood', 
    'residual_impact', 'residual_likelihood',
    'status', 'treatment_strategy'
]

@event.listens_for(Risk, 'before_update')
def risk_before_update(mapper, connection, target):
    """
    Capture changes to tracked fields and insert audit records.
    Uses raw connection to avoid session conflicts.
    """
    state = db.inspect(target)
    
    for field in RISK_TRACKED_FIELDS:
        hist = state.attrs[field].history
        if hist.has_changes():
            old_val = hist.deleted[0] if hist.deleted else None
            new_val = hist.added[0] if hist.added else getattr(target, field)
            
            # Skip if values are actually the same (type coercion edge case)
            if str(old_val) == str(new_val):
                continue
            
            # Get current user from Flask session if available
            user_id = None
            if has_request_context():
                user_id = flask_session.get('user_id')
            
            # Insert directly via connection to avoid session issues
            connection.execute(
                RiskHistory.__table__.insert().values(
                    risk_id=target.id,
                    user_id=user_id,
                    field_changed=field,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None
                )
            )


class SecurityAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_date = db.Column(db.Date, nullable=False, default=lambda: today())
    status = db.Column(db.String(50), default='Pending Review') # Pending Review, Approved, Rejected
    notes = db.Column(db.Text)
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(SecurityAssessment.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='SecurityAssessment')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(SecurityAssessment.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='SecurityAssessment')",
                            lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="compliance_links")

class AssetInventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    conducted_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_completed = db.Column(db.Boolean, default=False)

    # Relationship to all items in this inventory
    items = db.relationship('AssetInventoryItem', backref='inventory', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    conducted_by = db.relationship('User')

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(AssetInventory.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='AssetInventory')",
                            lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="compliance_links")

class AssetInventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('asset_inventory.id'), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # The user assigned at time of inventory
    status = db.Column(db.String(50), nullable=False) # e.g., 'Verified', 'Flagged'
    notes = db.Column(db.Text)
    event_time = db.Column(db.DateTime, default=lambda: now())

    # Relationships to get details in templates
    asset = db.relationship('Asset')
    user = db.relationship('User')

class Framework(db.Model):
    """
    Representa un marco de trabajo o normativa (ej. ISO27001, ITIL).
    """
    __tablename__ = 'framework'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    
    # Description
    description = db.Column(db.Text)
    
    # <-- REQUISITO: Enlace a web externa
    link = db.Column(db.String(1024))
    
    # Distinguishes the built-in frameworks, which are not editable
    is_custom = db.Column(db.Boolean, default=True, nullable=False)
    
    # Enables or disables the framework for the organisation
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # --- Relaciones ---

    # The framework's controls
    framework_controls = db.relationship(
        'FrameworkControl', 
        backref='framework', 
        lazy=LAZY_DYNAMIC, 
        cascade=CASCADE_ALL_DELETE_ORPHAN
    )
    
    # Attachments, for manuals and similar documents
    # Relies on Attachment being set up for polymorphic links
    attachments = db.relationship(
        'Attachment', 
        # Wrapped in a lambda so Python functions can be used in the expression
        primaryjoin=lambda: and_(
            # The key part: telling SQLAlchemy that 'linkable_id' is the column
            # acting as the foreign key.
            foreign(Attachment.linkable_id) == Framework.id,
            Attachment.linkable_type == 'Framework'
        ),
        lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="attachments" 
    )

    # Future relationship with audits
    # audits = db.relationship('Audit', backref='framework', lazy='dynamic')

    def __repr__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f'<Framework {self.id}: {self.name} ({status})>'


# Association table for cross-framework control mappings (self-referential)
control_mappings = db.Table('control_mappings',
    db.Column('source_control_id', db.Integer, db.ForeignKey('framework_control.id'), primary_key=True),
    db.Column('target_control_id', db.Integer, db.ForeignKey('framework_control.id'), primary_key=True)
)


class FrameworkControl(db.Model):
    """
    A single control or practice within a framework.
    """
    __tablename__ = 'framework_control'
    
    id = db.Column(db.Integer, primary_key=True)
    framework_id = db.Column(db.Integer, db.ForeignKey('framework.id'), nullable=False)
    
    # Control identifier, e.g. "A.5.7"
    control_id = db.Column(db.String(100), nullable=False) 
    
    name = db.Column(db.String(512), nullable=False)
    
    # Control-specific description
    description = db.Column(db.Text)

    # --- SOA (Statement of Applicability) ---
    is_applicable = db.Column(db.Boolean, default=True, nullable=False)
    soa_justification = db.Column(db.Text)  # Required when is_applicable = False

    # Cross-Framework Mappings: Controls this one maps to (e.g., DORA -> ISO)
    mapped_targets = db.relationship(
        'FrameworkControl',
        secondary=control_mappings,
        primaryjoin="FrameworkControl.id==control_mappings.c.source_control_id",
        secondaryjoin="FrameworkControl.id==control_mappings.c.target_control_id",
        backref=db.backref('mapped_sources', lazy=LAZY_DYNAMIC)
    )

    def get_all_mappings(self):
        """Related controls, incoming and outgoing, as a single list."""
        targets = self.mapped_targets
        sources = list(self.mapped_sources)
        # Combine and deduplicate
        return list(set(targets + sources))

    def __repr__(self):
        return f'<FrameworkControl {self.id}: {self.control_id}>'


class ComplianceRule(db.Model):
    """
    Declarative rule for automated compliance checking.
    Links a FrameworkControl to a target model (e.g., ActivityExecution, Campaign)
    with filter criteria and SLA timing for traffic-light status.
    """
    __tablename__ = 'compliance_rule'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relationship with the Control (Parent)
    framework_control_id = db.Column(db.Integer, db.ForeignKey('framework_control.id'), nullable=False)
    
    # Metadata
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    
    # Selection Logic (Declarative Polymorphism)
    # Examples: 'ActivityExecution', 'Campaign', 'BCDRTestLog'
    target_model = db.Column(db.String(50), nullable=False)
    # JSON string with filters, e.g. {"activity_name": "Quarterly User Access Review"}
    criteria = db.Column(db.Text, nullable=False, default='{}')
    
    # SLA Logic (Traffic Light)
    frequency_days = db.Column(db.Integer, nullable=False, default=90)  # Ideal frequency (Green)
    grace_period_days = db.Column(db.Integer, nullable=False, default=7)  # Buffer zone (Yellow)
    
    # State
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    
    # Relationships
    control = db.relationship('FrameworkControl', backref=db.backref('rules', lazy=LAZY_DYNAMIC))
    
    @property
    def total_sla_days(self):
        """Returns the absolute limit of days before considering non-compliance (Red)."""
        return self.frequency_days + self.grace_period_days
    
    def get_criteria(self):
        """Helper to get the criteria dict from JSON text."""
        import json
        try:
            return json.loads(self.criteria) if self.criteria else {}
        except ValueError:
            return {}
    
    def set_criteria(self, criteria_dict):
        """Helper to save the dict as JSON text."""
        import json
        self.criteria = json.dumps(criteria_dict)
    
    def __repr__(self):
        return f'<ComplianceRule {self.id}: {self.name} -> {self.target_model}>'
