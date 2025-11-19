# OpsDeck

OpsDeck is a unified IT operations platform designed to streamline asset management, vendor relations, and compliance. It centralizes disparate tools into a single control center, providing visibility and control over the entire IT ecosystem.

## Key Features

### Asset Lifecycle Management
- **Asset Tracking**: Monitor hardware, software, and peripherals from purchase to end-of-life.
- **Assignments**: Track asset assignments to users and locations.
- **Warranty Monitoring**: Automated tracking of warranty expiration dates.
- **Maintenance**: Log repairs, upgrades, and maintenance activities.
- **Disposal**: Manage end-of-life processes with formal disposal records.

### Governance, Risk & Compliance (GRC)
- **Compliance Linking**: Link any system object (Asset, Policy, Supplier) to specific Framework Controls (e.g., ISO 27001) to demonstrate compliance.
- **Framework Management**: Manage compliance frameworks and controls.
- **Policy Management**: Version-controlled policy documents with user acknowledgement tracking.
- **Risk Register**: Document and score organizational risks.
- **Incident Management**: Workflow for logging, investigating, and resolving security incidents.
- **Audits**: Conduct and record asset audits.

### Procurement & Finance
- **Supplier Database**: Centralized vendor management.
- **Purchase Orders**: Track purchases linked to budgets and suppliers.
- **Budget Management**: Define and monitor budgets by category.
- **Subscription Tracking**: Monitor recurring costs and renewal dates.
- **Financial Reporting**: Depreciation reports, spend analysis, and forecasting.

### Core Operations
- **User Directory**: Manage users, groups, and roles.
- **Training Hub**: Assign and track completion of training courses.
- **Documentation**: Internal knowledge base.

## Tech Stack
- **Backend**: Python 3, Flask
- **Database**: SQLAlchemy ORM, Flask-Migrate (SQLite default)
- **Frontend**: Jinja2 Templates, Bootstrap 5, Tom Select (for enhanced UI components)
- **Scheduling**: APScheduler

## Setup and Installation

### 1. Prerequisites
- Python 3.10+
- Virtual environment tool (venv)

### 2. Installation
```bash
# Clone the repository
# git clone https://github.com/pixelotes/opsdeck.git
# cd opsdeck

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:

```bash
# Flask Configuration
SECRET_KEY='your-secret-key'
FLASK_APP=run:app

# Database (Optional, defaults to local SQLite)
# DATABASE_URL='sqlite:///opsdeck.db'

# Email Settings (Optional)
SMTP_SERVER='smtp.gmail.com'
SMTP_PORT=587
EMAIL_USERNAME='your-email@example.com'
EMAIL_PASSWORD='your-app-password'
```

### 4. Initialization
Initialize the database and create the default admin user:

```bash
# Initialize migrations
flask db init

# Create migration script
flask db migrate -m "Initial migration"

# Apply migrations
flask db upgrade

# Create default admin user (admin/admin123)
flask init-db
```

## Usage
Run the application:

```bash
flask run
```

Access the application at `http://127.0.0.1:5000`.

**Default Credentials:**
- Username: `admin`
- Password: `admin123` (Change immediately after login)

## Documentation
For more detailed information, please refer to the `documentation/` directory:
- [Database Structure](documentation/database_structure.md)
- [Workflows](documentation/workflows.md)
