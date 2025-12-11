#!/bin/bash

cd "$(dirname "$0")/../ai_meeting_api"

echo "Making migrations..."
uv run python manage.py makemigrations

echo ""
echo "Applying migrations..."
uv run python manage.py migrate

echo ""
echo "Done!"
