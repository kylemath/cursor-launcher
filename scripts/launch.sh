#!/bin/bash
# Cursor Project Launcher — start the local server, then open a regular Chrome window.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT=8847
URL="http://localhost:$PORT/"
LOG_FILE="$PROJECT_DIR/.app-launcher.log"
APP_NAME="Cursor Launcher"
POINTER="$HOME/.cursor-launcher-dir"

exec > "$LOG_FILE" 2>&1

echo "=== $APP_NAME launch at $(date) ==="
echo "PROJECT_DIR: $PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/server.py" ]; then
  osascript -e "display dialog \"Could not find the cursor-launcher project.

Put the repo at ~/cursor-launcher, or keep CursorLauncher.app inside the project folder and launch it once from there.\" with title \"$APP_NAME\" buttons {\"OK\"} default button \"OK\" with icon stop"
  exit 1
fi

printf '%s\n' "$PROJECT_DIR" > "$POINTER"

# .app double-click PATH is /usr/bin:/bin:/usr/sbin:/sbin — Homebrew gh lives elsewhere
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$HOME/.local/bin:$PATH"

# ---------- Find a real Python 3 (not the Xcode stub) ----------
PY=""
for candidate in \
    "$HOME/.pyenv/shims/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "/usr/bin/python3"; do
    if [ -x "$candidate" ] && "$candidate" -c "import http.server" 2>/dev/null; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    osascript -e "display dialog \"$APP_NAME: could not find Python 3. Install it via Homebrew: brew install python\" with title \"$APP_NAME\" buttons {\"OK\"} default button \"OK\" with icon stop"
    exit 1
fi

echo "Using Python: $PY ($($PY --version 2>&1))"

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR" || exit 1

STALE=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$STALE" ]; then
    echo "Killing stale server (PID $STALE)"
    kill -9 $STALE 2>/dev/null
    sleep 0.5
fi

echo "Regenerating dashboard..."
"$PY" "$PROJECT_DIR/generate_dashboard.py" >> "$LOG_FILE" 2>&1

echo "Starting server on port $PORT..."
CL_NO_BROWSER=1 "$PY" "$PROJECT_DIR/server.py" >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"

for i in $(seq 1 30); do
    if curl -s "$URL" -o /dev/null 2>/dev/null; then
        echo "Server ready after ~$((i / 2))s"
        break
    fi
    sleep 0.5
done

if ! curl -s "$URL" -o /dev/null 2>/dev/null; then
  osascript -e "display dialog \"$APP_NAME failed to start. Check .app-launcher.log in the project folder.\" with title \"$APP_NAME\" buttons {\"OK\"} default button \"OK\" with icon stop" &
  exit 1
fi

# Regular Chrome window (same as before). Do not use --app / --args —
# those hide the tab bar or fail to open the URL if Chrome is already running.
if open -a "Google Chrome" "$URL" 2>/dev/null; then
    echo "Opened in Chrome: $URL"
elif open -a "Safari" "$URL" 2>/dev/null; then
    echo "Opened in Safari: $URL"
else
    open "$URL"
fi

wait "$SERVER_PID"
