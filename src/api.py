# src/api.py
from flask import request, current_app, jsonify, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from .extensions import db
from .models import User, Asset, Peripheral, License, Subscription
from .models.services import BusinessService
from .models.change import Change
from .models.request import Request
from .models.security import SecurityIncident
from .models.onboarding import OnboardingProcess
from .models.procurement import Supplier
from .models.crm import Contact
from .schemas import (
    UserSchema, UserInputSchema, AssetSchema, PeripheralSchema,
    LicenseSchema, SubscriptionSchema, ServiceSchema,
    SupplierSchema, ContactSchema,
    ChangeApiSchema, ChangeInputSchema,
    RequestApiSchema, RequestInputSchema,
    IncidentApiSchema, IncidentInputSchema,
    OnboardingApiSchema, OnboardingInputSchema,
)

# Define Blueprints for each resource
api_bp = Blueprint('api', 'api', url_prefix='/api/v1', description='OpsDeck API')

# --- Security Hook ---
@api_bp.before_request
def check_token():
    # Handle OPTIONS requests (for CORS/Preflight) if needed, usually flask handles it.
    if request.method == "OPTIONS":
        return None
        
    token = None
    # Check standard Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    if not token:
        # Check if it's the schema/swagger endpoint? 
        # flask-smorest serves swagger at /swagger-ui (configured in init) and openapi.json at /openapi.json (root usually).
        # Our bp prefix is /api/v1. So swagger docs should be safe.
        current_app.logger.warning(
            "API Access Failed: Missing Token",
            extra={
                "event.action": "api.request.failure",
                "failure.reason": "missing_token",
                "source.ip": request.remote_addr,
                "http.request.method": request.method,
                "url.path": request.path
            }
        )
        return jsonify({"error": "Token is missing"}), 401
    
    current_api_user = User.query.filter_by(api_token=token).first()
    if not current_api_user:
        current_app.logger.warning(
            "API Access Failed: Invalid Token",
            extra={
                "event.action": "api.request.failure",
                "failure.reason": "invalid_token",
                "source.ip": request.remote_addr,
                "http.request.method": request.method,
                "url.path": request.path
            }
        )
        return jsonify({"error": "Token is invalid"}), 401

    g.api_user = current_api_user

    current_app.logger.info(
        f"API Access: {current_api_user.email}",
        extra={
            "event.action": "api.request.success",
            "user.id": current_api_user.id,
            "user.email": current_api_user.email,
            "source.ip": request.remote_addr,
            "http.request.method": request.method,
            "url.path": request.path
        }
    )

# --- Helper to register Read-Only routes ---
def register_read_only_resource(blueprint, model, schema, url_name):
    """
    Registers List (GET /) and Detail (GET /{id}) routes for a given model.
    """
    
    @blueprint.route(f'/{url_name}')
    class ListResource(MethodView):
        @blueprint.doc(security=[{"bearerAuth": []}])
        @blueprint.response(200, schema(many=True))
        # @blueprint.paginate(Page) # Disabled due to injection issue
        def get(self):
            """List all {url_name} (Protected)"""
            limit = request.args.get('limit', 100, type=int)
            offset = request.args.get('offset', 0, type=int)
            return model.query.limit(limit).offset(offset).all()

    @blueprint.route(f'/{url_name}/<int:id>')
    class DetailResource(MethodView):
        @blueprint.doc(security=[{"bearerAuth": []}])
        @blueprint.response(200, schema)
        def get(self, id):
            """Get specific {url_name} by ID (Protected)"""
            return db.get_or_404(model, id)

# --- Register Routes ---
register_read_only_resource(api_bp, Asset, AssetSchema, 'assets')
register_read_only_resource(api_bp, Peripheral, PeripheralSchema, 'peripherals')
register_read_only_resource(api_bp, License, LicenseSchema, 'licenses')
register_read_only_resource(api_bp, Subscription, SubscriptionSchema, 'subscriptions')
register_read_only_resource(api_bp, BusinessService, ServiceSchema, 'services')
register_read_only_resource(api_bp, Supplier, SupplierSchema, 'suppliers')
register_read_only_resource(api_bp, Contact, ContactSchema, 'contacts')


# --- Helpers ---

def resolve_user(identifier):
    """Resolve a user by email (preferred) or name. Returns User or None."""
    if not identifier:
        return None
    user = User.query.filter_by(email=identifier, is_archived=False).first()
    if not user:
        user = User.query.filter_by(name=identifier, is_archived=False).first()
    return user


# --- Users (List + Detail read, upsert by email) ---

@api_bp.route('/users')
class UserListResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, UserSchema(many=True))
    def get(self):
        """List all users (Protected)"""
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        return User.query.limit(limit).offset(offset).all()

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.arguments(UserInputSchema)
    @api_bp.response(201, UserSchema)
    def post(self, data):
        """Create or update a User (upsert by email)"""
        existing = User.query.filter_by(email=data['email']).first()
        if existing:
            for key, value in data.items():
                if value is not None and key != 'email':
                    setattr(existing, key, value)
            db.session.commit()
            return existing, 200

        user = User(**{k: v for k, v in data.items() if v is not None})
        db.session.add(user)
        db.session.commit()
        return user, 201


