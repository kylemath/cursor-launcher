# Cursor Project Launcher

A local dashboard for all your coding projects. It scans your `~/Coding` folders
(and home), shows every project as a card, and lets you **open it in Cursor and
launch its dev server in one click** — plus see git status and manage ports, all
in your browser.

Runs locally on **http://localhost:8847**. Start it with the **Cursor Launcher**
dock app, or run `python3 server.py` in this folder.

---

## What it's for (the use cases)

| You want to… | Do this |
|---|---|
| Quickly reopen a project you were working on | Open the dashboard → **click a card** (opens in your current Cursor window) |
| Open a project in a separate window | **⌘/Ctrl/Shift+click** a card |
| Run a project's web app to look at it | Click **▶ Run** on the card → server starts, opens in Chrome |
| Open the code *and* the running app together | Click **🚀 Both** |
| See what you were last working on / what changed | **Feed** view (newest first, with latest commit + recent changes) |
| Compare projects across many dimensions | **Table** view (sort by branch, dirty files, last commit, port, etc.) |
| Find a specific project | Type in the **search box**, or use the **category filter chips** |
| Know which projects have uncommitted work | Look for the orange **●N** pill (or sort the Dirty column) |
| Know if a repo is public or private on GitHub | The **🌐 public / 🔒 private** pill on each card |
| Stop a dev server you left running | **Live Servers bar** at the top, or the **🔌 Ports** panel → Stop |
| Avoid two projects fighting over the same port | **🔌 Ports** shows conflicts; use **Manage → 🎲 Suggest** for a free port |
| Document a project for your homepage | **Manage → ✨ Auto-generate catalogue + screenshot** |
| Understand the icons/colors | Click **? Legend** |

---

## The three views

- **▦ Grid** — every project as a card in one wrapping list. Filter by category
  (Tools, Research, Home…), sort by recent activity / last commit / name.
- **☰ Feed** — a social-style feed, newest activity first: big cards with the
  description, latest commit message + date, recent changes, and branches.
- **▤ Table** — a sortable spreadsheet: Project, Category, Branch, Sync
  (ahead/behind), Dirty (uncommitted count), Remote (public/private), Last
  commit, Modified, Status, Port, **Cat** (has catalogue.json?), **Shot**
  (has screenshot.png?), Actions.

Deep links: `#grid`, `#feed`, `#table`.

## Git status on every card

For git repos: current **branch**, **↑/↓** ahead/behind the remote, **●N**
uncommitted files (or **✓** clean), **public/private** on GitHub, and the **last
commit date**. For non-repos it shows a **file count** instead.

## Ports

Every project's server **port** is shown as a pill. The dashboard detects
**conflicts** (two projects on the same port) and shows live **running** state.
The **🔌 Ports** overview lists every port, who uses it, whether it's listening
now, and a Stop button. **🎲 Suggest** (in Manage) picks the next free,
non-conflicting port.

## Manage a project (⚙ on any card)

- **Open**: in Cursor, the README, any `.md` file, or the running webpage.
- **✨ Auto-generate catalogue + screenshot**: creates `catalogue.json` (from
  folder name, README, git remote, and detected server) and captures a small
  `screenshot.png`.
- **Catalogue editor**: edit title, one-liner, description, demo URL, categories,
  tags, kind, status, and the server block. **✨ Auto-fill** suggests values.
  Saving **merges** so homepage-only fields (demoUrl, screenshot) are preserved.
- **📸 Capture screenshot**: starts the server, screenshots it, resizes small,
  saves `screenshot.png` into the project.

## catalogue.json

Each project can have a `catalogue.json`. It powers the dashboard **and** the
nightly homepage build. The launcher adds an optional `server` block:

```json
{
  "id": "MyApp",
  "title": "My App",
  "oneLiner": "Short description",
  "categories": ["web"],
  "tags": ["demo"],
  "status": "published",
  "server": { "type": "node", "port": 5173, "openPath": "/", "autoStart": true }
}
```

`server.type`: `static` (live-server or Python http.server), `node`
(`npm run dev`, Vite/Next aware), `liveserver`, `python`, or `custom` (with
`command`). If there's no `server` block, the type is auto-detected.

## The Cursor extension (in-editor companion)

There's a separate Cursor/VS Code extension (`../cursor-server-launcher-ext`)
that adds a **▶ Run :PORT** button to the status bar inside any open project. It
reads the same `catalogue.json` and opens the preview in Chrome. Hotkeys:
`Cmd+Alt+R` run, `Cmd+Alt+Shift+R` stop.

## Files

- `server.py` — local web server (port 8847) + all actions (open in Cursor,
  launch/stop servers, screenshots, save/auto-generate catalogue, ports).
- `generate_dashboard.py` — scans projects and builds `dashboard.html`
  (git-ignored: it embeds private repo names and local paths). Run with
  `--public` to build a sanitized, shareable `dashboard_public.html` that
  contains only repos that are public on GitHub, with no local paths.
- `server_launcher.py` — resolves and runs each project's dev server.
- `CursorLauncher.app` — double-click dock launcher.
- Runtime (git-ignored): `running.json`, `ports.json`, `.visibility_cache.json`, `logs/`.

## Running

```bash
python3 server.py          # starts on http://localhost:8847 and opens the browser
```

Or double-click **CursorLauncher.app**. To stop: the **⏹ Stop server** button in
the header, or `lsof -ti :8847 | xargs kill`.
