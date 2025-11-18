import calendar
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment, CURRENCY_RATES, Tag
from .auth import User

# Association table for Subscriptions and Tags
subscription_tags = db.Table('subscription_tags',
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

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

purchase_users = db.Table('purchase_users',
    db.Column('purchase_id', db.Integer, db.ForeignKey('purchase.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

purchase_tags = db.Table('purchase_tags',
    db.Column('purchase_id', db.Integer, db.ForeignKey('purchase.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

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
    attachments = db.relationship('Attachment',
        primaryjoin="and_(Supplier.id==foreign(Attachment.linkable_id), "
        "Attachment.linkable_type=='Supplier')",
        lazy=True, cascade='all, delete-orphan')

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
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Purchase.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Purchase')",
                            lazy=True, cascade='all, delete-orphan')
    assets = db.relationship('Asset', backref='purchase', lazy=True)
    peripherals = db.relationship('Peripheral', backref='purchase', lazy=True)
    licenses = db.relationship('License', backref='purchase', lazy=True) # Added relationship

    cost_history = db.relationship('PurchaseCostHistory', backref='purchase', lazy=True, order_by='PurchaseCostHistory.timestamp.desc()')

    @property
    def calculated_cost(self):
        """Calculates the cost from associated assets, peripherals, AND perpetual licenses."""
        total = 0.0 # Use float for calculations
        # Add costs from Assets
        for asset in self.assets:
            if asset.cost is not None:
                # Assuming purchase total should be sum of original costs
                # Add currency conversion here if needed, e.g., to EUR
                total += asset.cost
        # Add costs from Peripherals
        for peripheral in self.peripherals:
            if peripheral.cost is not None:
                 # Add currency conversion here if needed
                 total += peripheral.cost

        # --- ADDED: Include costs from perpetual/standalone licenses ---
        for license in self.licenses:
            # Only include cost if it's NOT linked to a subscription (i.e., it's perpetual/standalone)
            # and if the cost exists
            if license.subscription_id is None and license.cost is not None:
                 # Add currency conversion here if needed
                 total += license.cost
        # --- END ADDITION ---
        return total

    @property
    def total_cost(self):
        """Returns the validated cost if it exists, otherwise calculates it."""
        if self.validated_cost is not None:
            return self.validated_cost
        return self.calculated_cost

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
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Subscription.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Subscription')",
                            lazy=True, cascade='all, delete-orphan')
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
