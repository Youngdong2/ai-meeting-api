#!/bin/bash

cd "$(dirname "$0")/../ai_meeting_api"

uv run python manage.py show_urls
