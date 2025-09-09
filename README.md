# RenewalGuard 🛡️
RenewalGuard is a self-hosted Flask application designed to help you manage renewals for all your recurring services, contracts, licenses, domains, and certificates. Never miss a renewal date again and keep track of all associated costs, suppliers, contacts, and payment methods in one central place.

## Features ✨

* Dashboard Overview: At-a-glance view of upcoming renewals with configurable time periods (7, 30, 90 days) and a summary of total costs.
* Comprehensive Management: Full CRUD (Create, Read, Update, Delete) functionality for:
  + Services: Track any type of recurring service or subscription.
  + Suppliers: Manage vendor information.
  + Contacts: Keep a record of contacts associated with suppliers and services.
  + Payment Methods: Link services to specific credit cards or bank accounts to easily see dependencies.
* Interlinked Detail Views: Navigate seamlessly between services, suppliers, contacts, and payment methods to see all related information.
* Calendar View: Visualize all your upcoming renewal dates on a full-page calendar.
* Configurable Notifications: Set up automatic alerts via Email and Webhooks. You can configure when you get notified (e.g., 30, 14, and 7 days before a renewal) and how.
* Background Scheduler: A built-in scheduler automatically checks for renewals and sends notifications based on your settings.

## Tech Stack
* Backend: Python 3, Flask
* Database: SQLAlchemy ORM, Flask-Migrate (for database migrations). Defaults to SQLite.
* Frontend: Jinja2 Templates, Bootstrap 5
* Scheduling: APScheduler

## Setup and Installation
Follow these steps to get the application running locally.

1. Prerequisites
* Python 3.10+
* A virtual environment tool (venv)

2. Installation
```bash

# Clone the repository (or use your existing project folder)
# git clone https://github.com/your-username/renewalguard.git
# cd renewalguard

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the required Python packages
pip install -r requirements.txt
```
3. Configuration
The application is configured using environment variables. Create a file named .env in the root of the project and add the following variables.

`.env.example`:

```bash

# Flask Configuration
SECRET_KEY='a-very-strong-and-random-secret-key'
FLASK_APP=run:app

# Database URL (optional, defaults to a local SQLite file)
# DATABASE_URL='sqlite:///renewals.db'

# SMTP Email Notification Settings (optional)
SMTP_SERVER='smtp.gmail.com'
SMTP_PORT=587
EMAIL_USERNAME='your-email@gmail.com'
EMAIL_PASSWORD='your-gmail-app-password'

# Webhook Notification Settings (optional)
# WEBHOOK_URL='https://your-webhook-provider.com/...'
```
* `SECRET_KEY`: Required. A long, random string used for signing sessions.
* `FLASK_APP`: Required. Tells Flask how to load the application.
* SMTP variables: Only required if you want to use email notifications. For Gmail, you will need to generate an "App Password".

4. Initialize the Database
The first time you run the app, you need to create the database and the initial admin user.

```bash

# 1. Initialize the migrations folder (only run this once ever)
flask db init

# 2. Create the first migration script
flask db migrate -m "Initial migration"

# 3. Apply the migration to create all tables
flask db upgrade

# 4. Create the default admin user (admin/admin123)
flask init-db
```

## Usage
To run the application, use the Flask CLI:

```bash

flask run
```
The application will be available at http://127.0.0.1:5000.

* Default Login:
  + Username: admin
  + Password: admin123 (It's recommended to change this)