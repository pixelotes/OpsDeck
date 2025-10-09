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
    services = db.relationship('Service', backref='supplier', lazy=True)
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

    # Courses
    course_completion_id = db.Column(db.Integer, db.ForeignKey('course_completion.id'))

    # Policies
    policy_id = db.Column(db.Integer, db.ForeignKey('policy.id'))
    policy_version_id = db.Column(db.Integer, db.ForeignKey('policy_version.id'))

    # Policy assessments
    security_assessment_id = db.Column(db.Integer, db.ForeignKey('security_assessment.id'))

    # Risks
    risk_id = db.Column(db.Integer, db.ForeignKey('risk.id'))
    
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
    history = db.relationship('AssetHistory', backref='asset', lazy=True, cascade='all, delete-orphan', order_by='AssetHistory.changed_at.desc()')
    peripherals = db.relationship('Peripheral', backref='asset', lazy=True)
    assignments = db.relationship('AssetAssignment', backref='asset', lazy=True, cascade='all, delete-orphan', order_by='AssetAssignment.checked_out_date.desc()')

    
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
    
    brand = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    warranty_length = db.Column(db.Integer) # in months
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Relationships
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'))
    
    # --- NEW RELATIONSHIP ---
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
        spent = sum(purchase.cost for purchase in self.purchases)
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