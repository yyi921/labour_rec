#!/bin/bash

# Run migrations
python manage.py migrate --noinput

# Create/update admin user (only if env vars are set)
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    python manage.py create_admin --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
fi

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
