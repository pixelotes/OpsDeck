from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN

# --- PLANTILLAS Y CONFIGURACIÓN ---

class ProcessTemplate(db.Model):
    """Templates for global static tasks, e.g. 'Exit interview' or 'Sign NDA'."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    process_type = db.Column(db.String(50), default='offboarding') # 'onboarding' o 'offboarding'
    is_active = db.Column(db.Boolean, default=True)

class OnboardingPack(db.Model):
    """Container for role profiles, e.g. 'Pack Developer' or 'Pack Sales'."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    
    items = db.relationship('PackItem', backref='pack', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)

class PackItem(db.Model):
    """Elementos definidos dentro de un pack de onboarding."""
    id = db.Column(db.Integer, primary_key=True)
    pack_id = db.Column(db.Integer, db.ForeignKey('onboarding_pack.id'), nullable=False, index=True)
    
    # Tipo: 'Software', 'Hardware', 'Task'
    item_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    
    # Software items are linked so the later assignment is straightforward
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)
    software = db.relationship('Software')

    service_id = db.Column(db.Integer, db.ForeignKey('business_service.id'), nullable=True, index=True)
    service = db.relationship('BusinessService')

    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=True, index=True)
    subscription = db.relationship('Subscription')

    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True, index=True)
    course = db.relationship('Course')


# --- PROCESOS DE EJECUCIÓN ---

class OnboardingProcess(db.Model):
    """A record of one onboarding."""
    id = db.Column(db.Integer, primary_key=True)
    external_ref = db.Column(db.String(255), unique=True, nullable=True, index=True)
    new_hire_name = db.Column(db.String(100), nullable=False) # Placeholder name while there is no User yet
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True) # Se enlaza al crear el usuario
    
    # Optional: Email to use when creating the user, overrides auto-generation
    target_email = db.Column(db.String(120), nullable=True)
    
    # Personal email for pre-start communications
    personal_email = db.Column(db.String(120), nullable=True)

    start_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='Provisioning') # Provisioning, Completed
    
    pack_id = db.Column(db.Integer, db.ForeignKey('onboarding_pack.id'), index=True)
    pack = db.relationship('OnboardingPack')
    
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Pre-assignment of roles (Manager & Buddy)
    assigned_manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    assigned_buddy_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)

    assigned_manager = db.relationship('User', foreign_keys=[assigned_manager_id])
    assigned_buddy = db.relationship('User', foreign_keys=[assigned_buddy_id])
    
    # Checklist items
    items = db.relationship('ProcessItem', backref='onboarding_process', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)
    user = db.relationship('User', foreign_keys=[user_id])

class OffboardingProcess(db.Model):
    """Registro de una salida."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True) # Who carries out the offboarding
    
    departure_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), default='In Progress') # In Progress, Completed
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())

    # Relaciones
    user = db.relationship('User', foreign_keys=[user_id], backref='offboardings')
    manager = db.relationship('User', foreign_keys=[manager_id])
    
    # Checklist items
    items = db.relationship('ProcessItem', backref='offboarding_process', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)

class ProcessItem(db.Model):
    """
    A single checklist line.
    Puede pertenecer a un Onboarding O a un Offboarding.
    """
    id = db.Column(db.Integer, primary_key=True)
    
    # Optional FKs: exactly one of the two is expected to be set
    onboarding_process_id = db.Column(db.Integer, db.ForeignKey('onboarding_process.id'), nullable=True, index=True)
    offboarding_process_id = db.Column(db.Integer, db.ForeignKey('offboarding_process.id'), nullable=True, index=True)
    
    description = db.Column(db.String(255), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    
    # Metadata recording where the item came from, so it can link back to it
    item_type = db.Column(db.String(50)) # 'Asset', 'Peripheral', 'License', 'StaticTask', 'SoftwareProvision'
    
    # Id of the underlying object where applicable, e.g. the asset to hand back.
    linked_object_id = db.Column(db.Integer, nullable=True)