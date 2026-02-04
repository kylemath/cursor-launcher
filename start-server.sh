#!/bin/bash
# Start the Cursor Project Launcher server

cd "$(dirname "$0")"

echo "🔄 Regenerating dashboard..."
python3 generate_dashboard.py

echo ""
echo "🚀 Starting server..."
python3 server.py
