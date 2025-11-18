from datetime import datetime, date
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment
from .auth import User

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

class Risk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    risk_description = db.Column(db.Text, nullable=False)
    risk_owner = db.Column(db.String(100))
    status = db.Column(db.String(50), default='Identified') # Identified, Assessed, In Treatment, Mitigated, Accepted
    likelihood = db.Column(db.String(50), default='Low') # Low, Medium, High
    impact = db.Column(db.String(50), default='Low') # Low, Medium, High
    mitigation_plan = db.Column(db.Text)
    iso_27001_control = db.Column(db.String(100)) # e.g., 'A.12.1.2 Protection against malware'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(512))
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Risk.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Risk')",
                            lazy=True, cascade='all, delete-orphan')

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

class Audit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    conducted_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_completed = db.Column(db.Boolean, default=False)

    # Relationship to all events in this audit
    events = db.relationship('AuditEvent', backref='audit', lazy='dynamic', cascade='all, delete-orphan')
    conducted_by = db.relationship('User')

class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('audit.id'), nullable=False)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # The user assigned at time of audit
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
