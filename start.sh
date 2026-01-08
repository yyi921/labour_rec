#!/bin/bash

# Run migrations
python manage.py migrate --noinput

# Create/update admin user (only if env vars are set)
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
    python manage.py create_admin --username "$ADMIN_USERNAME" --password "$ADMIN_PASSWORD"
fi

# Collect static files
python manage.py collectstatic --noinput

# Start gunicorn
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
