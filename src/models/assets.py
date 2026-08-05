from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .auth import User, Group
from .core import CustomPropertiesMixin
from src.utils.timezone_helper import today, now


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    assets = db.relationship('Asset', backref='location', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # Physical address fields (optional - if filled, this is a physical site)
    address = db.Column(db.String(255))
    city = db.Column(db.String(100))
    zip_code = db.Column(db.String(20))
    country = db.Column(db.String(100))

    # Timezone for scheduled tasks respecting local time
    timezone = db.Column(db.String(50))  # e.g., 'Europe/Madrid', 'America/New_York'

    # Legal override (for subsidiaries with different tax ID)
    tax_id_override = db.Column(db.String(50))

    # Contact info
    phone = db.Column(db.String(50))
    reception_email = db.Column(db.String(120))

    @property
    def is_physical_site(self):
        """Returns True if this location has physical address info."""
        return bool(self.address or self.city or self.country)

class Brand(db.Model):
    """Manufacturer/brand of an asset or peripheral (e.g. Dell, Samsung, ASUS).
    Distinct from Supplier (commercial entity you buy from): the same product
    can come from different suppliers, and a supplier is not always the brand.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    website = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: now())

    models = db.relationship(
        'AssetModel', backref='brand', lazy=True,
        cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='AssetModel.name'
    )
    assets = db.relationship('Asset', backref='brand', lazy=True)
    peripherals = db.relationship('Peripheral', backref='brand', lazy=True)

    def __repr__(self):
        return f'<Brand {self.name}>'


class AssetModel(db.Model):
    """Specific product model under a brand (e.g. Dell XPS 13, Samsung C27F390).
    A Brand has many AssetModels; a model belongs to exactly one Brand.
    Shared by Asset and Peripheral.
    """
    __tablename__ = 'asset_model'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: now())

    assets = db.relationship('Asset', backref='model', lazy=True)
    peripherals = db.relationship('Peripheral', backref='model', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('brand_id', 'name', name='uq_asset_model_brand_name'),
    )

    def __repr__(self):
        return f'<AssetModel {self.name} (brand_id={self.brand_id})>'


class Asset(db.Model, CustomPropertiesMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=True, index=True)
    model_id = db.Column(db.Integer, db.ForeignKey('asset_model.id'), nullable=True, index=True)
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50), nullable=False, default='In Use', index=True)
    internal_id = db.Column(db.String(100), unique=True)
    comments = db.Column(db.Text)
    purchase_date = db.Column(db.Date)

    # --- UPDATED FIELDS ---
    cost = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')

    warranty_length = db.Column(db.Integer) # in months
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)

    # --- NEW FIELDS: Critical and Virtual indicators ---
    is_critical = db.Column(db.Boolean, default=False, nullable=False)
    is_virtual = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), index=True)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Asset.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Asset')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")
    
    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Asset.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Asset'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )
    history = db.relationship('AssetHistory', backref='asset', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='AssetHistory.changed_at.desc()')
    peripherals = db.relationship('Peripheral', backref='asset', lazy=True)
    assignments = db.relationship('AssetAssignment', backref='asset', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='AssetAssignment.checked_out_date.desc()')
    maintenance_logs = db.relationship('MaintenanceLog', backref='asset', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    disposal_record = db.relationship('DisposalRecord', backref='asset', uselist=False, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def warranty_end_date(self):
        if self.purchase_date and self.warranty_length:
            return self.purchase_date + relativedelta(months=+self.warranty_length)
        return None

    @property
    def linked_risks(self):
        """Returns all active risks linked to this asset via RiskAffectedItem."""
        from .security import RiskAffectedItem, Risk
        items = RiskAffectedItem.query.filter_by(
            linkable_type='Asset',
            linkable_id=self.id
        ).all()
        risk_ids = [item.risk_id for item in items]
        if not risk_ids:
            return []
        return Risk.query.filter(
            Risk.id.in_(risk_ids),
            Risk.status != 'Closed'
        ).all()

    @property
    def contracts(self):
        """Returns active contracts linked to this specific item."""
        from .contracts import Contract, ContractItem
        return Contract.query.join(ContractItem).filter(
            ContractItem.item_type == self.__class__.__name__, # e.g., 'Asset'
            ContractItem.item_id == self.id
        ).all()

    @property
    def max_risk_score(self):
        """Returns the highest residual_score among linked risks, or 0 if none."""
        risks = self.linked_risks
        if not risks:
            return 0
        return max(r.residual_score for r in risks)

    @property
    def location_display(self):
        """
        Hybrid location display:
        1. If has physical location, show location name
        2. If no location but has user, show 'User Name (Remote)'
        3. Otherwise, 'Unassigned / Stock'
        """
        if self.location:
            return self.location.name
        elif self.user:
            return f"📍 {self.user.name} (Remote)"
        else:
            return "Unassigned / Stock"

    def get_tickets(self):
        """
        Aggregates all related tickets:
        - Changes
        - Maintenance Logs
        - Disposal Record
        Returns a sorted list (by date desc) of dicts:
        {
            'type': 'Change'|'Maintenance'|'Disposal',
            'title': str,
            'status': str,
            'date': datetime,
            'url': str,
            'tags': list[str] (names),
            'obj': object (optional)
        }
        """
        tickets = []
        
        # 1. Changes
        for change in self.changes:
            tickets.append({
                'type': 'Change',
                'category': change.change_type, # Standard, Normal, Emergency
                'title': change.title,
                'status': change.status,
                'date': change.created_at,
                'url': f"/changes/{change.id}",
                'tags': [t.name for t in change.tags],
                'id': change.id,
                'assignee': change.assignee.name if change.assignee else None
            })

        # 2. Maintenance Logs
        for log in self.maintenance_logs:
            tickets.append({
                'type': 'Maintenance',
                'category': log.event_type, # Repair, Planned, etc.
                'title': log.description,
                'status': log.status,
                'date': datetime.combine(log.event_date, datetime.min.time()),
                'url': f"/maintenance/{log.id}/edit",
                'tags': [], 
                'id': log.id,
                'assignee': log.assigned_to.name if log.assigned_to else None
            })

        # 3. Disposal Record
        if self.disposal_record:
            rec = self.disposal_record
            tickets.append({
                'type': 'Disposal',
                'category': rec.disposal_method,
                'title': f"Disposal: {rec.disposal_method}",
                'status': 'Closed',
                'date': datetime.combine(rec.disposal_date, datetime.min.time()),
                'url': f"/disposal/{rec.id}",
                'tags': [],
                'id': rec.id,
                'assignee': None
            })
            
        # Sort by date descending
        tickets.sort(key=lambda x: x['date'], reverse=True)
        return tickets

class AssetAssignment(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Can be unassigned
    checked_out_date = db.Column(db.DateTime, default=lambda: now())
    checked_in_date = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    user = db.relationship('User', backref='assignments')

class AssetHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    changed_at = db.Column(db.DateTime, default=lambda: now())

class PeripheralAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Can be unassigned
    checked_out_date = db.Column(db.DateTime, default=lambda: now())
    checked_in_date = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text)
    user = db.relationship('User', backref='peripheral_assignments')

class Peripheral(db.Model, CustomPropertiesMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50))
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50), nullable=False, default='In Use', index=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    maintenance_logs = db.relationship('MaintenanceLog', backref='peripheral', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    disposal_record = db.relationship('DisposalRecord', backref='peripheral', uselist=False, cascade=CASCADE_ALL_DELETE_ORPHAN)

    # --- ADDED/UPDATED FIELDS ---
    brand_id = db.Column(db.Integer, db.ForeignKey('brand.id'), nullable=True, index=True)
    model_id = db.Column(db.Integer, db.ForeignKey('asset_model.id'), nullable=True, index=True)
    purchase_date = db.Column(db.Date)
    warranty_length = db.Column(db.Integer) # in months

    # --- COSTS ---
    cost = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)

    # Relationships
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    
    assignments = db.relationship('PeripheralAssignment', backref='peripheral', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='PeripheralAssignment.checked_out_date.desc()')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Peripheral.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Peripheral')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Peripheral.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Peripheral'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )
    
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    def __init__(self, **kwargs):
        super(Peripheral, self).__init__(**kwargs)
        if self.serial_number == '':
            self.serial_number = None

    @property
    def warranty_end_date(self):
        if self.purchase_date and self.warranty_length:
            return self.purchase_date + relativedelta(months=+self.warranty_length)
        return None

    @property
    def location_display(self):
        """
        Hybrid location display for peripherals:
        1. If has user assigned, show 'User Name (Assigned)'
        2. If attached to an asset, use asset's location_display
        3. Otherwise, 'Unassigned / Stock'
        """
        if self.user:
            return f"📍 {self.user.name} (Assigned)"
        elif self.asset:
            return self.asset.location_display
        else:
            return "Unassigned / Stock"

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
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True) # Assigned user (seat)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=True, index=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=True, index=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=True, index=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)

    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: now())

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == License.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'License'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    @property
    def status(self):
        current_date = today()
        if self.expiry_date and self.expiry_date < current_date:
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
    subscriptions = db.relationship('Subscription', backref='software', lazy=LAZY_DYNAMIC)
    licenses = db.relationship('License', backref='software', lazy=LAZY_DYNAMIC)
    
    supplier = db.relationship('Supplier', backref='software')

    # ISO 27001 Compliance Field
    iso_27001_control_references = db.Column(db.Text, nullable=True, comment="Relevant ISO 27001 controls, e.g., A.12.1.2, A.14.2.1")

    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Software.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Software'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    @property
    def owner(self):
        if self.owner_type == 'user' and self.owner_id:
            return db.session.get(User, self.owner_id)
        if self.owner_type == 'group' and self.owner_id:
            return db.session.get(Group, self.owner_id)
        return None

    def get_tickets(self):
        """
        Aggregates all related tickets:
        - Changes
        Returns a sorted list (by date desc) of dicts.
        """
        tickets = []
        
        # 1. Changes
        for change in self.changes:
            tickets.append({
                'type': 'Change',
                'category': change.change_type,
                'title': change.title,
                'status': change.status,
                'date': change.created_at,
                'url': f"/changes/{change.id}",
                'tags': [t.name for t in change.tags],
                'id': change.id
            })
            
        # Sort by date descending
        tickets.sort(key=lambda x: x['date'], reverse=True)
        return tickets

# Association table for MaintenanceLog tags
maintenance_log_tags = db.Table('maintenance_log_tags',
    db.Column('maintenance_log_id', db.Integer, db.ForeignKey('maintenance_log.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class MaintenanceLog(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(100), nullable=False) # e.g., Repair, Planned Maintenance, Unplanned Maintenance
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Open') # Open, In Progress, Completed, Cancelled
    event_date = db.Column(db.Date, nullable=False, default=lambda: today())
    ticket_link = db.Column(db.String(512))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: now())
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: now(), onupdate=lambda: now())
    
    # Relationships
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'))
    
    assigned_to = db.relationship('User', backref='maintenance_logs')
    tags = db.relationship('Tag', secondary=maintenance_log_tags, backref=db.backref('maintenance_logs', lazy=LAZY_DYNAMIC))

    attachments = db.relationship('Attachment',
                            primaryjoin="and_(MaintenanceLog.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='MaintenanceLog')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == MaintenanceLog.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'MaintenanceLog'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

class DisposalHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disposal_id = db.Column(db.Integer, db.ForeignKey('disposal_record.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    reason = db.Column(db.Text, nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    changed_at = db.Column(db.DateTime, default=lambda: now())
    
    changed_by = db.relationship('User')

class DisposalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    disposal_date = db.Column(db.Date, nullable=False, default=lambda: today())
    disposal_method = db.Column(db.String(100), nullable=False) # e.g., Recycled, Destroyed, Sold
    disposal_partner_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True, index=True)
    notes = db.Column(db.Text)

    disposal_partner = db.relationship('Supplier', backref='disposal_records')

    # Can only be linked to one item
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), unique=True)
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'), unique=True)
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(DisposalRecord.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='DisposalRecord')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    history = db.relationship('DisposalHistory', backref='disposal_record', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='DisposalHistory.changed_at.desc()')
