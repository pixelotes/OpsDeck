# src/schemas.py
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from .extensions import db
from .models import User, Asset, Peripheral, License, Subscription
from .models.services import BusinessService

from marshmallow import fields, Schema, validate
from .models.change import Change
from .models.request import Request
from .models.security import SecurityIncident
from .models.onboarding import OnboardingProcess
from .models.procurement import Supplier
from .models.crm import Contact

# --- Base Schema ---
class BaseSchema(SQLAlchemyAutoSchema):
    class Meta:
        sqla_session = db.session
        load_instance = True
        include_fk = True # Include foreign keys like user_id, asset_id

# --- Resource Schemas ---

class UserSchema(BaseSchema):
    custom_properties = fields.Dict(dump_only=True)
    class Meta(BaseSchema.Meta):
        model = User
        # Exclude sensitive data automatically
        exclude = ('password_hash', 'api_token')

class UserInputSchema(Schema):
    email = fields.Email(required=True, validate=validate.Length(min=1, max=100))
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    department = fields.String(load_default=None, validate=validate.Length(max=100))
    job_title = fields.String(load_default=None, validate=validate.Length(max=100))
    personal_email = fields.String(load_default=None, validate=validate.Length(max=120))
    role = fields.String(load_default='user', validate=validate.Length(max=50))

class AssetSchema(BaseSchema):
    custom_properties = fields.Dict(dump_only=True)
    class Meta(BaseSchema.Meta):
        model = Asset

class PeripheralSchema(BaseSchema):
    custom_properties = fields.Dict(dump_only=True)
    class Meta(BaseSchema.Meta):
        model = Peripheral

class LicenseSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = License

class SubscriptionSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Subscription

class ServiceSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = BusinessService
        # Recursive relationships are excluded to keep the payload small.
        exclude = ('upstream_dependencies', 'downstream_dependencies', 'components')

class SupplierSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Supplier

class ContactSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Contact


# --- API Output Schemas ---

class ChangeApiSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Change

class RequestApiSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = Request

class IncidentApiSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = SecurityIncident

class OnboardingApiSchema(BaseSchema):
    class Meta(BaseSchema.Meta):
        model = OnboardingProcess


# --- API Input Schemas (accept emails/names instead of IDs) ---

class ChangeInputSchema(Schema):
    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(load_default=None)
    change_type = fields.String(load_default='Standard', validate=validate.OneOf(['Standard', 'Normal', 'Emergency']))
    priority = fields.String(load_default='Medium', validate=validate.OneOf(['Low', 'Medium', 'High', 'Critical']))
    risk_impact = fields.String(load_default='Low', validate=validate.OneOf(['Low', 'Medium', 'High']))
    status = fields.String(load_default='Draft')
    implementation_plan = fields.String(load_default=None)
    rollback_plan = fields.String(load_default=None)
    test_plan = fields.String(load_default=None)
    requester = fields.String(load_default=None)
    assignee = fields.String(load_default=None)
    external_ref = fields.String(load_default=None, validate=validate.Length(max=255))


class RequestInputSchema(Schema):
    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(load_default=None)
    request_type = fields.String(load_default='General', validate=validate.OneOf(['General', 'Access', 'Hardware', 'Software', 'Information']))
    priority = fields.String(load_default='Medium', validate=validate.OneOf(['Low', 'Medium', 'High', 'Critical']))
    status = fields.String(load_default='Pending')
    justification = fields.String(load_default=None)
    resolution_notes = fields.String(load_default=None)
    requester = fields.String(load_default=None)
    assignee = fields.String(load_default=None)
    external_ref = fields.String(load_default=None, validate=validate.Length(max=255))


class IncidentInputSchema(Schema):
    title = fields.String(required=True, validate=validate.Length(min=1, max=255))
    description = fields.String(required=True)
    severity = fields.String(load_default='SEV-3', validate=validate.OneOf(['SEV-0', 'SEV-1', 'SEV-2', 'SEV-3']))
    status = fields.String(load_default='Investigating')
    impact = fields.String(load_default='Minor', validate=validate.OneOf(['Minor', 'Moderate', 'Significant', 'Extensive']))
    reported_by = fields.String(load_default=None)
    owner = fields.String(load_default=None)
    assignee = fields.String(load_default=None)
    external_ref = fields.String(load_default=None, validate=validate.Length(max=255))


class OnboardingInputSchema(Schema):
    new_hire_name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    start_date = fields.Date(required=True)
    status = fields.String(load_default='Provisioning')
    manager = fields.String(load_default=None)
    buddy = fields.String(load_default=None)
    pack_id = fields.Integer(load_default=None)
    target_email = fields.String(load_default=None)
    personal_email = fields.String(load_default=None)
    external_ref = fields.String(load_default=None, validate=validate.Length(max=255))