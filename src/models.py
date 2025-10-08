# src/models.py

import calendar
from .extensions import db
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash

# Currency conversion rates (EUR base)
CURRENCY_RATES = {
    'EUR': 1.0,
    'USD': 0.92,
    'GBP': 1.18
}


# --- Models ---
class AppUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True)
    department = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assets = db.relationship('Asset', backref='user', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    attachments = db.relationship('Attachment', backref='supplier', lazy=True, cascade='all, delete-orphan')
    
    # Relationships
    contacts = db.relationship('Contact', backref='supplier', lazy=True, cascade='all, delete-orphan')
    services = db.relationship('Service', backref='supplier', lazy=True)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)
    assets = db.relationship('Asset', backref='supplier', lazy=True)
    peripherals = db.relationship('Peripheral', backref='supplier', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(50))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

# Association table for Services and Tags
service_tags = db.Table('service_tags',
    db.Column('service_id', db.Integer, db.ForeignKey('service.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False) # Original filename
    secure_filename = db.Column(db.String(255), nullable=False, unique=True) # Stored filename
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign keys - one of these will be set
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'))

# Association table for many-to-many relationship between services and payments
service_payment_methods = db.Table('service_payment_methods',
    db.Column('service_id', db.Integer, db.ForeignKey('service.id'), primary_key=True),
    db.Column('payment_method_id', db.Integer, db.ForeignKey('payment_method.id'), primary_key=True)
)

# Association table for many-to-many relationship between services and contacts
service_contacts = db.Table('service_contacts',
    db.Column('service_id', db.Integer, db.ForeignKey('service.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'), primary_key=True),
)

class CostHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    # The date this cost became effective
    changed_date = db.Column(db.Date, nullable=False, default=date.today)

class PaymentMethod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Company Visa"
    method_type = db.Column(db.String(50), nullable=False)  # e.g., "Credit Card", "Bank Transfer"
    details = db.Column(db.String(100))  # e.g., "Visa ending in 1234"
    expiry_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)


    # Relationship back to Service (optional, but useful)
    services = db.relationship('Service', secondary=service_payment_methods, back_populates='payment_methods')
    purchases = db.relationship('Purchase', backref='payment_method', lazy=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    
    # Renewal information
    renewal_date = db.Column(db.Date, nullable=False)
    renewal_period_type = db.Column(db.String(20), nullable=False)
    renewal_period_value = db.Column(db.Integer, default=1)
    
    # NEW FIELD: Stores 'first', 'last', or a day number (e.g., '15') for monthly renewals
    monthly_renewal_day = db.Column(db.String(10), nullable=True)
    
    auto_renew = db.Column(db.Boolean, default=False)
    
    # Cost information
    cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='EUR')
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    contacts = db.relationship('Contact', secondary=service_contacts, backref='services')
    payment_methods = db.relationship('PaymentMethod', secondary=service_payment_methods, back_populates='services')
    attachments = db.relationship('Attachment', backref='service', lazy=True, cascade='all, delete-orphan')
    cost_history = db.relationship('CostHistory', backref='service', lazy=True, cascade='all, delete-orphan', order_by='CostHistory.changed_date')
    tags = db.relationship('Tag', secondary=service_tags, backref=db.backref('services', lazy='dynamic'))
    
    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def cost_eur(self):
        rate = CURRENCY_RATES.get(self.currency, 1.0)
        return self.cost * rate
    
    @property
    def next_renewal_date(self):
        """
        Calculates the next upcoming renewal date with advanced logic for
        specific monthly renewal days.
        """
        current_date = date.today()
        renewal_date = self.renewal_date
        
        while renewal_date < current_date:
            if self.renewal_period_type == 'monthly':
                # --- NEW: Advanced Monthly Logic ---
                # Move to the next month(s) first
                next_month = renewal_date + relativedelta(months=+self.renewal_period_value)
                
                day = next_month.day
                if self.monthly_renewal_day:
                    if self.monthly_renewal_day == 'first':
                        day = 1
                    elif self.monthly_renewal_day == 'last':
                        # Get the last day of that month
                        day = calendar.monthrange(next_month.year, next_month.month)[1]
                    else:
                        try:
                            # Use the specific day, but ensure it's valid for that month
                            day = int(self.monthly_renewal_day)
                            last_day_of_month = calendar.monthrange(next_month.year, next_month.month)[1]
                            day = min(day, last_day_of_month)
                        except (ValueError, TypeError):
                            pass # Fallback to original day if invalid
                
                renewal_date = next_month.replace(day=day)

            elif self.renewal_period_type == 'yearly':
                renewal_date += relativedelta(years=+self.renewal_period_value)
            else: # custom
                renewal_date += timedelta(days=self.renewal_period_value)
        
        return renewal_date
    
    def get_renewal_date_after(self, current_renewal):
        """
        Calculates the single next renewal date after a given date,
        applying all advanced monthly logic.
        """
        if self.renewal_period_type == 'monthly':
            # Move to the next month(s) first
            next_month_base = current_renewal + relativedelta(months=+self.renewal_period_value)
            
            day = next_month_base.day # Default to the same day in the next month
            if self.monthly_renewal_day:
                if self.monthly_renewal_day == 'first':
                    day = 1
                elif self.monthly_renewal_day == 'last':
                    # Get the last day of that month
                    day = calendar.monthrange(next_month_base.year, next_month_base.month)[1]
                else:
                    try:
                        # Use the specific day, but ensure it's valid for that month
                        day = int(self.monthly_renewal_day)
                        last_day_of_month = calendar.monthrange(next_month_base.year, next_month_base.month)[1]
                        day = min(day, last_day_of_month)
                    except (ValueError, TypeError):
                        pass # Fallback to original day if invalid
            
            return next_month_base.replace(day=day)

        elif self.renewal_period_type == 'yearly':
            return current_renewal + relativedelta(years=+self.renewal_period_value)
        else: # custom
            return current_renewal + timedelta(days=self.renewal_period_value)

class NotificationSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email_enabled = db.Column(db.Boolean, default=False)
    email_recipient = db.Column(db.String(120))
    webhook_enabled = db.Column(db.Boolean, default=False)
    webhook_url = db.Column(db.String(255))
    # We'll store the days as a comma-separated string, e.g., "30,14,7"
    notify_days_before = db.Column(db.String(100), default="30,14,7")

# --- New Models ---
purchase_users = db.Table('purchase_users',
    db.Column('purchase_id', db.Integer, db.ForeignKey('purchase.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

purchase_tags = db.Table('purchase_tags',
    db.Column('purchase_id', db.Integer, db.ForeignKey('purchase.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    internal_id = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(255), nullable=False)
    invoice_number = db.Column(db.String(100))
    purchase_date = db.Column(db.Date, nullable=False)
    cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='EUR')
    comments = db.Column(db.Text)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_method.id'))
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    users = db.relationship('User', secondary=purchase_users, backref='purchases')
    tags = db.relationship('Tag', secondary=purchase_tags, backref='purchases')
    attachments = db.relationship('Attachment', backref='purchase', lazy=True, cascade='all, delete-orphan')
    assets = db.relationship('Asset', backref='purchase', lazy=True)
    peripherals = db.relationship('Peripheral', backref='purchase', lazy=True)

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
    price = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    warranty_length = db.Column(db.Integer) # in months
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    attachments = db.relationship('Attachment', backref='asset', lazy=True, cascade='all, delete-orphan')
    history = db.relationship('AssetHistory', backref='asset', lazy=True, cascade='all, delete-orphan')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def warranty_end_date(self):
        if self.purchase_date and self.warranty_length:
            return self.purchase_date + relativedelta(months=+self.warranty_length)
        return None

class AssetHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

class Peripheral(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50)) # e.g., Keyboard, Mouse, Monitor
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50), nullable=False, default='In Use')
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    # Relationships
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __init__(self, **kwargs):
        super(Peripheral, self).__init__(**kwargs)
        if self.serial_number == '':
            self.serial_number = None

class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100))
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='EUR')
    period = db.Column(db.String(50), nullable=False, default='One-time') # e.g., 'monthly', 'yearly'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    purchases = db.relationship('Purchase', backref='budget', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    @property
    def remaining(self):
        spent = sum(purchase.cost for purchase in self.purchases)
        return self.amount - spent