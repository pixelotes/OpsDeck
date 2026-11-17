#!/bin/sh

# Ensure the data directory exists (required for attachments)
mkdir -p /app/data/attachments

# Apply database migrations (migrations are committed in the repo/image)
# For fresh databases: creates all tables from the migration chain
# For existing databases: applies only pending migrations
#
# Handles three edge cases:
# 1. alembic_version references a revision that no longer exists (e.g. after squash)
# 2. Database has tables but no alembic_version tracking (pre-migration DB)
# 3. alembic_version table exists but is empty
python3 -c "
from src import create_app
from src.extensions import db
app = create_app()
with app.app_context():
    try:
        result = db.session.execute(db.text('SELECT version_num FROM alembic_version')).fetchone()
        if result:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            cfg = Config('migrations/alembic.ini')
            cfg.set_main_option('script_location', 'migrations')
            scripts = ScriptDirectory.from_config(cfg)
            try:
                scripts.get_revision(result[0])
            except:
                print(f'  Stale revision {result[0]} — clearing alembic_version')
                db.session.execute(db.text('DELETE FROM alembic_version'))
                db.session.commit()
                import sys
                sys.exit(99)
        else:
            # alembic_version exists but is empty — check if DB has tables
            tables = db.session.execute(db.text(
                \"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name != 'alembic_version'\"
            )).scalar()
            if tables and tables > 0:
                print(f'  Pre-existing DB detected ({tables} tables, empty alembic_version) — will stamp')
                import subprocess, sys
                sys.exit(99)
    except Exception as e:
        err = str(e)
        if 'alembic_version' in err or 'does not exist' in err or 'UndefinedTable' in err:
            # No alembic_version table — check if other tables exist
            try:
                tables = db.session.rollback() or db.session.execute(db.text(
                    \"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'\"
                )).scalar()
                if tables and tables > 0:
                    print(f'  Pre-existing DB detected ({tables} tables, no alembic_version) — will stamp')
                    import sys
                    sys.exit(99)
            except:
                pass
        pass
"
PRECHECK_EXIT=$?

echo "Applying database migrations..."
if [ "$PRECHECK_EXIT" = "99" ]; then
    echo "Pre-existing database detected without migration tracking. Stamping current state..."
    flask db stamp head
    echo "Running any pending migrations..."
    if ! flask db upgrade; then
        echo "ERROR: Migration failed after stamp."
        exit 1
    fi
else
    if ! flask db upgrade; then
        echo "ERROR: Migration failed. Not stamping — fix the migration and redeploy."
        exit 1
    fi
fi

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
        # API connectors are core now and seeded by seed-db-prod
        flask seed-ai-profiles
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
