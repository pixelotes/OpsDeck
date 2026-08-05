from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from src.utils.timezone_helper import today, now


class Contract(db.Model):
    __tablename__ = 'contract'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default='Active') # Options: Active, Expired, Draft, Terminated
    contract_type = db.Column(db.String(100)) # e.g. NDA, MSA, SLA, Lease, Support
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    supplier = db.relationship('Supplier', backref='contracts')
    
    # Contacts (Optional: simple string or Many-to-Many if strict link needed. String is often sufficient for reference)
    contact_email = db.Column(db.String(120)) 
    
    # Financials
    cost = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(3), default='EUR')
    payment_frequency = db.Column(db.String(50)) # Monthly, Yearly, One-time
    
    # Lifecycle
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    notice_period_days = db.Column(db.Integer, default=30) # Alert trigger
    is_auto_renew = db.Column(db.Boolean, default=False)
    renewal_notes = db.Column(db.Text)
    
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Relationships
    # 1. Polymorphic Attachments (Reuse existing system)
    attachments = db.relationship('Attachment',
        primaryjoin="and_(Contract.id==foreign(Attachment.linkable_id), "
                    "Attachment.linkable_type=='Contract')",
        lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="attachments")
        
    # 2. Linked Items (The Reverse Polymorphic Link)
    items = db.relationship('ContractItem', backref='contract', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)

    @property
    def is_active(self):
        # Handle cases where dates might be None (though schema says nullable=False, nice to be safe)
        if not self.start_date or not self.end_date:
            return False
        return self.start_date <= today() <= self.end_date

    @property
    def days_until_expiry(self):
        if not self.end_date: return 9999
        return (self.end_date - today()).days


class ContractItem(db.Model):
    """
    Links a Contract to ANY item (Asset, Subscription, etc.)
    """
    __tablename__ = 'contract_item'
    
    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    
    # Polymorphic Foreign Key
    item_id = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(50), nullable=False) # 'Asset', 'Subscription', 'License', 'BusinessService'
    
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def item(self):
        """Resolves the actual object based on item_type."""
        # Local imports to prevent circular dependency
        if self.item_type == 'Asset':
            from .assets import Asset
            return db.session.get(Asset, self.item_id)
        elif self.item_type == 'Subscription':
            from .procurement import Subscription
            return db.session.get(Subscription, self.item_id)
        elif self.item_type == 'License':
            from .assets import License
            return db.session.get(License, self.item_id)
        elif self.item_type == 'BusinessService':
            from .services import BusinessService
            return db.session.get(BusinessService, self.item_id)
        return None
