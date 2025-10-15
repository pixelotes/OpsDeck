import calendar
from .extensions import db
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
from werkzeug.security import generate_password_hash, check_password_hash

# Currency conversion rates (EUR base)
CURRENCY_RATES = {
    'EUR': 1.0,
    'USD': 0.92,
    'GBP': 1.18,
    'ZAR': 0.05
}


# --- Models ---

user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

policy_version_users = db.Table('policy_version_users',
    db.Column('policy_version_id', db.Integer, db.ForeignKey('policy_version.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

policy_version_groups = db.Table('policy_version_groups',
    db.Column('policy_version_id', db.Integer, db.ForeignKey('policy_version.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    users = db.relationship('User', secondary=user_groups, back_populates='groups')
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary=policy_version_groups, back_populates='groups_to_acknowledge')

class User(db.Model): # Add UserMixin here if using Flask-Login
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False) # Make email unique and required for login
    password_hash = db.Column(db.String(120)) # Can be nullable for users who don't log in
    role = db.Column(db.String(50), default='user') # e.g., 'user', 'editor', 'admin'
    department = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assets = db.relationship('Asset', backref='user', lazy=True)
    peripherals = db.relationship('Peripheral', backref='user', lazy=True)
    licenses = db.relationship('License', backref='user', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    acknowledgements = db.relationship('PolicyAcknowledgement', backref='user', lazy=True, cascade='all, delete-orphan')
    groups = db.relationship('Group', secondary=user_groups, back_populates='users')
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary=policy_version_users, back_populates='users_to_acknowledge')
    course_assignments = db.relationship('CourseAssignment', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        # Only check password if one is set
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    compliance_status = db.Column(db.String(50), default='Pending')
    gdpr_dpa_signed = db.Column(db.Date, nullable=True)
    security_assessment_completed = db.Column(db.Date, nullable=True)
    compliance_notes = db.Column(db.Text, nullable=True)
    data_storage_region = db.Column(db.String(50), default='EU')
    attachments = db.relationship('Attachment', backref='supplier', lazy=True, cascade='all, delete-orphan')
    
    contacts = db.relationship('Contact', backref='supplier', lazy=True, cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='supplier', lazy=True)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)
    assets = db.relationship('Asset', backref='supplier', lazy=True)
    peripherals = db.relationship('Peripheral', backref='supplier', lazy=True)
    opportunities = db.relationship('Opportunity', backref='supplier', foreign_keys='Opportunity.supplier_id')
    security_assessments = db.relationship('SecurityAssessment', backref='supplier', lazy=True, cascade='all, delete-orphan')

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    role = db.Column(db.String(50))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    opportunities = db.relationship('Opportunity', backref='primary_contact', foreign_keys='Opportunity.primary_contact_id')

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

# Association table for Subscriptions and Tags
subscription_tags = db.Table('subscription_tags',
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False) # Original filename
    secure_filename = db.Column(db.String(255), nullable=False, unique=True) # Stored filename
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bcdr_test_log_id = db.Column(db.Integer, db.ForeignKey('bcdr_test_log.id'))
    maintenance_log_id = db.Column(db.Integer, db.ForeignKey('maintenance_log.id'))
    disposal_record_id = db.Column(db.Integer, db.ForeignKey('disposal_record.id'))

    # Courses
    course_completion_id = db.Column(db.Integer, db.ForeignKey('course_completion.id'))

    # Policies
    policy_id = db.Column(db.Integer, db.ForeignKey('policy.id'))
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_version.id'))

    # Policy assessments
    security_assessment_id = db.Column(db.Integer, db.ForeignKey('security_assessment.id'))

    # Risks
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'))
                        
    # Security Incidents
    security_incident_id = db.Column(db.Integer, db.ForeignKey('security_incident.id'))
    
    # Foreign keys - one of these will be set
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    peripheral_id = db.Column(db.Integer, db.ForeignKey('peripheral.id'))

# Association table for many-to-many relationship between subscriptions and payments
subscription_payment_methods = db.Table('subscription_payment_methods',
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True),
    db.Column('payment_method_id', db.Integer, db.ForeignKey('payment_method.id'), primary_key=True)
)

# Association table for many-to-many relationship between subscriptions and contacts
subscription_contacts = db.Table('subscription_contacts',
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True),
    db.Column('contact_id', db.Integer, db.ForeignKey('contact.id'), primary_key=True),
)

class CostHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=False)
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


    # Relationship back to Subscription (optional, but useful)
    subscriptions = db.relationship('Subscription', secondary=subscription_payment_methods, back_populates='payment_methods')
    purchases = db.relationship('Purchase', backref='payment_method', lazy=True)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subscription_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    
    # Renewal information
    renewal_date = db.Column(db.Date, nullable=False)
    renewal_period_type = db.Column(db.String(20), nullable=False)
    renewal_period_value = db.Column(db.Integer, default=1)
    
    # Stores 'first', 'last', or a day number (e.g., '15') for monthly renewals
    monthly_renewal_day = db.Column(db.String(10), nullable=True)
    
    auto_renew = db.Column(db.Boolean, default=False)
    
    # Cost information
    cost = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), default='EUR')

    # Licenses
    licenses = db.relationship('License', backref='subscription', lazy=True)
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True)
    contacts = db.relationship('Contact', secondary=subscription_contacts, backref='subscriptions')
    payment_methods = db.relationship('PaymentMethod', secondary=subscription_payment_methods, back_populates='subscriptions')
    attachments = db.relationship('Attachment', backref='subscription', lazy=True, cascade='all, delete-orphan')
    cost_history = db.relationship('CostHistory', backref='subscription', lazy=True, cascade='all, delete-orphan', order_by='CostHistory.changed_date')
    tags = db.relationship('Tag', secondary=subscription_tags, backref=db.backref('subscriptions', lazy='dynamic'))
    
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

class PurchaseCostHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'validated' or 'un-validated'
    cost = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User')

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    internal_id = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(255), nullable=False)
    invoice_number = db.Column(db.String(100))
    purchase_date = db.Column(db.Date, nullable=False)
    comments = db.Column(db.Text)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_method.id'))
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    validated_cost = db.Column(db.Float, nullable=True)
    cost_validated_at = db.Column(db.DateTime, nullable=True)
    cost_validated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    cost_validated_by = db.relationship('User', foreign_keys=[cost_validated_by_id])
    
    users = db.relationship('User', secondary=purchase_users, backref='purchases')
    tags = db.relationship('Tag', secondary=purchase_tags, backref='purchases')
    attachments = db.relationship('Attachment', backref='purchase', lazy=True, cascade='all, delete-orphan')
    assets = db.relationship('Asset', backref='purchase', lazy=True)
    peripherals = db.relationship('Peripheral', backref='purchase', lazy=True)
    licenses = db.relationship('License', backref='purchase', lazy=True)
    
    cost_history = db.relationship('PurchaseCostHistory', backref='purchase', lazy=True, order_by='PurchaseCostHistory.timestamp.desc()')

    @property
    def calculated_cost(self):
        """Always calculates the cost from associated items."""
        total = 0
        for asset in self.assets:
            if asset.cost:
                total += asset.cost
        for peripheral in self.peripherals:
            if peripheral.cost:
                total += peripheral.cost
        return total
    
    @property
    def total_cost(self):
        """Returns the validated cost if it exists, otherwise calculates it."""
        if self.validated_cost is not None:
            return self.validated_cost
        return self.calculated_cost

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
    attachments = db.relationship('Attachment', backref='asset', lazy=True, cascade='all, delete-orphan')
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
        # CORRECTED: Use the total_cost property from the Purchase model
        spent = sum(purchase.total_cost for purchase in self.purchases)
        return self.amount - spent
    
class Opportunity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(50), default='Evaluating') # e.g., Evaluating, PoC, Negotiating, Won, Lost
    potential_value = db.Column(db.Float)
    currency = db.Column(db.String(3), default='EUR')
    estimated_close_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    primary_contact_id = db.Column(db.Integer, db.ForeignKey('contact.id'))

    # Relationships
    activities = db.relationship('Activity', backref='opportunity', lazy=True, cascade='all, delete-orphan', order_by='Activity.activity_date.desc()')

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False, default='Meeting') # e.g., Meeting, Call, Email
    activity_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=False)

    # Relationship
    opportunity_id = db.Column(db.Integer, db.ForeignKey('opportunity.id'), nullable=False)

class Policy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100)) # e.g., 'IT Security', 'HR', 'General'
    description = db.Column(db.Text)
    link = db.Column(db.String(512))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to its versions
    versions = db.relationship('PolicyVersion', backref='policy', lazy=True, cascade='all, delete-orphan')
    attachments = db.relationship('Attachment', primaryjoin="and_(Attachment.policy_id==Policy.id)", lazy=True, cascade='all, delete-orphan')

class PolicyVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    version_number = db.Column(db.String(50), nullable=False) # e.g., '1.0', '1.1', '2.0'
    status = db.Column(db.String(50), default='Draft') # 'Draft', 'Active', 'Archived'
    content = db.Column(db.Text) # The full text of the policy
    effective_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date) # Optional: when the policy version is no longer valid
    acknowledgements = db.relationship('PolicyAcknowledgement', backref='version', lazy=True, cascade='all, delete-orphan')
    users_to_acknowledge = db.relationship('User', secondary=policy_version_users, back_populates='policy_versions_to_acknowledge')
    groups_to_acknowledge = db.relationship('Group', secondary=policy_version_groups, back_populates='policy_versions_to_acknowledge')

    # Relationship back to the main policy document
    policy_id = db.Column(db.Integer, db.ForeignKey('policy.id'), nullable=False)
    attachments = db.relationship('Attachment', primaryjoin="and_(Attachment.policy_version_id==PolicyVersion.id)", lazy=True, cascade='all, delete-orphan')

class PolicyAcknowledgement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_version.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    acknowledged_at = db.Column(db.DateTime, default=datetime.utcnow)

class SecurityAssessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(50), default='Pending Review') # Pending Review, Approved, Rejected
    notes = db.Column(db.Text)
    
    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    attachments = db.relationship('Attachment', backref='security_assessment', lazy=True, cascade='all, delete-orphan')

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
    attachments = db.relationship('Attachment', backref='risk', lazy=True, cascade='all, delete-orphan')

# --- Association Tables for BCDR ---
bcdr_plan_subscriptions = db.Table('bcdr_plan_subscriptions',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True)
)

bcdr_plan_assets = db.Table('bcdr_plan_assets',
    db.Column('plan_id', db.Integer, db.ForeignKey('bcdr_plan.id'), primary_key=True),
    db.Column('asset_id', db.Integer, db.ForeignKey('asset.id'), primary_key=True)
)

class BCDRPlan(db.Model):
    __tablename__ = 'bcdr_plan'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    subscriptions = db.relationship('Subscription', secondary=bcdr_plan_subscriptions, backref='bcdr_plans')
    assets = db.relationship('Asset', secondary=bcdr_plan_assets, backref='bcdr_plans')
    test_logs = db.relationship('BCDRTestLog', backref='plan', lazy='dynamic', cascade='all, delete-orphan', order_by='BCDRTestLog.test_date.desc()')

class BCDRTestLog(db.Model):
    __tablename__ = 'bcdr_test_log'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('bcdr_plan.id'), nullable=False)
    test_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(50), nullable=False) # In Progress, Passed, Failed
    notes = db.Column(db.Text)
    
    # Relationships
    attachments = db.relationship('Attachment', backref='bcdr_test_log', lazy=True, cascade='all, delete-orphan')

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(512))
    completion_days = db.Column(db.Integer, default=30) # Timeframe to complete after assignment
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    assignments = db.relationship('CourseAssignment', backref='course', lazy=True, cascade='all, delete-orphan')

class CourseAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assigned_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    completion = db.relationship('CourseCompletion', backref='assignment', uselist=False, cascade='all, delete-orphan')

class CourseCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    completion_date = db.Column(db.Date, nullable=False, default=date.today)
    notes = db.Column(db.Text)
    
    assignment_id = db.Column(db.Integer, db.ForeignKey('course_assignment.id'), nullable=False)
    attachment_id = db.Column(db.Integer, db.ForeignKey('attachment.id'))
    
    attachment = db.relationship('Attachment', foreign_keys=[attachment_id])

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
    attachments = db.relationship('Attachment', backref='maintenance_log', lazy=True, cascade='all, delete-orphan')

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
    attachments = db.relationship('Attachment', backref='security_incident', lazy=True, cascade='all, delete-orphan')

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
    
    attachments = db.relationship('Attachment', backref='disposal_record', lazy=True, cascade='all, delete-orphan')

    history = db.relationship('DisposalHistory', backref='disposal_record', lazy=True, cascade='all, delete-orphan', order_by='DisposalHistory.changed_at.desc()')

class Lead(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(255), nullable=False)
    contact_name = db.Column(db.String(255))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    status = db.Column(db.String(50), default='New') # New, Contacted, Qualified, Converted, Disqualified
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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