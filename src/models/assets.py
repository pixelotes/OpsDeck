from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment
from .auth import User, Group

class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assets = db.relationship('Asset', backref='location', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100))
    brand = db.Column(db.String(100))
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50), nullable=False, default='In Use')
    internal_id = db.Column(db.String(100), unique=True)
    comments = db.Column(db.Text)
    purchase_date = db.Column(db.Date)
    
    # --- UPDATED FIELDS ---
    cost = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    
    warranty_length = db.Column(db.Integer) # in months
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Asset.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Asset')",
                            lazy=True, cascade='all, delete-orphan')
    history = db.relationship('AssetHistory', backref='asset', lazy=True, cascade='all, delete-orphan', order_by='AssetHistory.changed_at.desc()')
    peripherals = db.relationship('Peripheral', backref='asset', lazy=True)
    assignments = db.relationship('AssetAssignment', backref='asset', lazy=True, cascade='all, delete-orphan', order_by='AssetAssignment.checked_out_date.desc()')
    maintenance_logs = db.relationship('MaintenanceLog', backref='asset', lazy='dynamic', cascade='all, delete-orphan')
    disposal_record = db.relationship('DisposalRecord', backref='asset', uselist=False, cascade='all, delete-orphan')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def warranty_end_date(self):
        if self.purchase_date and self.warranty_length:
            return self.purchase_date + relativedelta(months=+self.warranty_length)
        return None

class AssetAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Can be unassigned
    checked_out_date = db.Column(db.DateTime, default=datetime.utcnow)
    checked_in_date = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    user = db.relationship('User', backref='assignments')

class AssetHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

class PeripheralAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Can be unassigned
    checked_out_date = db.Column(db.DateTime, default=datetime.utcnow)
    checked_in_date = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    user = db.relationship('User', backref='peripheral_assignments')

class Peripheral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50))
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50), nullable=False, default='In Use')
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    maintenance_logs = db.relationship('MaintenanceLog', backref='peripheral', lazy='dynamic', cascade='all, delete-orphan')
    disposal_record = db.relationship('DisposalRecord', backref='peripheral', uselist=False, cascade='all, delete-orphan')
    
    # --- ADDED/UPDATED FIELDS ---
    brand = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    warranty_length = db.Column(db.Integer) # in months
    
    # --- COSTS ---
    cost = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relationships
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    
    assignments = db.relationship('PeripheralAssignment', backref='peripheral', lazy=True, cascade='all, delete-orphan', order_by='PeripheralAssignment.checked_out_date.desc()')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Peripheral.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Peripheral')",
                            lazy=True, cascade='all, delete-orphan')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __init__(self, **kwargs):
        super(Peripheral, self).__init__(**kwargs)
        if self.serial_number == '':
            self.serial_number = None

    @property
    def warranty_end_date(self):
        if self.purchase_date and self.warranty_length:
            return self.purchase_date + relativedelta(months=+self.warranty_length)
        return None

class License(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    license_key = db.Column(db.Text)
    
    # Financials
    cost = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    
    # Dates
    purchase_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date, nullable=True) # Optional for perpetual licenses

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # Assigned user (seat)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True)
    
    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status(self):
        today = date.today()
        if self.expiry_date and self.expiry_date < today:
            return "Expired"
        if self.user_id:
            return "In use"
        return "Available"

class Software(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    category = db.Column(db.String(100)) # e.g., 'Design', 'Productivity', 'Security'
    description = db.Column(db.Text)

    # Ownership
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50)) # 'user' or 'group'

    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)
    subscriptions = db.relationship('Subscription', backref='software', lazy='dynamic')
    licenses = db.relationship('License', backref='software', lazy='dynamic')
    
    supplier = db.relationship('Supplier', backref='software')

    # ISO 27001 Compliance Field
    iso_27001_control_references = db.Column(db.Text, nullable=True, comment="Relevant ISO 27001 controls, e.g., A.12.1.2, A.14.2.1")

    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def owner(self):
        if self.owner_type == 'user' and self.owner_id:
            return User.query.get(self.owner_id)
        if self.owner_type == 'group' and self.owner_id:
            return Group.query.get(self.owner_id)
        return None

class MaintenanceLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100), nullable=False) # e.g., Repair, Planned Maintenance, Unplanned Maintenance
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Open') # Open, In Progress, Completed, Cancelled
    event_date = db.Column(db.Date, nullable=False, default=date.today)
    ticket_link = db.Column(db.String(512))
    notes = db.Column(db.Text)
    
    # Relationships
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'))
    
    assigned_to = db.relationship('User', backref='maintenance_logs')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(MaintenanceLog.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='MaintenanceLog')",
                            lazy=True, cascade='all, delete-orphan')

class DisposalHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disposal_id = db.Column(db.Integer, db.ForeignKey('disposal_record.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    reason = db.Column(db.Text, nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    changed_by = db.relationship('User')

class DisposalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disposal_date = db.Column(db.Date, nullable=False, default=date.today)
    disposal_method = db.Column(db.String(100), nullable=False) # e.g., Recycled, Destroyed, Sold
    disposal_partner = db.Column(db.String(255))
    notes = db.Column(db.Text)

    # Can only be linked to one item
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), unique=True)
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'), unique=True)
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(DisposalRecord.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='DisposalRecord')",
                            lazy=True, cascade='all, delete-orphan')

    history = db.relationship('DisposalHistory', backref='disposal_record', lazy=True, cascade='all, delete-orphan', order_by='DisposalHistory.changed_at.desc()')
