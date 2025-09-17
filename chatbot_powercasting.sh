#!/bin/bash

APP_NAME="chatbot_powercasting"
APP_MODULE="app:app"   # change "app:app" → (filename:Flask app variable)
HOST="0.0.0.0"
PORT=5050
WORKERS=4

# Activate venv if needed
# source venv/bin/activate

# Run Flask with Gunicorn
exec gunicorn $APP_MODULE \
    --workers $WORKERS \
    --bind $HOST:$PORT \
    --timeout 120 \
    --log-level info