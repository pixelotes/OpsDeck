# src/__init__.py

import os
import atexit
from flask import Flask, session
from apscheduler.schedulers.background import BackgroundScheduler

from .extensions import db, migrate
from .models import User
from . import notifications # Added the missing import
import markdown
from markupsafe import Markup
import re

def create_app():
    """
    Application factory function to create and configure the Flask app.
    """
    app = Flask(__name__)

    # --- Configuration ---
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///../data/renewals.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
    app.config['WEBHOOK_URL'] = os.environ.get('WEBHOOK_URL', '')

    # --- Initialize Extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    
    # --- REGISTER THE CUSTOM MARKDOWN FILTER ---
    @app.template_filter('markdown')
    def markdown_filter(s):
        return markdown.markdown(s)
    
    @app.template_filter('nl2br')
    def nl2br_filter(s):
        """Converts newlines in a string to HTML <br> tags."""
        return Markup(re.sub(r'\n', '<br>\n', s))

    # --- Register Blueprints ---
    from .routes.main import main_bp
    from .routes.assets import assets_bp
    from .routes.peripherals import peripherals_bp
    from .routes.locations import locations_bp
    from .routes.suppliers import suppliers_bp
    from .routes.contacts import contacts_bp
    from .routes.users import users_bp
    from .routes.groups import groups_bp
    from .routes.payment_methods import payment_methods_bp
    from .routes.tags import tags_bp
    from .routes.subscriptions import subscriptions_bp
    from .routes.licenses import licenses_bp
    from .routes.purchases import purchases_bp
    from .routes.budgets import budgets_bp
    from .routes.reports import reports_bp
    from .routes.attachments import attachments_bp
    from .routes.treeview import treeview_bp
    from .routes.admin import admin_bp
    from .routes.opportunities import opportunities_bp
    from .routes.policies import policies_bp
    from .routes.compliance import compliance_bp
    from .routes.risk import risk_bp
    from .routes.training import training_bp
    from .routes.maintenance import maintenance_bp
    from .routes.disposal import disposal_bp
    from .routes.leads import leads_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(assets_bp, url_prefix='/assets')
    app.register_blueprint(peripherals_bp, url_prefix='/peripherals')
    app.register_blueprint(locations_bp, url_prefix='/locations')
    app.register_blueprint(suppliers_bp, url_prefix='/suppliers')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(users_bp, url_prefix='/users')
    app.register_blueprint(groups_bp, url_prefix='/groups')
    app.register_blueprint(payment_methods_bp, url_prefix='/payment-methods')
    app.register_blueprint(tags_bp, url_prefix='/tags')
    app.register_blueprint(subscriptions_bp, url_prefix='/subscriptions')
    app.register_blueprint(licenses_bp)
    app.register_blueprint(purchases_bp, url_prefix='/purchases')
    app.register_blueprint(budgets_bp, url_prefix='/budgets')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(attachments_bp, url_prefix='/attachments')
    app.register_blueprint(treeview_bp, url_prefix='/tree-view')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(opportunities_bp, url_prefix='/opportunities')
    app.register_blueprint(policies_bp, url_prefix='/policies')
    app.register_blueprint(compliance_bp, url_prefix='/compliance')
    app.register_blueprint(risk_bp, url_prefix='/risk')
    app.register_blueprint(training_bp, url_prefix='/training')
    app.register_blueprint(maintenance_bp)
    app.register_blueprint(disposal_bp)
    app.register_blueprint(leads_bp)

    # --- Make user role avaiable in all templates ---
    @app.context_processor
    def inject_user_role():
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id) # Changed from AppUser
            if user:
                return dict(current_user_role=user.role)
        return dict(current_user_role=None)

    # --- Force admin to change the default password ---
    from .routes.main import password_change_required
    @app.before_request
    def before_request_hook():
        # This now correctly calls the updated password_change_required decorator
        password_change_required(lambda: None)()

    # --- Scheduler and Notifications ---
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=notifications.check_upcoming_renewals,
        args=[app],
        trigger="interval",
        days=1
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())

    # --- CLI Commands ---
    @app.cli.command("init-db")
    def init_db_command():
        """Creates the database tables and a default admin user."""
        with app.app_context():
            db.create_all()
            if not User.query.first(): # Changed from AppUser
                admin_user = User(name='admin', email='admin@example.com', role='admin') # Changed to User
                admin_user.set_password('admin123')
                db.session.add(admin_user)
                db.session.commit()
                print("Database initialized and admin user created.")
    
    # --- Seed the db with fake demo data ---
    @app.cli.command("seed-db")
    def seed_db_command():
        """Seeds the database with demo data."""
        from .seeder import seed_data
        seed_data()

    return app