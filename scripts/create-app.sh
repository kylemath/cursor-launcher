#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="CursorLauncher"
APP_DIR="$PROJECT_DIR/$APP_NAME.app"
BUILD_COPY="$PROJECT_DIR/build/$APP_NAME.app"

rm -rf "$APP_DIR" "$BUILD_COPY"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDisplayName</key>
	<string>Cursor Launcher</string>
	<key>CFBundleExecutable</key>
	<string>launcher</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIdentifier</key>
	<string>com.kylemath.cursorlauncher</string>
	<key>CFBundleName</key>
	<string>Cursor Launcher</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>2.1</string>
	<key>CFBundleVersion</key>
	<string>2</string>
	<key>LSMinimumSystemVersion</key>
	<string>10.13</string>
	<key>LSUIElement</key>
	<false/>
	<key>NSHighResolutionCapable</key>
	<true/>
</dict>
</plist>
PLIST

cat > "$APP_DIR/Contents/MacOS/launcher" << 'LAUNCHER'
#!/bin/bash
# Thin wrapper: find the project, then run scripts/launch.sh

BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
POINTER="$HOME/.cursor-launcher-dir"

find_project() {
  local sibling
  sibling="$(cd "$BUNDLE_DIR/.." && pwd)"
  if [ -f "$sibling/scripts/launch.sh" ]; then
    echo "$sibling"
    return 0
  fi

  if [ -f "$POINTER" ]; then
    local stored
    stored=$(cat "$POINTER" 2>/dev/null)
    if [ -n "$stored" ] && [ -f "$stored/scripts/launch.sh" ]; then
      echo "$stored"
      return 0
    fi
  fi

  local candidate
  for candidate in \
    "$HOME/cursor-launcher" \
    "$HOME/Coding/TOOLS/cursor-launcher" \
    "$HOME/Coding/cursor-launcher"; do
    if [ -f "$candidate/scripts/launch.sh" ]; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

PROJECT_DIR="$(find_project)" || true

if [ -z "$PROJECT_DIR" ] || [ ! -f "$PROJECT_DIR/scripts/launch.sh" ]; then
  osascript -e 'display dialog "Could not find the cursor-launcher project.

Put the repo at ~/cursor-launcher, or keep CursorLauncher.app inside the project folder and launch it once from there." with title "Cursor Launcher" buttons {"OK"} default button "OK" with icon stop'
  exit 1
fi

printf '%s\n' "$PROJECT_DIR" > "$POINTER"
exec "$PROJECT_DIR/scripts/launch.sh"
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/launcher"

if [ -f "$PROJECT_DIR/build/AppIcon.icns" ]; then
  cp "$PROJECT_DIR/build/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
elif [ -f "$PROJECT_DIR/CursorLauncher.app/Contents/Resources/AppIcon.icns" ]; then
  true
fi

xattr -cr "$APP_DIR" 2>/dev/null || true

mkdir -p "$PROJECT_DIR/build"
cp -R "$APP_DIR" "$BUILD_COPY"
xattr -cr "$BUILD_COPY" 2>/dev/null || true

echo "Created: $APP_DIR"
if [ "$1" = "--install" ]; then
  rm -rf "/Applications/$APP_NAME.app"
  cp -R "$APP_DIR" "/Applications/$APP_NAME.app"
  xattr -cr "/Applications/$APP_NAME.app" 2>/dev/null || true
  echo "Installed to /Applications/$APP_NAME.app"
fi
