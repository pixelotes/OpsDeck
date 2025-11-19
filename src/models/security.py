from datetime import datetime, date
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment
from .auth import User

class ComplianceLink(db.Model):
    """
    Tabla de asociación polimórfica.
    Vincula un control (ej. 'A.5.7') con un objeto 
    (ej. un Asset, una Policy) y explica CÓMO lo cumple.
    """
    __tablename__ = 'compliance_link'
    id = db.Column(db.Integer, primary_key=True)
    
    # Lado 1: El control que se está cumpliendo
    framework_control_id = db.Column(db.Integer, db.ForeignKey('framework_control.id'), nullable=False)
    
    # Lado 2: El objeto polimórfico que cumple el control
    linkable_id = db.Column(db.Integer, nullable=False, index=True)
    linkable_type = db.Column(db.String(50), nullable=False, index=True)

    description = db.Column(db.Text, nullable=False)

    # --- Relaciones ---
    
    # Back-reference para que desde FrameworkControl podamos ver los links
    framework_control = db.relationship(
        'FrameworkControl',
        backref=db.backref('compliance_links', lazy='dynamic', cascade='all, delete-orphan')
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
            'Risk': Risk,
            'AssetInventory': AssetInventory
        }
        
        model = model_map.get(self.linkable_type)
        if model:
            return model.query.get(self.linkable_id)
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

class SecurityIncident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    incident_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Investigating') # Investigating, Contained, Resolved, Closed
    severity = db.Column(db.String(50), default='SEV-3') # SEV-0 (Critical) to SEV-3 (Low)
    impact = db.Column(db.String(50), default='Minor') # Minor, Moderate, Significant, Extensive
    data_breach = db.Column(db.Boolean, default=False)
    third_party_impacted = db.Column(db.Boolean, default=False)
    review = db.relationship('PostIncidentReview', backref='incident', uselist=False, cascade='all, delete-orphan')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    
    # Relationships
    reported_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    reported_by = db.relationship('User', foreign_keys=[reported_by_id])
    owner = db.relationship('User', foreign_keys=[owner_id])
    
    affected_assets = db.relationship('Asset', secondary=incident_assets, backref='incidents')
    affected_users = db.relationship('User', secondary=incident_users, backref='incidents')
    affected_subscriptions = db.relationship('Subscription', secondary=incident_subscriptions, backref='incidents')
    affected_suppliers = db.relationship('Supplier', secondary=incident_suppliers, backref='incidents')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(SecurityIncident.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='SecurityIncident')",
                            lazy=True, cascade='all, delete-orphan')
    
    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(SecurityIncident.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='SecurityIncident')",
                            lazy='dynamic', cascade='all, delete-orphan')

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    timeline_events = db.relationship('IncidentTimelineEvent', backref='review', lazy=True, cascade='all, delete-orphan', order_by='IncidentTimelineEvent.order')

class IncidentTimelineEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('post_incident_review.id'), nullable=False)
    event_time = db.Column(db.DateTime, nullable=False)
    description = db.Column(db.Text, nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

risk_assets = db.Table('risk_assets',
    db.Column('risk_id', db.Integer, db.ForeignKey('risk.id'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('asset.id'), primary_key=True)
)

class Risk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    risk_description = db.Column(db.Text, nullable=False)
    
    # Management
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    owner = db.relationship('User', foreign_keys=[owner_id])
    
    status = db.Column(db.String(50), default='Identified') # Identified, Assessed, In Treatment, Mitigated, Accepted, Closed
    treatment_strategy = db.Column(db.String(50)) # Mitigate, Accept, Transfer, Avoid
    next_review_date = db.Column(db.Date)
    
    # Quantitative Scoring (1-5)
    inherent_impact = db.Column(db.Integer, default=5)
    inherent_likelihood = db.Column(db.Integer, default=5)
    
    residual_impact = db.Column(db.Integer, default=5)
    residual_likelihood = db.Column(db.Integer, default=5)
    
    mitigation_plan = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(512))
    
    # Relationships
    assets = db.relationship('Asset', secondary=risk_assets, backref='risks', lazy='dynamic')
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Risk.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Risk')",
                            lazy=True, cascade='all, delete-orphan')

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(Risk.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='Risk')",
                            lazy='dynamic', cascade='all, delete-orphan')

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
        if self.next_review_date and self.next_review_date < date.today():
            return True
        return False

    @property
    def risk_reduction_percentage(self):
        if self.inherent_score > 0:
            reduction = self.inherent_score - self.residual_score
            return round((reduction / self.inherent_score) * 100, 1)
        return 0.0

class SecurityAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(50), default='Pending Review') # Pending Review, Approved, Rejected
    notes = db.Column(db.Text)
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(SecurityAssessment.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='SecurityAssessment')",
                            lazy=True, cascade='all, delete-orphan')

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(SecurityAssessment.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='SecurityAssessment')",
                            lazy='dynamic', cascade='all, delete-orphan')

class AssetInventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conducted_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_completed = db.Column(db.Boolean, default=False)

    # Relationship to all items in this inventory
    items = db.relationship('AssetInventoryItem', backref='inventory', lazy='dynamic', cascade='all, delete-orphan')
    conducted_by = db.relationship('User')

    compliance_links = db.relationship('ComplianceLink',
                            primaryjoin="and_(AssetInventory.id==foreign(ComplianceLink.linkable_id), "
                                        "ComplianceLink.linkable_type=='AssetInventory')",
                            lazy='dynamic', cascade='all, delete-orphan')

class AssetInventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inventory_id = db.Column(db.Integer, db.ForeignKey('asset_inventory.id'), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # The user assigned at time of inventory
    status = db.Column(db.String(50), nullable=False) # e.g., 'Verified', 'Flagged'
    notes = db.Column(db.Text)
    event_time = db.Column(db.DateTime, default=datetime.utcnow)

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
    
    # <-- REQUISITO: Descripción
    description = db.Column(db.Text)
    
    # <-- REQUISITO: Enlace a web externa
    link = db.Column(db.String(1024))
    
    # Flag para diferenciar los 'built-in' (no editables)
    is_custom = db.Column(db.Boolean, default=True, nullable=False)
    
    # <-- ¡NUEVO! REQUISITO: Para activar/desactivar el framework en la org
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # --- Relaciones ---

    # Relación con los controles del marco
    framework_controls = db.relationship(
        'FrameworkControl', 
        backref='framework', 
        lazy='dynamic', 
        cascade='all, delete-orphan'
    )
    
    # <-- REQUISITO: Soporte para attachments (manuales, etc.)
    # (Asumiendo que tu modelo Attachment está configurado para polimorfismo)
    attachments = db.relationship(
        'Attachment', 
        # Convertimos el string a una lambda para poder usar funciones de Python
        primaryjoin=lambda: and_(
            # ¡LA CLAVE ESTÁ AQUÍ! Le decimos a SQLAlchemy que 'linkable_id'
            # es la columna que actúa como clave foránea.
            foreign(Attachment.linkable_id) == Framework.id,
            Attachment.linkable_type == 'Framework'
        ),
        lazy='dynamic',
        cascade='all, delete-orphan',
        overlaps="attachments" 
    )

    # Relación futura con Auditorías
    # audits = db.relationship('Audit', backref='framework', lazy='dynamic')

    def __repr__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f'<Framework {self.id}: {self.name} ({status})>'


class FrameworkControl(db.Model):
    """
    Representa un control individual o práctica dentro de un Framework.
    """
    __tablename__ = 'framework_control'
    
    id = db.Column(db.Integer, primary_key=True)
    framework_id = db.Column(db.Integer, db.ForeignKey('framework.id'), nullable=False)
    
    # Identificador del control (ej. "A.5.7")
    control_id = db.Column(db.String(100), nullable=False) 
    
    name = db.Column(db.String(512), nullable=False)
    
    # Descripción específica del control
    description = db.Column(db.Text)
    
    # Relación futura con los controles de una auditoría específica
    # audit_controls = db.relationship('AuditControl', backref='base_control', lazy='dynamic')

    def __repr__(self):
        return f'<FrameworkControl {self.id}: {self.control_id}>'
    

