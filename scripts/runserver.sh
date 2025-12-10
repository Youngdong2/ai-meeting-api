#!/bin/bash

cd "$(dirname "$0")/../ai_meeting_api"

uv run python manage.py runserver 0.0.0.0:8022
