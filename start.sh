#!/bin/bash

# Run database migrations
python manage.py migrate --noinput

# Create/update admin user (only if env vars are set)
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    python manage.py create_admin --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
fi

# Populate location and department mappings
python manage.py populate_mappings

# Load cost center splits (only if not already loaded)
python manage.py load_costcenter_splits || echo "Cost center splits already loaded or error occurred"

# Collect static files
python manage.py collectstatic --noinput

# Start gunicorn with increased timeout and workers for handling large CSV uploads
gunicorn config.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --timeout 600 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --log-level info
