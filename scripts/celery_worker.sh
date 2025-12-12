#!/bin/bash

cd "$(dirname "$0")/../ai_meeting_api"

uv run celery -A ai_meeting_api worker --loglevel=info
