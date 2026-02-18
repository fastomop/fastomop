#!/bin/bash
set -e

echo "Starting nginx reverse proxy on port 7777..."
nginx

echo "Starting FastOMOP backend on port 3000..."
cd /app
runuser -u fastomop -- /app/.venv/bin/python -m agno_fastomop.web_interface &

sleep 8

echo "Starting Agent UI on port 3001..."
cd /ui
runuser -u fastomop -- sh -c "PORT=3001 pnpm start" &

wait
