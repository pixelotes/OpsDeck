import calendar
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import foreign, validates
from sqlalchemy import and_
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from src.utils.timezone_helper import today, now


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

# Association table for User Access (M2M) - Subscriptions
subscription_users = db.Table('subscription_users',
    db.Column('subscription_id', db.Integer, db.ForeignKey('subscription.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
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
    website = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_critical = db.Column(db.Boolean, default=False)
    compliance_status = db.Column(db.String(50), default='Pending')
    gdpr_dpa_signed = db.Column(db.Date, nullable=True)
    security_assessment_completed = db.Column(db.Date, nullable=True)
    compliance_notes = db.Column(db.Text, nullable=True)
    data_storage_region = db.Column(db.String(50), default='EU')
    attachments = db.relationship('Attachment',
        primaryjoin="and_(Supplier.id==foreign(Attachment.linkable_id), "
        "Attachment.linkable_type=='Supplier')",
        lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Supplier.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Supplier'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    contacts = db.relationship('Contact', backref='supplier', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)
    subscriptions = db.relationship('Subscription', backref='supplier', lazy=True)
    purchases = db.relationship('Purchase', backref='supplier', lazy=True)
    assets = db.relationship('Asset', backref='supplier', lazy=True)
    peripherals = db.relationship('Peripheral', backref='supplier', lazy=True)
    opportunities = db.relationship('Opportunity', backref='supplier', foreign_keys='Opportunity.supplier_id')
    security_assessments = db.relationship('SecurityAssessment', backref='supplier', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN)


class PurchaseCostHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'validated' or 'un-validated'
    cost = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=lambda: now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = db.relationship('User')

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    internal_id = db.Column(db.String(100), unique=True)
    description = db.Column(db.String(255), nullable=False)
    invoice_number = db.Column(db.String(100))
    purchase_date = db.Column(db.Date, nullable=False)
    comments = db.Column(db.Text)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), index=True)
    payment_method_id = db.Column(db.Integer, db.ForeignKey('payment_method.id'), index=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), index=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)

    validated_cost = db.Column(db.Float, nullable=True)
    cost_validated_at = db.Column(db.DateTime, nullable=True)
    cost_validated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    cost_validated_by = db.relationship('User', foreign_keys=[cost_validated_by_id])

    users = db.relationship('User', secondary=purchase_users, backref='purchases')
    tags = db.relationship('Tag', secondary=purchase_tags, backref='purchases')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Purchase.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Purchase')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Purchase.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Purchase'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )
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
    valid_from = db.Column(db.Date, nullable=False, default=lambda: today().replace(month=1, day=1))
    valid_until = db.Column(db.Date, nullable=False, default=lambda: today().replace(month=12, day=31))
    created_at = db.Column(db.DateTime, default=lambda: now())
    purchases = db.relationship('Purchase', backref='budget', lazy=True)
    subscriptions = db.relationship('Subscription', backref='budget', lazy=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Budget.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Budget'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    @validates('amount')
    def validate_amount(self, key, value):
        """
        Validate that budget amount is positive and non-zero.

        Raises:
            ValueError: If amount is <= 0
        """
        if value is not None and value <= 0:
            raise ValueError(f"Budget amount must be greater than 0, got {value}")
        return value

    def is_active(self, date_to_check=None):
        """
        Check if the budget is active on a given date.

        This method uses Date (not DateTime) comparisons because budgets are valid
        for complete days, not specific hours. A budget is considered valid for the
        entire duration of both valid_from and valid_until dates (inclusive on both sides).

        Examples:
            - Budget valid from 2024-01-01 to 2024-12-31
            - A subscription renewing on 2024-01-01 → VALID (first day inclusive)
            - A subscription renewing on 2024-12-31 → VALID (last day inclusive)
            - A subscription renewing on 2025-01-01 → INVALID (outside period)

        Args:
            date_to_check: Date to check (defaults to today). Can be a date or datetime
                          object (datetime will be converted to date for comparison)

        Returns:
            bool: True if date_to_check falls within the budget's validity period (inclusive)
        """
        if date_to_check is None:
            date_to_check = today()

        # Convert datetime to date if necessary (for flexibility in calling code)
        if isinstance(date_to_check, datetime):
            date_to_check = date_to_check.date()

        return self.valid_from <= date_to_check <= self.valid_until

    @property
    def remaining(self):
        """
        Calculate remaining budget after purchases and subscription renewals.

        For subscriptions, calculates all renewals that occur within the budget's
        valid period (valid_from to valid_until).
        """
        from ..services.finance_service import get_conversion_rate

        # Calculate spent from purchases
        spent = sum(purchase.total_cost for purchase in self.purchases)

        # Calculate spent from subscriptions
        # For each subscription, count all renewals within the budget period
        for subscription in self.subscriptions:
            if subscription.is_archived:
                continue

            # Convert subscription cost to budget currency
            rate = get_conversion_rate(subscription.currency)
            cost_in_budget_currency = subscription.cost * rate

            if not subscription.auto_renew:
                # Non-renewable: count only once if renewal_date falls within budget period
                if self.valid_from <= subscription.renewal_date <= self.valid_until:
                    spent += cost_in_budget_currency
                continue

            # Count renewals within budget validity period
            renewal_count = self._count_renewals_in_period(
                subscription.renewal_date,
                subscription.renewal_period_type,
                subscription.renewal_period_value
            )

            spent += cost_in_budget_currency * renewal_count

        return self.amount - spent

    def _count_renewals_in_period(self, renewal_date, period_type, period_value):
        """
        Count how many renewals occur within the budget's validity period.

        Args:
            renewal_date: Initial renewal date
            period_type: 'monthly', 'yearly', or 'custom'
            period_value: Number of months/years/days between renewals

        Returns:
            Number of renewals within the budget period
        """
        from dateutil.relativedelta import relativedelta
        from datetime import timedelta

        if not period_value or period_value <= 0:
            return 0

        count = 0
        current_renewal = renewal_date

        # Only count renewals that fall within budget validity
        while current_renewal <= self.valid_until:
            if current_renewal >= self.valid_from:
                count += 1

            # Calculate next renewal date
            if period_type == 'monthly':
                current_renewal += relativedelta(months=+period_value)
            elif period_type == 'yearly':
                current_renewal += relativedelta(years=+period_value)
            else:  # custom (days)
                current_renewal += timedelta(days=period_value)

        return count

class CostHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('subscription.id'), nullable=False)
    cost = db.Column(db.Float, nullable=False)  # Base cost at this point in time
    currency = db.Column(db.String(3), nullable=False)
    # The date this cost became effective
    changed_date = db.Column(db.Date, nullable=False, default=lambda: today())

    # NEW: Additional tracking fields
    pricing_model = db.Column(db.String(20))  # 'fixed' or 'per_user'
    cost_per_user = db.Column(db.Float, nullable=True)  # Cost per user at this point
    user_count = db.Column(db.Integer, nullable=True)  # Number of users at this point
    reason = db.Column(db.String(50))  # 'price_change', 'user_added', 'user_removed', 'onboarding', 'offboarding', 'manual'

    @property
    def total_cost(self):
        """Calculate total cost at this point in history"""
        if self.pricing_model == 'per_user' and self.cost_per_user is not None:
            return self.cost_per_user * (self.user_count or 0)
        return self.cost or 0


