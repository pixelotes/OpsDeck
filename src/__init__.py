# src/__init__.py

import os
import atexit
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from .extensions import db, migrate
from .routes import main_bp
from .models import AppUser
from . import notifications

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

    # --- Register Blueprints ---
    app.register_blueprint(main_bp)

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
            if not AppUser.query.first():
                admin_user = AppUser(username='admin')
                admin_user.set_password('admin123')
                db.session.add(admin_user)
                db.session.commit()
                print("Database initialized and admin user created.")

    return app