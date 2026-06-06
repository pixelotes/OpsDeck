# src/__init__.py

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import atexit
import click
from flask import Flask, session, render_template, request, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
import ecs_logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_dance.contrib.google import make_google_blueprint
from flask_talisman import Talisman
from flask_smorest import Api

from .extensions import db, migrate

from .models import User, Contract, ContractItem
from . import notifications # Added the missing import
import markdown
from markupsafe import Markup
from .seeder_prod import seed_production_frameworks
import re

# --- Rate Limiter (global instance for use in blueprints) ---
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)

# --- CSRF Protection ---
from flask_wtf.csrf import CSRFProtect
from src.utils.timezone_helper import today

csrf = CSRFProtect()

# --- Content Security Policy ---
talisman = Talisman()

# --- Initialize Extensions ---
def configure_logging(app):
    """
    Configure structured ECS logging with file rotation and console output.
    """
    # Get the app logger
    logger = logging.getLogger(app.name)
    logger.setLevel(logging.INFO)

    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 1. Handler for file output (JSON ECS format)
    # Rotates at 10MB, keeps 5 backup files
    log_file_path = os.path.join(log_dir, 'logs.json')
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(ecs_logging.StdlibFormatter())

    # 2. Handler for console output (JSON ECS format as requested)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ecs_logging.StdlibFormatter())

    # Clear any existing handlers and add the new ones
    logger.handlers = []
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Sync Flask's app.logger with our configured logger
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logger.level)

