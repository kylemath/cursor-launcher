#!/bin/bash
# Quick launcher script for Cursor Project Dashboard

cd "$(dirname "$0")"

# Check for --server or -s flag
if [[ "$1" == "--server" || "$1" == "-s" ]]; then
    echo "🚀 Starting dashboard with server (enables new window support)..."
    python3 server.py
else
    echo "🔄 Regenerating dashboard..."
    python3 generate_dashboard.py

    echo ""
    echo "🚀 Opening dashboard..."
    open dashboard.html

    echo ""
    echo "✅ Done! Dashboard is open in your browser."
    echo ""
    echo "💡 Tip: Run 'projects -s' or './launch.sh --server' to enable ⌘+Click for new windows"
fi
