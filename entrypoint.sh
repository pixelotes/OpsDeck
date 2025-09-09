#!/bin/sh

# This is the path inside the container where the database will live
DB_FILE="/app/data/renewals.db"

# Wait for the database file to be created if it's being mounted
sleep 1

# Check if the database file does NOT exist
if [ ! -f "$DB_FILE" ]; then
    echo "Database not found. Initializing..."
    # Initialize the migrations folder (if it's not already there)
    flask db init
    # Create the migration script from the models
    flask db migrate -m "Initial migration"
    # Apply the migration to create all tables
    flask db upgrade
    # Create the default admin user
    flask init-db
    echo "Database initialized."
else
    echo "Database found. Applying any pending migrations..."
    # If the database already exists, just apply any new migrations
    flask db upgrade
    echo "Migrations applied."
fi

# Start the application using gunicorn
echo "Starting application..."
exec gunicorn --bind 0.0.0.0:5000 run:app