def log_subscription_cost_change(subscription, reason='manual'):
    """
    Records a cost change in the subscription's history.
    Should be called whenever:
    - Cost or cost_per_user changes
    - Users are added/removed (for per_user pricing)
    - Pricing model changes

    Args:
        subscription: The Subscription object
        reason: One of 'price_change', 'user_added', 'user_removed', 'onboarding', 'offboarding', 'manual'

    Note: Does NOT commit - caller must handle commit
    """
    active_user_count = len([u for u in subscription.users if not u.is_archived])

    history_entry = CostHistory(
        subscription_id=subscription.id,
        cost=subscription.cost,
        currency=subscription.currency,
        pricing_model=subscription.pricing_model,
        cost_per_user=subscription.cost_per_user,
        user_count=active_user_count,
        reason=reason,
        changed_date=today()
    )
    db.session.add(history_entry)


class PaymentMethod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Company Visa"
    method_type = db.Column(db.String(50), nullable=False)  # e.g., "Credit Card", "Bank Transfer"
    details = db.Column(db.String(100))  # e.g., "Visa ending in 1234"
    expiry_date = db.Column(db.Date)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='payment_methods')
    created_at = db.Column(db.DateTime, default=lambda: now())
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
    cost = db.Column(db.Float, nullable=False)  # Base cost (for fixed) or legacy
    currency = db.Column(db.String(3), default='EUR')

    # NEW: Pricing model
    pricing_model = db.Column(db.String(20), default='fixed')  # 'fixed' or 'per_user'
    cost_per_user = db.Column(db.Float, nullable=True)  # Cost per user/license (for per_user model)

    # User information
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    user = db.relationship('User', backref='subscriptions')

    # Licenses
    licenses = db.relationship('License', backref='subscription', lazy=True)

    # Relationships
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True, index=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budget.id'), nullable=True, index=True)
    contacts = db.relationship('Contact', secondary=subscription_contacts, backref='subscriptions')
    payment_methods = db.relationship('PaymentMethod', secondary=subscription_payment_methods, back_populates='subscriptions')
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Subscription.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Subscription')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Subscription.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Subscription'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )
    cost_history = db.relationship('CostHistory', backref='subscription', lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN, order_by='CostHistory.changed_date')
    tags = db.relationship('Tag', secondary=subscription_tags, backref=db.backref('subscriptions', lazy=LAZY_DYNAMIC))
    users = db.relationship('User', secondary=subscription_users, backref='access_subscriptions')
    
    # Metadata
    is_archived = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    @validates('cost')
    def validate_cost(self, key, value):
        """
        Validate that subscription cost is not negative.
        Cost can be 0 for per_user pricing (calculated from cost_per_user * users).
        Route-level validation ensures cost > 0 for fixed pricing.
        """
        if value is not None and value < 0:
            raise ValueError(f"Subscription cost must not be negative, got {value}")
        return value

    @validates('renewal_period_value')
    def validate_renewal_period_value(self, key, value):
        if value is not None and value <= 0:
            raise ValueError(f"Renewal period value must be greater than 0, got {value}")
        return value

    @property
    def cost_eur(self):
        from ..services.finance_service import get_conversion_rate
        rate = get_conversion_rate(self.currency)
        return self.current_cost * rate

    @property
    def current_cost(self):
        """
        Calculates the current total cost based on pricing model.
        For per_user: cost_per_user * active_users
        For fixed: cost
        """
        if self.pricing_model == 'per_user' and self.cost_per_user:
            # Count only non-archived users
            active_users = [u for u in self.users if not u.is_archived]
            return self.cost_per_user * len(active_users)
        return self.cost or 0

    @property
    def monthly_cost(self):
        """
        Calculates the monthly cost regardless of renewal period.
        Converts yearly/custom periods to monthly equivalent.
        """
        base_cost = self.current_cost

        if self.renewal_period_type == 'yearly':
            return base_cost / 12
        elif self.renewal_period_type == 'monthly':
            return base_cost
        elif self.renewal_period_type == 'custom' and self.renewal_period_value:
            # Assuming renewal_period_value is in months for custom
            return base_cost / self.renewal_period_value
        else:
            return base_cost

    @property
    def annual_cost(self):
        """Projected annual cost"""
        return self.monthly_cost * 12

    @property
    def monthly_cost_eur(self):
        """Monthly cost converted to EUR"""
        from ..services.finance_service import get_conversion_rate
        rate = get_conversion_rate(self.currency or 'EUR')
        return self.monthly_cost * rate

    @property
    def annual_cost_eur(self):
        """Annual cost converted to EUR"""
        return self.monthly_cost_eur * 12

    @property
    def active_user_count(self):
        """Count of active (non-archived) users"""
        return len([u for u in self.users if not u.is_archived])

    @property
    def next_renewal_date(self):
        """
        Calculates the next upcoming renewal date with advanced logic for
        specific monthly renewal days.

        Optimized to avoid CPU-intensive loops when renewal_date is far in the past.

        Returns:
            date: Next renewal date, or None if auto_renew is False
        """
        # If auto-renewal is disabled, don't calculate next renewal
        if not self.auto_renew:
            return None

        current_date = today()
        renewal_date = self.renewal_date

        # If renewal_date is already in the future, return it
        if renewal_date >= current_date:
            return renewal_date

        # OPTIMIZATION: Calculate periods mathematically instead of looping
        # This prevents CPU-intensive loops when renewal_date is years in the past

        if self.renewal_period_type == 'monthly':
            # Calculate months difference
            months_diff = (current_date.year - renewal_date.year) * 12 + \
                         (current_date.month - renewal_date.month)

            # Calculate how many renewal periods have passed
            periods_passed = months_diff // self.renewal_period_value

            # Jump to approximately the right date
            renewal_date = renewal_date + relativedelta(months=+(periods_passed * self.renewal_period_value))

            # Fine-tune: ensure we're at or past current_date
            while renewal_date < current_date:
                next_month = renewal_date + relativedelta(months=+self.renewal_period_value)

                day = next_month.day
                if self.monthly_renewal_day:
                    if self.monthly_renewal_day == 'first':
                        day = 1
                    elif self.monthly_renewal_day == 'last':
                        day = calendar.monthrange(next_month.year, next_month.month)[1]
                    else:
                        try:
                            day = int(self.monthly_renewal_day)
                            last_day_of_month = calendar.monthrange(next_month.year, next_month.month)[1]
                            day = min(day, last_day_of_month)
                        except (ValueError, TypeError):
                            pass

                renewal_date = next_month.replace(day=day)

        elif self.renewal_period_type == 'yearly':
            # Calculate years difference
            years_diff = current_date.year - renewal_date.year
            periods_passed = years_diff // self.renewal_period_value

            # Jump to approximately the right date
            renewal_date = renewal_date + relativedelta(years=+(periods_passed * self.renewal_period_value))

            # Fine-tune: ensure we're at or past current_date
            while renewal_date < current_date:
                renewal_date += relativedelta(years=+self.renewal_period_value)

        else:  # custom (days)
            # Calculate days difference
            days_diff = (current_date - renewal_date).days
            periods_passed = days_diff // self.renewal_period_value

            # Jump to approximately the right date
            renewal_date = renewal_date + timedelta(days=(periods_passed * self.renewal_period_value))

            # Fine-tune: ensure we're at or past current_date
            while renewal_date < current_date:
                renewal_date += timedelta(days=self.renewal_period_value)

        return renewal_date
    

    
    @property
    def contracts(self):
        """Returns active contracts linked to this specific item."""
        from .contracts import Contract, ContractItem
        return Contract.query.join(ContractItem).filter(
            ContractItem.item_type == self.__class__.__name__, # e.g., 'Subscription'
            ContractItem.item_id == self.id
        ).all()

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