@api_bp.route('/users/<int:id>')
class UserDetailResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, UserSchema)
    def get(self, id):
        """Get specific user by ID (Protected)"""
        return db.get_or_404(User, id)


# --- POST Endpoints (Upsert by external_ref) ---

@api_bp.route('/changes')
class ChangeResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, ChangeApiSchema(many=True))
    def get(self):
        """List all changes (Protected)"""
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        return Change.query.limit(limit).offset(offset).all()

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.arguments(ChangeInputSchema)
    @api_bp.response(201, ChangeApiSchema)
    def post(self, data):
        """Create or update a Change (upsert by external_ref)"""
        existing = None
        if data.get('external_ref'):
            existing = Change.query.filter_by(external_ref=data['external_ref']).first()

        requester = resolve_user(data.pop('requester', None))
        assignee = resolve_user(data.pop('assignee', None))

        if existing:
            for key, value in data.items():
                if value is not None:
                    setattr(existing, key, value)
            if requester:
                existing.requester_id = requester.id
            if assignee:
                existing.assignee_id = assignee.id
            db.session.commit()
            return existing, 200

        change = Change(
            requester_id=(requester.id if requester else g.api_user.id),
            assignee_id=(assignee.id if assignee else None),
            **{k: v for k, v in data.items() if v is not None}
        )
        db.session.add(change)
        db.session.commit()
        return change, 201


@api_bp.route('/changes/<int:id>')
class ChangeDetailResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, ChangeApiSchema)
    def get(self, id):
        """Get specific change by ID (Protected)"""
        return db.get_or_404(Change, id)


@api_bp.route('/requests')
class RequestResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, RequestApiSchema(many=True))
    def get(self):
        """List all service requests (Protected)"""
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        return Request.query.limit(limit).offset(offset).all()

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.arguments(RequestInputSchema)
    @api_bp.response(201, RequestApiSchema)
    def post(self, data):
        """Create or update a service Request (upsert by external_ref)"""
        existing = None
        if data.get('external_ref'):
            existing = Request.query.filter_by(external_ref=data['external_ref']).first()

        requester = resolve_user(data.pop('requester', None))
        assignee = resolve_user(data.pop('assignee', None))

        if existing:
            for key, value in data.items():
                if value is not None:
                    setattr(existing, key, value)
            if requester:
                existing.requester_id = requester.id
            if assignee:
                existing.assignee_id = assignee.id
            db.session.commit()
            return existing, 200

        req = Request(
            requester_id=(requester.id if requester else g.api_user.id),
            assignee_id=(assignee.id if assignee else None),
            **{k: v for k, v in data.items() if v is not None}
        )
        db.session.add(req)
        db.session.commit()
        return req, 201


@api_bp.route('/requests/<int:id>')
class RequestDetailResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.response(200, RequestApiSchema)
    def get(self, id):
        """Get specific service request by ID (Protected)"""
        return db.get_or_404(Request, id)


@api_bp.route('/incidents')
class IncidentResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.arguments(IncidentInputSchema)
    @api_bp.response(201, IncidentApiSchema)
    def post(self, data):
        """Create or update a Security Incident (upsert by external_ref)"""
        existing = None
        if data.get('external_ref'):
            existing = SecurityIncident.query.filter_by(external_ref=data['external_ref']).first()

        reported_by = resolve_user(data.pop('reported_by', None))
        owner = resolve_user(data.pop('owner', None))
        assignee = resolve_user(data.pop('assignee', None))

        if existing:
            for key, value in data.items():
                if value is not None:
                    setattr(existing, key, value)
            if reported_by:
                existing.reported_by_id = reported_by.id
            if owner:
                existing.owner_id = owner.id
            if assignee:
                existing.assignee_id = assignee.id
            db.session.commit()
            return existing, 200

        incident = SecurityIncident(
            reported_by_id=(reported_by.id if reported_by else g.api_user.id),
            owner_id=(owner.id if owner else None),
            assignee_id=(assignee.id if assignee else None),
            **{k: v for k, v in data.items() if v is not None}
        )
        db.session.add(incident)
        db.session.commit()
        return incident, 201


@api_bp.route('/onboardings')
class OnboardingResource(MethodView):

    @api_bp.doc(security=[{"bearerAuth": []}])
    @api_bp.arguments(OnboardingInputSchema)
    @api_bp.response(201, OnboardingApiSchema)
    def post(self, data):
        """Create or update an Onboarding Process (upsert by external_ref)"""
        existing = None
        if data.get('external_ref'):
            existing = OnboardingProcess.query.filter_by(external_ref=data['external_ref']).first()

        manager = resolve_user(data.pop('manager', None))
        buddy = resolve_user(data.pop('buddy', None))

        if existing:
            for key, value in data.items():
                if value is not None:
                    setattr(existing, key, value)
            if manager:
                existing.assigned_manager_id = manager.id
            if buddy:
                existing.assigned_buddy_id = buddy.id
            db.session.commit()
            return existing, 200

        onboarding = OnboardingProcess(
            assigned_manager_id=(manager.id if manager else None),
            assigned_buddy_id=(buddy.id if buddy else None),
            **{k: v for k, v in data.items() if v is not None}
        )
        db.session.add(onboarding)
        db.session.commit()
        return onboarding, 201