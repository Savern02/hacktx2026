#!/bin/bash

# Docker Desktop's WSL integration creates /.dockerenv on the host too,
# so prefer a local .venv when one exists.
if [ -f .venv/bin/activate ]; then
    echo "Running locally with .venv"
    source .venv/bin/activate
else
    echo "Running in Docker"
fi

fastapi dev app/main.py --host 0.0.0.0 --port 8000 --reload &
python watcher.py

wait