def create_app(test_config=None):
    """
    Application factory function to create and configure the Flask app.
    
    Args:
        test_config (dict, optional): Configuration dictionary for testing.
                                     If provided, overrides default configuration.
    """
    app = Flask(__name__)

    # --- Configuration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
    
    # Database configuration - PostgreSQL required in production
    if test_config and 'SQLALCHEMY_DATABASE_URI' in test_config:
        database_url = test_config['SQLALCHEMY_DATABASE_URI']
    else:
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is required. "
                "Example: postgresql://user:password@host:5432/dbname"
            )
    # Handle Heroku-style postgres:// URLs (SQLAlchemy requires postgresql://)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

    # Log which database backend is being used
    is_postgres = 'postgresql' in database_url
    app.config['IS_POSTGRES'] = is_postgres

    # --- CORRECT UPLOAD FOLDER CONFIG ---
    # Define the project's root directory (where run.py is)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Set the upload folder to data/attachments/ inside the root
    app.config['UPLOAD_FOLDER'] = os.path.join(project_root, 'data', 'attachments')

    # Create the new uploads folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Email configuration
    app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '587'))
    app.config['EMAIL_USERNAME'] = os.environ.get('EMAIL_USERNAME', '')
    app.config['EMAIL_PASSWORD'] = os.environ.get('EMAIL_PASSWORD', '')
    app.config['EMAIL_SENDER_NAME'] = os.environ.get('EMAIL_SENDER_NAME', '')
    app.config['WEBHOOK_URL'] = os.environ.get('WEBHOOK_URL', '')

    # --- Google OAuth Configuration ---
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
    app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')
    # Allow insecure transport for local development
    insecure_transport = os.environ.get('OAUTHLIB_INSECURE_TRANSPORT') == '1'
    if insecure_transport:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

    # --- MFA Configuration ---
    app.config['MFA_ENABLED'] = os.environ.get('MFA_ENABLED', 'False').lower() == 'true'

    # --- Admin User Configuration (for initial setup) ---
    app.config['DEFAULT_ADMIN_EMAIL'] = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
    app.config['DEFAULT_ADMIN_INITIAL_PASSWORD'] = os.environ.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')

    # --- API Configuration ---
    app.config["API_TITLE"] = "OpsDeck API"
    app.config["API_VERSION"] = "v1"
    app.config["OPENAPI_VERSION"] = "3.0.2"
    app.config["OPENAPI_URL_PREFIX"] = "/"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/swagger-ui"
    app.config["OPENAPI_SWAGGER_UI_URL"] = "/static/vendor/swagger-ui/"
    app.config["API_SPEC_OPTIONS"] = {
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT"
                }
            }
        }
    }

    # --- Apply Test Configuration (BEFORE extension initialization) ---
    if test_config is not None:
        app.config.update(test_config)

    # --- Initialize Extensions ---
    db.init_app(app)
    from .extensions import login_manager
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    migrate.init_app(app, db)

    # Initialize audit logging
    from src.utils.audit_listener import register_audit_listener
    register_audit_listener(db)

    limiter.init_app(app)

    @limiter.request_filter
    def _no_limit_static():
        return request.endpoint == 'static'

    # Configure CSRF to not protect JSON requests (for AJAX endpoints)
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    app.config['WTF_CSRF_ENABLED'] = True
    csrf.init_app(app)
    
    # Disable HTTPS enforcement in development (debug mode) or when explicitly disabled
    is_development = app.debug or insecure_transport or os.environ.get('FLASK_ENV') == 'development'
    talisman.init_app(app, content_security_policy=None, force_https=not is_development)

    # --- Configure Logging (ECS format with rotation) ---
    configure_logging(app)

    # --- Initialize API ---
    api = Api(app)
    from .api import api_bp
    api.register_blueprint(api_bp)

    # --- Custom Error Handlers ---
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(429)
    def ratelimit_handler(e):
        from .utils.logger import log_audit
        log_audit(
            event_type='security.rate_limit_breach',
            action='block',
            outcome='failure',
            error_message=e.description
        )
        return render_template('errors/429.html', error=e.description), 429
    
    @app.errorhandler(500)
    def internal_server_error(e):
        from .utils.logger import log_audit
        log_audit(
            event_type='system.internal_error',
            action='error',
            outcome='failure',
            error_message=str(e)
        )
        return render_template('errors/500.html'), 500
    
    # --- REGISTER THE CUSTOM MARKDOWN FILTER ---
    @app.template_filter('markdown')
    def markdown_filter(s):
        """Convert markdown to HTML with common extensions"""
        return Markup(markdown.markdown(s, extensions=[
            'extra',           # Includes tables, fenced code blocks, footnotes, etc.
            'codehilite',      # Syntax highlighting for code blocks
            'nl2br',           # Convert newlines to <br>
            'sane_lists',      # Better list handling
            'toc',             # Table of contents
            'smarty'           # Smart quotes and dashes
        ]))
    
    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """Converts newlines in a string to HTML <br> tags."""
        return Markup(re.sub(r'\n', '<br>\n', s))

    # --- Register Blueprints ---
    from .routes.main import main_bp
    from .routes.assets import assets_bp
    from .routes.peripherals import peripherals_bp
    from .routes.brands import brands_bp
    from .routes.locations import locations_bp
    from .routes.suppliers import suppliers_bp
    from .routes.contacts import contacts_bp
    from .routes.users import users_bp
    from .routes.groups import groups_bp
    from .routes.payment_methods import payment_methods_bp
    from .routes.tags import tags_bp
    from .routes.subscriptions import subscriptions_bp
    from .routes.licenses import licenses_bp
    from .routes.software import software_bp
    from .routes.purchases import purchases_bp
    from .routes.budgets import budgets_bp
    from .routes.reports import reports_bp
    from .routes.attachments import attachments_bp
    from .routes.treeview import treeview_bp
    from .routes.admin import admin_bp
    from .routes.evaluations import evaluations_bp
    from .routes.policies import policies_bp
    from .routes.compliance import compliance_bp
    from .routes.risk import risk_bp
    from .routes.training import training_bp
    from .routes.maintenance import maintenance_bp
    from .routes.disposal import disposal_bp
    from .routes.requirements import requirements_bp
    from .routes.documentation import documentation_bp
    from .routes.frameworks import frameworks_bp
    from .routes.links import links_bp
    from .routes.activities import activities_bp
    from .routes.onboarding import onboarding_bp
    from .routes.credentials import credentials_bp

    # --- Favicon Route ---
    from flask import send_from_directory
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')

    app.register_blueprint(main_bp)
    app.register_blueprint(assets_bp, url_prefix='/assets')
    app.register_blueprint(peripherals_bp, url_prefix='/peripherals')
    app.register_blueprint(brands_bp, url_prefix='/brands')
    app.register_blueprint(locations_bp, url_prefix='/locations')
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(groups_bp, url_prefix='/groups')
    app.register_blueprint(payment_methods_bp, url_prefix='/payment-methods')
    app.register_blueprint(tags_bp, url_prefix='/tags')
    app.register_blueprint(subscriptions_bp, url_prefix='/subscriptions')
    app.register_blueprint(licenses_bp)
    app.register_blueprint(software_bp)
    app.register_blueprint(purchases_bp, url_prefix='/purchases')
    app.register_blueprint(budgets_bp, url_prefix='/budgets')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(attachments_bp, url_prefix='/attachments')
    app.register_blueprint(treeview_bp, url_prefix='/tree-view')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(policies_bp, url_prefix='/policies')
    app.register_blueprint(compliance_bp, url_prefix='/compliance')
    app.register_blueprint(risk_bp, url_prefix='/risk')

    from .routes.search import search_bp
    app.register_blueprint(search_bp, url_prefix='/search')
    app.register_blueprint(training_bp, url_prefix='/training')
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(disposal_bp)
    app.register_blueprint(requirements_bp)
    app.register_blueprint(documentation_bp, url_prefix='/documentation')
    app.register_blueprint(frameworks_bp)
    
    from .routes.changes import changes_bp
    app.register_blueprint(changes_bp, url_prefix='/changes')

    from .routes.audits import audits_bp
    app.register_blueprint(audits_bp)
    from .routes.services import services_bp
    app.register_blueprint(services_bp)
    from .routes.cost_centers import cost_centers_bp
    app.register_blueprint(cost_centers_bp, url_prefix='/cost-centers')
    app.register_blueprint(links_bp, url_prefix='/links')
    app.register_blueprint(activities_bp, url_prefix='/security/activities')
    app.register_blueprint(onboarding_bp, url_prefix='/onboarding')
    from .routes.risk_assessment import risk_assessment_bp
    app.register_blueprint(risk_assessment_bp)
    from .routes.credentials import credentials_bp
    from .routes.certificates import certificates_bp
    app.register_blueprint(credentials_bp)
    app.register_blueprint(certificates_bp)
    
    # Hiring / ATS Module
    from .routes.hiring import hiring_bp
    app.register_blueprint(hiring_bp, url_prefix='/hr/hiring')
    
    from .routes.configuration import configuration_bp
    app.register_blueprint(configuration_bp, url_prefix='/configuration')
    
    from .routes.admin_communications import admin_communications_bp
    app.register_blueprint(admin_communications_bp, url_prefix='/admin/communications')
    
    from .routes.admin_notifications import admin_notifications_bp
    app.register_blueprint(admin_notifications_bp, url_prefix='/admin/notifications')
    
    from .routes.campaigns import campaigns_bp
    app.register_blueprint(campaigns_bp, url_prefix='/campaigns')
    
    from .routes.organization import organization_bp
    app.register_blueprint(organization_bp, url_prefix='/settings/organization')

    from .routes.finance import finance_bp
    app.register_blueprint(finance_bp, url_prefix='/finance')


    from .routes.contracts import contracts_bp
    app.register_blueprint(contracts_bp, url_prefix='/contracts')

    # --- Google OAuth Blueprint ---
    if app.config.get('GOOGLE_OAUTH_CLIENT_ID'):
        google_bp = make_google_blueprint(
            client_id=app.config['GOOGLE_OAUTH_CLIENT_ID'],
            client_secret=app.config['GOOGLE_OAUTH_CLIENT_SECRET'],
            scope=["openid", "https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/userinfo.email"],
            redirect_to="main.google_callback"
        )
        app.register_blueprint(google_bp, url_prefix="/login")


    # --- Make user and role available in all templates ---
    @app.context_processor
    def inject_user_context():
        from datetime import date
        user_id = session.get('user_id')
        original_user_id = session.get('original_user_id')
        is_impersonating = original_user_id is not None
        
        if user_id:
            user = db.session.get(User, user_id)
            if user:
                context = dict(
                    current_user=user, 
                    current_user_role=user.role, 
                    today=today(),
                    is_impersonating=is_impersonating
                )
                
                # Add original user if impersonating
                if is_impersonating and original_user_id:
                    original_user = db.session.get(User, original_user_id)
                    context['original_user'] = original_user
                
                return context

        return {
            'current_user': None,
            'current_user_role': None,
            'today': today(),
            'is_impersonating': False
        }

    # --- Action Required alerts (global navbar bell) ---
    @app.context_processor
    def inject_action_alerts():
        user_id = session.get('user_id')
        if not user_id:
            return {'action_alerts': [], 'action_alerts_count': 0}
        user = db.session.get(User, user_id)
        if not user:
            return {'action_alerts': [], 'action_alerts_count': 0}
        from .routes.main import get_action_required_alerts
        alerts = get_action_required_alerts(user)
        return {'action_alerts': alerts, 'action_alerts_count': len(alerts)}

    # --- Permissions Context Processor ---
    @app.context_processor
    def inject_permissions():
        from .services.permissions_service import get_user_modules
        from .services.permissions_cache import permissions_cache
        user_id = session.get('user_id')
        
        def get_perms():
            if not user_id:
                return {}
            perms = permissions_cache.get(user_id)
            if perms is None:
                get_user_modules(user_id)
                perms = permissions_cache.get(user_id)
            return perms or {}

        def can_read(module_slug):
            user = db.session.get(User, user_id) if user_id else None
            if user and user.role == 'admin':
                return True
            return module_slug in get_perms()

        def can_write(module_slug):
            user = db.session.get(User, user_id) if user_id else None
            if user and user.role == 'admin':
                return True
            return get_perms().get(module_slug) == 'WRITE'
            
        return dict(has_permission=can_read, can_read=can_read, can_write=can_write)


    # --- GLOBAL AUTHENTICATION GUARD (Security by Default) ---
    @app.before_request
    def require_login():
        """
        Global authentication wall: All routes require login by default.
        Only whitelisted endpoints are accessible without authentication.
        """
        # Lista de endpoints que NO requieren autenticación (Whitelist)
        public_endpoints = [
            'main.login',
            'main.google_callback',
            'google.login',  # Google OAuth login initiation
            'google.authorized',  # Google OAuth callback handler
            'main.mfa_verify',  # Necesario para el flujo de 2FA
            'main.health_check',  # Health check for Kubernetes probes
            'main.internal_test_db',  # Internal route for CLI database testing
            'main.internal_app_info',  # Internal route for CLI app info
            'main.internal_test_email',  # Internal route for CLI email testing
            'main.internal_health_check',  # Internal route for CLI health check
            'main.internal_test_security',  # Internal route for CLI security audit
            'static',
            'favicon',
            # API endpoints use token authentication, not session
            'api-v1.AuthLogin',
            'api-v1.AuthRefresh',
        ]

        # Permitir acceso si:
        # 1. El usuario ya está autenticado (tiene user_id en sesión)
        if 'user_id' in session:
            return None

        # 2. La petición es un recurso estático o endpoint None (404)
        if request.endpoint is None:
            return None
            
        # 3. La petición es a un endpoint público
        if request.endpoint in public_endpoints:
            return None
            
        # 4. Permitir endpoints de API (usan autenticación por token)
        # Check by path since flask-smorest uses different endpoint naming
        if request.path and request.path.startswith('/api/v1'):
            return None

        # Si llegamos aquí, bloquear y redirigir a login
        # Guardar la URL solicitada para redirigir después del login
        return redirect(url_for('main.login', next=request.url))

    # --- Force admin to change the default password ---
    @app.before_request
    def enforce_password_change():
        """
        Force users with default admin credentials to change their password.
        This runs after authentication but before any route handler.
        """
        user_id = session.get('user_id')
        if user_id:
            # Skip check for allowed endpoints
            if request.endpoint in ['main.change_password', 'main.logout', 'static', 'favicon']:
                return None
                
            user = db.session.get(User, user_id)
            if user:
                # Get configured admin credentials from app config
                default_admin_email = app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
                default_admin_password = app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')
                
                # Check if user is using the default admin credentials
                if user.email == default_admin_email and user.check_password(default_admin_password):
                    # Force redirect to password change page
                    return redirect(url_for('main.change_password'))
        
        return None

    # --- Scheduler and Notifications ---
    # Only start the scheduler if not in testing mode
    if not app.config.get('TESTING'):
        from .utils.timezone_helper import get_timezone_name
        app_timezone = get_timezone_name()

        scheduler = BackgroundScheduler(timezone=app_timezone)
        scheduler.add_job(
            func=notifications.check_upcoming_renewals,
            args=[app],
            trigger="interval",
            days=1
        )
        scheduler.add_job(
            func=notifications.check_credential_expirations,
            args=[app],
            trigger="interval",
            days=1
        )
        scheduler.add_job(
            func=notifications.check_certificate_expirations,
            args=[app],
            trigger="interval",
            days=1
        )
        # Communications engine - process scheduled emails every 5 minutes for faster delivery
        scheduler.add_job(
            func=notifications.process_communications_queue,
            args=[app],
            trigger="interval",
            minutes=5
        )
        # Exchange rate sync - runs daily at 3:00 AM local time
        from .services.finance_service import update_exchange_rates
        def sync_exchange_rates():
            with app.app_context():
                update_exchange_rates()
        scheduler.add_job(
            func=sync_exchange_rates,
            trigger="cron",
            hour=3,
            minute=0,
            timezone=app_timezone,
            id="sync_exchange_rates"
        )
        # UAR automation - runs daily at 8:00 AM local time
        from .services.uar_service import run_scheduled_uar_comparisons
        scheduler.add_job(
            func=run_scheduled_uar_comparisons,
            args=[app],
            trigger="cron",
            hour=8,
            minute=0,
            timezone=app_timezone,
            id="uar_scheduled_comparisons",
            replace_existing=True
        )
        # Compliance drift detection - runs weekly on Mondays at 9:00 AM local time
        from .services.compliance_drift_service import run_drift_detection
        scheduler.add_job(
            func=run_drift_detection,
            args=[app],
            trigger="cron",
            day_of_week='mon',
            hour=9,
            minute=0,
            timezone=app_timezone,
            id="compliance_drift_detection",
            replace_existing=True
        )
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())

    # --- CLI Commands ---
    @app.cli.command("init-db")
    def init_db_command():
        """Creates the database tables and a default admin user if none exists."""
        with app.app_context():
            db.create_all()
            
            # Get admin credentials from configuration (environment variables)
            email = app.config.get('DEFAULT_ADMIN_EMAIL')
            password = app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD')
            
            if not email or not password:
                print("Error: Admin credentials not configured.")
                return
            
            # Check if admin user already exists (idempotency)
            existing_admin = User.query.filter_by(email=email).first()
            if existing_admin:
                print(f"Admin user '{email}' already exists. Skipping creation.")
                return
            
            # Create the admin user (hidden from org chart as it's a break-glass account)
            admin_user = User(name='Administrator', email=email, role='admin', hide_from_org_chart=True)
            admin_user.set_password(password)
            db.session.add(admin_user)
            db.session.commit()
            print(f"✓ Admin user created successfully: {email}")
    
    # --- Seed the db with fake demo data ---
    @app.cli.command("seed-db-demodata")
    def seed_db_command():
        """Seeds the database with demo data."""
        from .seeder import seed_data
        seed_data()

    @app.cli.command('seed-db-prod')
    def seed_prod_command():
        """Carga los datos maestros de producción (Frameworks & Threats)."""
        seed_production_frameworks()
        from .seeder_prod import seed_threats, seed_magerit_catalog, seed_operational_catalog, seed_it_infrastructure_catalog, seed_notification_templates, seed_modules
        seed_modules()
        seed_threats()
        seed_magerit_catalog()
        seed_operational_catalog()
        seed_it_infrastructure_catalog()
        seed_notification_templates()

    @app.cli.command('test-db')
    def test_db_command():
        """Tests database connectivity by querying the user table."""
        with app.test_client() as client:
            response = client.get('/internal/test-db', follow_redirects=True)
            data = response.get_json()
            
            if response.status_code == 200 and data:
                print("✅ Database Test: SUCCESS")
                print(f"   Database Type: {data.get('database_type')}")
                print(f"   Database URI: {data.get('database_uri')}")
                print(f"   User Count: {data.get('user_count')}")
                print(f"   Query Executed: {data.get('query_executed')}")
            else:
                print("❌ Database Test: FAILED")
                if data:
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                    print(f"   Message: {data.get('message', 'No message')}")
                else:
                    print(f"   HTTP Status: {response.status_code}")
                    print(f"   Response: {response.data.decode('utf-8') if response.data else 'No response'}")

    @app.cli.command('app-info')
    def app_info_command():
        """Displays application configuration information."""
        with app.test_client() as client:
            response = client.get('/internal/app-info', follow_redirects=True)
            data = response.get_json()
            
            if response.status_code == 200 and data:
                print("\n📊 Application Information:\n")
                print(f"App Name: {data.get('app_name')}")
                print(f"API Version: {data.get('api_version')}\n")
                
                print("Database Configuration:")
                db_info = data.get('database', {})
                print(f"  Type: {db_info.get('type')}")
                print(f"  URI: {db_info.get('uri')}")
                print(f"  Track Modifications: {db_info.get('track_modifications')}\n")
                
                print("Security Configuration:")
                sec_info = data.get('security', {})
                print(f"  MFA Enabled: {sec_info.get('mfa_enabled')}")
                print(f"  Secret Key Configured: {sec_info.get('secret_key_configured')}")
                print(f"  Testing Mode: {sec_info.get('testing_mode')}\n")
                
                print("Email Configuration:")
                email_info = data.get('email', {})
                print(f"  SMTP Server: {email_info.get('smtp_server')}")
                print(f"  SMTP Port: {email_info.get('smtp_port')}")
                print(f"  Email Configured: {email_info.get('email_configured')}\n")
                
                print("OAuth Configuration:")
                oauth_info = data.get('oauth', {})
                print(f"  Google OAuth Configured: {oauth_info.get('google_oauth_configured')}\n")
                
                print("Paths:")
                paths_info = data.get('paths', {})
                print(f"  Upload Folder: {paths_info.get('upload_folder')}\n")
            else:
                print("❌ Failed to retrieve app info")
                if data:
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                    print(f"   Message: {data.get('message', 'No message')}")
                else:
                    print(f"   HTTP Status: {response.status_code}")
                    print(f"   Response: {response.data.decode('utf-8') if response.data else 'No response'}")

    # --- Importar CLI Commands (Data Import) ---
    from . import cli
    cli.register_commands(app)

    @app.cli.command('test-email')
    @click.option('--recipient', default=None, help='Email recipient (defaults to configured EMAIL_USERNAME)')
    def test_email_command(recipient):
        """Tests email configuration by sending a test email."""
        with app.test_client() as client:
            url = '/internal/test-email'
            if recipient:
                url += f'?recipient={recipient}'
            
            response = client.get(url, follow_redirects=True)
            data = response.get_json()
            
            if response.status_code == 200 and data:
                print("✅ Email Test: SUCCESS")
                print(f"   Recipient: {data.get('recipient')}")
                print(f"   SMTP Server: {data.get('smtp_server')}:{data.get('smtp_port')}")
                print(f"   Message: {data.get('message')}")
            else:
                print("❌ Email Test: FAILED")
                if data:
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                    print(f"   Message: {data.get('message', 'No message')}")
                    if 'config' in data:
                        print("   Configuration status:")
                        for key, value in data['config'].items():
                            status = "✓" if value else "✗"
                            print(f"     {status} {key}")
                else:
                    print(f"   HTTP Status: {response.status_code}")

    @app.cli.command('health-check')
    def health_check_command():
        """Performs comprehensive health check of all system components."""
        with app.test_client() as client:
            response = client.get('/internal/health-check', follow_redirects=True)
            data = response.get_json()
            
            if data:
                overall_status = data.get('status', 'unknown')
                
                if overall_status == 'healthy':
                    print("✅ System Health: HEALTHY\n")
                else:
                    print("❌ System Health: UNHEALTHY\n")
                
                print("Component Status:")
                print("-" * 50)
                
                components = data.get('components', {})
                for component, info in components.items():
                    status = info.get('status', 'unknown')
                    
                    if status == 'healthy':
                        icon = "✅"
                    elif status == 'configured':
                        icon = "ℹ️ "
                    elif status == 'disabled':
                        icon = "⚪"
                    elif status == 'not_configured':
                        icon = "⚠️ "
                    else:
                        icon = "❌"
                    
                    print(f"{icon} {component.upper()}: {status}")
                    
                    # Show additional details
                    for key, value in info.items():
                        if key != 'status' and not key.startswith('_'):
                            print(f"   {key}: {value}")
                
                print("-" * 50)
                print(f"\nTimestamp: {data.get('timestamp')}")
                
                # Exit with appropriate code
                import sys
                sys.exit(0 if overall_status == 'healthy' else 1)
            else:
                print("❌ Failed to retrieve health check data")
                print(f"   HTTP Status: {response.status_code}")
                import sys
                sys.exit(1)

    @app.cli.command('test-security')
    def test_security_command():
        """Performs security configuration audit."""
        with app.test_client() as client:
            response = client.get('/internal/test-security', follow_redirects=True)
            data = response.get_json()
            
            if response.status_code == 200 and data:
                print("\n🔒 Security Configuration Audit\n")
                print("=" * 60)
                
                # Show summary first
                summary = data.get('summary', {})
                critical = summary.get('critical_issues', 0)
                warnings = summary.get('warnings', 0)
                recommendations = summary.get('recommendations', 0)
                
                print(f"\nSummary:")
                if critical > 0:
                    print(f"  🔴 Critical Issues: {critical}")
                if warnings > 0:
                    print(f"  ⚠️  Warnings: {warnings}")
                if recommendations > 0:
                    print(f"  💡 Recommendations: {recommendations}")
                
                if critical == 0 and warnings == 0:
                    print("  ✅ No critical issues or warnings found")
                
                # Show detailed checks
                print(f"\nDetailed Checks:")
                print("-" * 60)
                
                checks = data.get('checks', {})
                for check_name, check_info in checks.items():
                    status = check_info.get('status', 'unknown')
                    message = check_info.get('message', '')
                    
                    if status == 'ok':
                        icon = "✅"
                    elif status == 'info':
                        icon = "ℹ️ "
                    elif status == 'warning':
                        icon = "⚠️ "
                    elif status == 'critical':
                        icon = "🔴"
                    else:
                        icon = "❓"
                    
                    print(f"{icon} {check_name.upper().replace('_', ' ')}")
                    print(f"   {message}")
                
                # Show warnings
                warnings_list = data.get('warnings', [])
                if warnings_list:
                    print(f"\n⚠️  Warnings:")
                    print("-" * 60)
                    for warning in warnings_list:
                        print(f"  • {warning}")
                
                # Show recommendations
                recommendations_list = data.get('recommendations', [])
                if recommendations_list:
                    print(f"\n💡 Recommendations:")
                    print("-" * 60)
                    for rec in recommendations_list:
                        print(f"  • {rec}")
                
                print("\n" + "=" * 60)
                print(f"Audit completed at: {data.get('timestamp')}\n")
            else:
                print("❌ Failed to retrieve security audit data")
                if data:
                    print(f"   Error: {data.get('error', 'Unknown error')}")
                else:
                    print(f"   HTTP Status: {response.status_code}")

    # --- Plugin System: Dynamic Loading ---
    try:
        import opsdeck_enterprise
        opsdeck_enterprise.init_plugin(app)
        app.logger.info(f"✓ Plugin Enterprise cargado: v{opsdeck_enterprise.__version__}")
    except ImportError:
        app.logger.info("Iniciando OpsDeck en modo estándar (sin plugins)")
    except Exception as e:
        app.logger.error(f"Error cargando plugin Enterprise: {str(e)}")
        # No fallar la app si el plugin falla, solo registrar el error

    return app

