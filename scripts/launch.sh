#!/bin/bash
# Cursor Project Launcher — starts the local server and opens the PWA
# (or Chrome so you can install it). Works from Terminal or the .app wrapper.

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

# Prefer an installed Chrome PWA (own Dock icon) over a regular Chrome tab
PWA_APP=""
for dir in "$HOME/Applications/Chrome Apps.localized" "$HOME/Applications/Chrome Apps" "$HOME/Applications"; do
  for name in "$APP_NAME" "Cursor Project Launcher" "CursorLauncher"; do
    if [ -d "$dir/$name.app" ]; then
      PWA_APP="$dir/$name.app"
      break 2
    fi
  done
done

if [ -n "$PWA_APP" ]; then
  echo "Launching installed PWA: $PWA_APP"
  open -a "$PWA_APP"
else
  echo "PWA not installed — opening in Chrome so it can be installed."
  if   [ -d "/Applications/Google Chrome.app" ]; then
    open -na "Google Chrome" --args "$URL"
  elif [ -d "/Applications/Chromium.app" ]; then
    open -na "Chromium" --args "$URL"
  elif [ -d "/Applications/Microsoft Edge.app" ]; then
    open -na "Microsoft Edge" --args "$URL"
  elif [ -d "/Applications/Brave Browser.app" ]; then
    open -na "Brave Browser" --args "$URL"
  elif [ -d "/Applications/Safari.app" ]; then
    open -a "Safari" "$URL"
  else
    open "$URL"
  fi

  FLAG="$PROJECT_DIR/.pwa-install-hinted"
  if [ ! -f "$FLAG" ]; then
    touch "$FLAG"
    sleep 3
    osascript -e "display dialog \"To get a standalone app with its own Dock icon:

1. Look for the install icon (⊕) on the right side of the Chrome address bar
2. Click it and choose Install

Next time you launch, it will open as its own app with the new Cursor + picker icon.\" with title \"$APP_NAME — Install as App\" buttons {\"OK\"} default button \"OK\"" &
  fi
fi

wait "$SERVER_PID"
