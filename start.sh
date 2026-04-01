#!/bin/bash

echo "Running update..."
python3 update.py

echo "Starting Gunicorn..."
gunicorn app:app \
    --workers 1 \
    --threads 1 \
    --bind 0.0.0.0:$PORT \
    --timeout 86400 &

echo "Starting Telegram Bot..."

# Loop supaya bot auto restart kalau crash
while true
do
    python3 main.py
    echo "Bot crashed or disconnected! Restarting in 5 seconds..."
    sleep 5
done
