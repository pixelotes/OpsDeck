# src/__init__.py

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import atexit
import click
from flask import (Flask, session, render_template, request, redirect, url_for,
                   jsonify, flash)
from apscheduler.schedulers.background import BackgroundScheduler
import ecs_logging
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_dance.contrib.google import make_google_blueprint
from flask_talisman import Talisman
from flask_smorest import Api

from .extensions import db, migrate

from .models import User, Contract, ContractItem
from . import notifications
import markdown
from markupsafe import Markup
from .seeder_prod import seed_production_frameworks
import re

# --- Rate Limiter (global instance for use in blueprints) ---
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["10000 per day", "1000 per hour"]
)

# --- CSRF Protection ---
from flask_wtf.csrf import CSRFProtect
from src.utils.timezone_helper import today
from .utils.json_api import request_wants_json

#: Endpoints reachable without authentication.
#:
#: Module level rather than a local inside the login guard so the JSON contract test can
#: derive the exception list from the guard itself instead of keeping a copy that drifts:
#: the health check and the internal CLI routes answer JSON and are meant to be
#: unauthenticated, so they are the one group that must not be asserted to return 401.
PUBLIC_ENDPOINTS = [
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

    # 2. Handler for console output (JSON ECS format)
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

    # Cache static assets aggressively (1 year). Cache-busting is handled by the
    # mtime-based ?v= query param added in `add_static_cache_buster` below, so the
    # browser re-fetches a file only when it actually changes on disk.
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # 1 year, in seconds

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

    # Cap the size of any request body. Without this an authenticated user can fill the
    # disk one upload at a time. It applies to every request, not only to attachments,
    # so it also bounds imports and form posts; 5 MB covers the evidence documents and
    # import files this app deals with. Raise MAX_UPLOAD_MB where bigger files are
    # legitimate. Requests over the limit are answered by the 413 handler below.
    try:
        max_upload_mb = int(os.environ.get('MAX_UPLOAD_MB', '5'))
    except ValueError:
        max_upload_mb = 5
    max_upload_mb = max(1, max_upload_mb)
    app.config['MAX_UPLOAD_MB'] = max_upload_mb
    app.config['MAX_CONTENT_LENGTH'] = max_upload_mb * 1024 * 1024

    # File types accepted by every upload in the app: photos, invoices, evidence
    # documents and the archives they arrive in. Enforced in reject_disallowed_uploads
    # below rather than per route, because there are two dozen upload sites and one
    # check that cannot be forgotten beats twenty-four that can.
    #
    # Deliberately absent: svg, html and htm, which can carry script. They are harmless
    # while attachments download instead of rendering (as_attachment=True), but that is
    # one changed argument away from stored XSS. Executables are absent for the obvious
    # reason. Override with UPLOAD_ALLOWED_EXTENSIONS as a comma-separated list.
    default_extensions = (
        # images and scans
        'jpg,jpeg,png,gif,bmp,tga,webp,tif,tiff,heic,heif,'
        # documents
        'pdf,odt,ods,odp,doc,docx,xls,xlsx,ppt,pptx,rtf,txt,md,'
        # data
        'csv,tsv,json,xml,log,'
        # archives
        'zip,7z,gz,tar,tgz,rar,'
        # mail, for phishing and incident evidence
        'eml,msg,'
        # certificates
        'pem,crt,cer,der'
    )
    configured = os.environ.get('UPLOAD_ALLOWED_EXTENSIONS', default_extensions)
    app.config['UPLOAD_ALLOWED_EXTENSIONS'] = {
        ext.strip().lower().lstrip('.')
        for ext in configured.split(',') if ext.strip()
    }

    # Email configuration
    app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '587'))
    app.config['EMAIL_USERNAME'] = os.environ.get('EMAIL_USERNAME', '')
    app.config['EMAIL_PASSWORD'] = os.environ.get('EMAIL_PASSWORD', '')
    app.config['EMAIL_SENDER_NAME'] = os.environ.get('EMAIL_SENDER_NAME', '')
    app.config['WEBHOOK_URL'] = os.environ.get('WEBHOOK_URL', '')

    # Public base URL of this deployment (e.g. https://opsdeck.acme.com), used to
    # build absolute, clickable links in notifications ({{ event_url }}). Empty =
    # links fall back to relative paths (not clickable from email/chat).
    app.config['APP_BASE_URL'] = os.environ.get('APP_BASE_URL', '').rstrip('/')

    # Behind a reverse proxy (e.g. prod), honour X-Forwarded-* so request.scheme /
    # host / url reflect the real public origin instead of the internal one. Without
    # this, absolute URLs (email links, OAuth callbacks) carry the internal host.
    # Opt-in via TRUST_PROXY so direct/dev deployments are unaffected.
    if os.environ.get('TRUST_PROXY', '').lower() in ('1', 'true', 'yes', 'on'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
        # Static files and the debounced global-search AJAX endpoint
        # (fired on every keystroke) must not count against the rate limit.
        return request.endpoint in ('static', 'main.search')

    @app.url_defaults
    def add_static_cache_buster(endpoint, values):
        # Append ?v=<mtime> to static URLs so the 1-year browser cache is
        # invalidated automatically whenever the underlying file changes.
        if endpoint != 'static' or 'filename' not in values:
            return
        try:
            mtime = int(os.stat(os.path.join(app.static_folder, values['filename'])).st_mtime)
        except OSError:
            return
        values['v'] = mtime

    # Configure CSRF to not protect JSON requests (for AJAX endpoints)
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    app.config['WTF_CSRF_ENABLED'] = True
    csrf.init_app(app)
    
    # Disable HTTPS enforcement in development (debug mode) or when explicitly disabled
    is_development = app.debug or insecure_transport or os.environ.get('FLASK_ENV') == 'development'

    # --- Content Security Policy (baseline) ---
    # All first-party assets are vendored under /static, so 'self' covers them.
    #
    # 'unsafe-eval' is gone. It was granted because Mermaid was said to need it, which
    # stopped being true: Mermaid 11 contains no eval() and no `new Function`, and every
    # dynamic-code site left in any vendored bundle is a polyfill that a modern browser
    # never reaches — four spellings of `globalThis || Function("return this")()`, which
    # short-circuit because globalThis and self exist, and Swagger UI's
    # Function.prototype.bind shim, used only when native bind is missing. See
    # tests/test_csp.py, which pins that inventory so a dependency bump that introduces
    # a real eval fails the build instead of silently needing this back.
    #
    # script-src no longer allows inline script. The 137 on* handlers became delegated
    # listeners and the 91 inline <script> blocks carry a per-request nonce, which
    # Talisman adds to the header and templates read with csp_nonce(). Both halves had to
    # land together: a nonce makes the browser ignore 'unsafe-inline' outright, so a
    # single un-nonced block or leftover handler would have broken on the same deploy.
    #
    # style-src keeps it, and probably always will: 328 style="" attributes, and a nonce
    # cannot cover an attribute — only a <style> block. Removing it would mean moving
    # every one of those into a stylesheet for a much smaller gain than this.
    content_security_policy = {
        'default-src': "'self'",
        'script-src': ["'self'"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", 'data:'],
        'font-src': ["'self'", 'data:'],
        'connect-src': "'self'",
        'frame-ancestors': "'self'",
        'base-uri': "'self'",
        'form-action': "'self'",
        'object-src': "'none'",
    }
    # Escape hatches (no redeploy needed): CSP_ENABLED=False disables it entirely;
    # CSP_REPORT_ONLY=True sends Content-Security-Policy-Report-Only (logs violations
    # in the browser console without blocking) — useful to verify before enforcing.
    csp_enabled = os.environ.get('CSP_ENABLED', 'True').lower() == 'true'
    csp_report_only = os.environ.get('CSP_REPORT_ONLY', 'False').lower() == 'true'

    talisman.init_app(
        app,
        content_security_policy=(content_security_policy if csp_enabled else None),
        content_security_policy_nonce_in=['script-src'],
        content_security_policy_report_only=csp_report_only,
        force_https=not is_development,
    )

    # --- Configure Logging (ECS format with rotation) ---
    configure_logging(app)

    # --- Initialize API ---
    api = Api(app)
    from .api import api_bp
    api.register_blueprint(api_bp)

    # --- Custom Error Handlers ---
    # The error pages answer JSON for a JSON caller for the same reason the login guard
    # does. abort(404) is the common way in: a JSON endpoint that looks up a missing row
    # with get_or_404 would otherwise hand a fetch() client an HTML error page, which is
    # the original bug arriving by a different route.
    @app.errorhandler(404)
    def page_not_found(e):
        if request_wants_json():
            return jsonify({'error': 'Not found.'}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        if request_wants_json():
            return jsonify({'error': 'Forbidden.'}), 403
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(413)
    def payload_too_large(e):
        """Answer an over-sized request body with something the caller can act on.

        Flask aborts the request as soon as the limit is exceeded, so without this the
        user gets a bare Werkzeug error page with no hint about what went wrong or how
        big the file may be. API callers get JSON for the same reason the login guard
        does: a fetch() client cannot read an HTML page.
        """
        limit_mb = app.config.get('MAX_UPLOAD_MB', 5)
        message = f'That file is too large. The limit is {limit_mb} MB.'

        if request_wants_json():
            return jsonify({'error': message}), 413

        from .utils.redirects import safe_redirect_target
        flash(message, 'danger')
        return redirect(safe_redirect_target(request.referrer)), 302

    @app.errorhandler(429)
    def ratelimit_handler(e):
        from .utils.logger import log_audit
        log_audit(
            event_type='security.rate_limit_breach',
            action='block',
            outcome='failure',
            error_message=e.description
        )
        if request_wants_json():
            return jsonify({'error': e.description or 'Too many requests.'}), 429
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
        # Deliberately not str(e): the HTML page shows nothing either, and a JSON caller
        # is the one whose response tends to end up logged or displayed verbatim.
        if request_wants_json():
            return jsonify({'error': 'Internal error.'}), 500
        return render_template('errors/500.html'), 500
    
    # --- REGISTER THE CUSTOM MARKDOWN FILTER ---
    @app.template_filter('email_html')
    def email_html_filter(value):
        """Render an email body inside the app with anything executable removed.

        Bodies are sanitised on save too; this covers rows stored before that existed,
        and means the page does not depend on the write path having been the only one.
        """
        from .utils.sanitize import sanitize_email_html
        return Markup(sanitize_email_html(value or ''))

    @app.template_filter('markdown')
    def markdown_filter(s):
        """Convert markdown to HTML with common extensions, then sanitize.

        Sanitization is required: the markdown library does NOT strip raw HTML,
        so unsanitized output of user-supplied text is a stored-XSS vector.
        """
        from .utils.sanitize import sanitize_html
        html = markdown.markdown(s, extensions=[
            'extra',           # Includes tables, fenced code blocks, footnotes, etc.
            'codehilite',      # Syntax highlighting for code blocks
            'nl2br',           # Convert newlines to <br>
            'sane_lists',      # Better list handling
            'toc',             # Table of contents
            'smarty'           # Smart quotes and dashes
        ])
        return Markup(sanitize_html(html))
    
    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """Converts newlines in a string to HTML <br> tags."""
        return Markup(re.sub(r'\n', '<br>\n', s))

    # --- Register Blueprints ---
    from .routes.main import main_bp
    from .routes.assets import assets_bp
    from .routes.peripherals import peripherals_bp
    from .routes.brands import brands_bp
    from .routes.asset_models import asset_models_bp
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
    app.register_blueprint(asset_models_bp, url_prefix='/asset-models')
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

    from .routes.requests import requests_bp
    app.register_blueprint(requests_bp, url_prefix='/requests')

    from .routes.roadmaps import roadmaps_bp
    app.register_blueprint(roadmaps_bp, url_prefix='/roadmaps')

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

    from .routes.event_rules import event_rules_bp
    app.register_blueprint(event_rules_bp, url_prefix='/settings/event-rules')
    
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

    # --- Risk matrix ---
    @app.context_processor
    def inject_risk_matrix():
        """Make the matrix available to any template that renders a severity.

        risk_level_colour replaces a chain of conditionals that was copied into four
        templates; having it in one place is what stops the heatmap's colours drifting
        from the badges printed next to it.
        """
        from .services.risk_scale import current_appetite, current_scale, level_colour
        return {
            'risk_level_colour': level_colour,
            'current_risk_scale': current_scale,
            'current_risk_appetite': current_appetite,
        }

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
        # Endpoints reachable without authentication (whitelist)
        public_endpoints = PUBLIC_ENDPOINTS

        # Permitir acceso si:
        # 1. The user is already authenticated (user_id is in the session)
        if 'user_id' in session:
            return None

        # 2. The request is for a static file, or has no endpoint at all (404)
        if request.endpoint is None:
            return None
            
        # 3. The request targets a public endpoint
        if request.endpoint in public_endpoints:
            return None
            
        # 4. Allow the API endpoints, which authenticate by token
        # Check by path since flask-smorest uses different endpoint naming
        if request.path and request.path.startswith('/api/v1'):
            return None

        # 5. API-style requests must fail as JSON rather than with a 302 to the login
        # page: a fetch() client would parse that HTML as if it were the response and
        # the authentication failure would go unnoticed.
        if request_wants_json():
            return jsonify({'error': 'Authentication required.'}), 401

        # Nothing matched, so block and redirect to the login page
        # Remember the requested URL so the user lands there after logging in
        return redirect(url_for('main.login', next=request.url))


    # --- GLOBAL UPLOAD TYPE GUARD ---
    @app.before_request
    def reject_disallowed_uploads():
        """Refuse a file whose extension is not on the allowlist, before any route runs.

        Enforced here because uploads happen at two dozen places across thirteen
        blueprints — attachments, resumes, audit evidence, training certificates,
        activity executions — and none of them validated anything. A single hook covers
        the ones that exist and the ones added later.

        Extension only: content sniffing would need a new dependency, and the point of
        the check is to keep obviously-wrong files out of a folder that is served with
        as_attachment=True, not to prove a file is what it claims.
        """
        if not request.files:
            return None

        allowed = app.config.get('UPLOAD_ALLOWED_EXTENSIONS') or set()
        for field in request.files:
            for storage in request.files.getlist(field):
                filename = (storage.filename or '').strip()
                if not filename:
                    continue        # nothing chosen; the route reports that itself
                extension = os.path.splitext(filename)[1].lower().lstrip('.')
                if extension in allowed:
                    continue

                described = f'.{extension}' if extension else 'no extension'
                message = (f'That file type is not accepted ({described}). '
                           f'Allowed types: {", ".join(sorted(allowed))}.')

                if request_wants_json():
                    return jsonify({'error': message}), 415

                from .utils.redirects import safe_redirect_target
                flash(message, 'danger')
                return redirect(safe_redirect_target(request.referrer))
        return None

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
        # Event engine - match committed changes (AuditLog) against EventRules and
        # enqueue notifications. Runs slightly ahead of the comms queue below.
        from .services.event_engine import process_event_rules
        scheduler.add_job(
            func=process_event_rules,
            args=[app],
            trigger="interval",
            minutes=2,
            id="event_engine",
            replace_existing=True
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
    
    @app.cli.command("db-doctor")
    @click.option('--fix', is_flag=True, help='Repair alembic tracking / apply pending migrations where safe.')
    def db_doctor_command(fix):
        """Diagnose (and optionally --fix) DB schema vs migration state.

        Verifies alembic version tracking and compares the live schema against
        the models. Handy after rough deploys where alembic_version drifts.
        Exits 1 if problems remain.
        """
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.migration import MigrationContext
        from alembic.autogenerate import compare_metadata

        def _fmt(d):
            op = d[0]
            try:
                if op in ('add_table', 'remove_table'):
                    return f"{op}: {d[1].name}"
                if op in ('add_column', 'remove_column'):
                    return f"{op}: {d[2]}.{d[3].name}"
                if op.startswith('modify'):
                    return f"{op}: {d[2]}.{d[3]}"
            except Exception:
                pass
            return str(op)

        with app.app_context():
            cfg = Config('migrations/alembic.ini')
            cfg.set_main_option('script_location', 'migrations')
            script = ScriptDirectory.from_config(cfg)
            heads = list(script.get_heads())
            head = heads[0] if len(heads) == 1 else None

            inspector = sa_inspect(db.engine)
            all_tables = inspector.get_table_names()
            has_version = 'alembic_version' in all_tables
            tables = [t for t in all_tables if t != 'alembic_version']

            with db.engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                current = ctx.get_current_revision()
                diff = compare_metadata(ctx, db.metadata)

            plugin_removes = [d for d in diff if d[0] == 'remove_table']
            drift = [d for d in diff if d[0] != 'remove_table']

            stale = False
            if current is not None:
                try:
                    script.get_revision(current)
                except Exception:
                    stale = True

            tracking_broken = (not has_version) or (current is None) or stale
            behind = bool(head and current and not stale and current != head)
            empty = len(tables) == 0

            click.echo("=== Alembic tracking ===")
            click.echo(f"  Migration head(s): {', '.join(heads) or '(none)'}")
            click.echo(f"  Tables in DB:      {len(tables)}")
            if not has_version:
                tstatus = 'MISSING — no alembic_version table'
            elif current is None:
                tstatus = 'EMPTY — alembic_version has no row'
            elif stale:
                tstatus = f'STALE — current {current!r} not found in migrations'
            elif behind:
                tstatus = f'BEHIND — at {current}, head is {head}'
            else:
                tstatus = f'OK — {current}'
            click.echo(f"  Tracking status:   {tstatus}")

            click.echo("=== Schema vs models ===")
            if empty:
                click.echo("  EMPTY DB — no application tables present")
            elif drift:
                click.echo(f"  DRIFT — {len(drift)} difference(s) vs models:")
                for d in drift[:50]:
                    click.echo(f"    - {_fmt(d)}")
                if len(drift) > 50:
                    click.echo(f"    ... and {len(drift) - 50} more")
            else:
                click.echo("  OK — schema matches models")
            if plugin_removes:
                click.echo(f"  ({len(plugin_removes)} extra table(s) not in models — likely optional plugins)")

            healthy = not (tracking_broken or behind or drift or empty)
            if healthy:
                click.echo("\n✓ Database is healthy.")
                return

            if not fix:
                click.echo("\n⚠ Issues detected. Re-run with --fix to repair where safe.")
                raise SystemExit(1)

            from flask_migrate import stamp, upgrade
            click.echo("\n--- Applying fixes (--fix) ---")

            if empty:
                upgrade()
                click.echo("  Empty DB: applied all migrations (upgrade).")
            elif drift and tracking_broken:
                click.echo("  Schema differs from models AND tracking is broken.")
                click.echo("  Not stamping (would mislabel state). Investigate, then: flask db migrate")
                raise SystemExit(1)
            elif tracking_broken:
                if stale and has_version:
                    with db.engine.connect() as conn:
                        conn.execute(sa_text('DELETE FROM alembic_version'))
                        conn.commit()
                    click.echo("  Cleared stale alembic_version row.")
                stamp(revision='head')
                click.echo(f"  Stamped head ({head}). Schema already matched models.")
            elif behind:
                upgrade()
                click.echo("  Applied pending migrations (upgrade).")

            if drift and not empty:
                click.echo("  NOTE: schema drift vs models remains — generate a migration: flask db migrate")
                raise SystemExit(1)

            click.echo("✓ Done.")

    # --- Seed the db with fake demo data ---
    @app.cli.command("seed-db-demodata")
    def seed_db_command():
        """Seeds the database with demo data."""
        from .seeder import seed_data
        seed_data()

    @app.cli.command('seed-db-prod')
    def seed_prod_command():
        """Load the production master data (frameworks and threat types)."""
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
                
                print("\nSummary:")
                if critical > 0:
                    print(f"  🔴 Critical Issues: {critical}")
                if warnings > 0:
                    print(f"  ⚠️  Warnings: {warnings}")
                if recommendations > 0:
                    print(f"  💡 Recommendations: {recommendations}")
                
                if critical == 0 and warnings == 0:
                    print("  ✅ No critical issues or warnings found")
                
                # Show detailed checks
                print("\nDetailed Checks:")
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
                    print("\n⚠️  Warnings:")
                    print("-" * 60)
                    for warning in warnings_list:
                        print(f"  • {warning}")
                
                # Show recommendations
                recommendations_list = data.get('recommendations', [])
                if recommendations_list:
                    print("\n💡 Recommendations:")
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
        app.logger.info("Starting OpsDeck in standard mode (no plugins)")
    except Exception as e:
        app.logger.error(f"Error cargando plugin Enterprise: {str(e)}")
        # No fallar la app si el plugin falla, solo registrar el error

    return app

