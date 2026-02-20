#!/bin/sh

# Ensure the data directory exists (required for attachments)
mkdir -p /app/data/attachments

# Check if Enterprise mode is enabled and install plugin BEFORE migrations
if [ "$ENTERPRISE_ENABLED" = "True" ]; then
    echo "Enterprise mode enabled. Installing enterprise plugin..."
    if [ -d "/app/opsdeck-enterprise" ]; then
        # Install the enterprise plugin in editable mode
        pip install -e /app/opsdeck-enterprise
        if [ $? -eq 0 ]; then
             echo "✓ Enterprise plugin installed successfully"
        else
             echo "✗ Failed to install enterprise plugin"
             exit 1
        fi
    else
        echo "⚠ Enterprise mode enabled but opsdeck-enterprise folder not found"
    fi
fi

# Apply database migrations (migrations are committed in the repo/image)
# For fresh databases: creates all tables from the migration chain
# For existing databases: applies only pending migrations
flask db upgrade 2>&1 || {
    echo "Migration failed. Attempting to stamp current DB state and retry..."
    flask db stamp head
    flask db upgrade
}

# Create the default admin user
flask init-db

# Add initial frameworks and controls (Production Data)
flask seed-db-prod


# Add demo data (Users, Assets, Risks, etc.) - Only if SEED_DEMO_DATA is True
if [ "$SEED_DEMO_DATA" = "True" ]; then
    echo "Seeding demo data..."
    flask seed-db-demodata
else
    echo "Skipping demo data seeding (SEED_DEMO_DATA not set to True)"
fi


# Seed Enterprise plugin data - Only if ENTERPRISE_ENABLED is True
if [ "$ENTERPRISE_ENABLED" = "True" ]; then
    if [ -d "/app/opsdeck-enterprise" ]; then
        echo "Seeding enterprise data..."
        # We assume plugin was installed at the beginning of the script
        flask seed-connectors
        flask seed-ai-profiles
        if [ "$SEED_DEMO_DATA" = "True" ]; then
            flask seed-kpis
            flask seed-demo-reports
        fi
        echo "✓ Enterprise plugin configured and seeded"
    fi
else
    echo "Enterprise mode disabled (ENTERPRISE_ENABLED not set to True)"
fi


echo "Database initialized."


# Start the application using gunicorn
echo "Starting application..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile - \
    --error-logfile - \
    run:app
