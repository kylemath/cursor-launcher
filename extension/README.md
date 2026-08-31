# Project Server Launcher (Cursor / VS Code extension)

In-editor companion to the dashboard in this repo. Adds a one-click **Run
server** button to the status bar that launches the current project's dev
server (HTML / Python / Node) and opens a preview. Shares the same
`catalogue.json` `server` block as `server_launcher.py`.

## What it does

- When you open a project folder, a `$(play) Run :PORT` button appears in the
  status bar (bottom-left) if the project has a launchable server.
- Click it (or press `Cmd+Alt+R`) to start the server in an integrated terminal
  and open a preview.
- The button turns into `$(debug-stop) Stop :PORT`; click it (or
  `Cmd+Alt+Shift+R`) to stop.

## How the server is determined

1. The optional `server` block in the project's `catalogue.json`:

   ```json
   {
     "server": {
       "type": "node",
       "command": "npm run dev",
       "port": 5173,
       "openPath": "/",
       "autoStart": true
     }
   }
   ```

   - `type`: `static` (live-server when installed, else `python3 -m http.server`),
     `node` (`npm run dev`/`start`, Vite/Next aware), `liveserver`
     (`npx live-server`), `python` (`manage.py`/`app.py`/`main.py`), or `custom`
     (uses `command`).
   - `command` overrides the type default; `port` drives the preview URL;
     `openPath` is appended to the URL.

2. If there is no `server` block, the type is auto-detected:
   - `package.json` with a `dev`/`start` script -> node
   - `index.html` -> static
   - `manage.py` / `app.py` / `main.py` -> python

The target port is freed before launch so a stale server doesn't block startup.

## Settings

- `projectLauncher.openPreview` (default `true`): open a preview after launching.
- `projectLauncher.previewTarget` (default `chrome`): where to open the preview —
  `chrome` (Google Chrome, falls back to default browser), `simpleBrowser`
  (Cursor's in-editor browser), or `default` (system default browser).

## Install (local)

From this directory:

```bash
npx @vscode/vsce package
cursor --install-extension cursor-server-launcher-0.2.0.vsix
```

For development you can instead symlink this folder into `~/.cursor/extensions/`.
