# Cursor Project Launcher

A local dashboard for coding projects. It scans `~/Coding` and `~`, shows each
folder as a card, and lets you **open it in Cursor and launch its dev server in
one click** — plus git status, ports, and GitHub repos that are not cloned yet.

Runs on **http://localhost:8847**. First run or a second machine: **[QUICKSTART.md](QUICKSTART.md)**.

```bash
python3 server.py          # regenerates the dashboard and opens the browser
```

Or double-click **CursorLauncher.app**. Stop with **⏹ Stop server** in the header,
or `lsof -ti :8847 | xargs kill`.

---

## What it's for

| You want to… | Do this |
|---|---|
| Reopen a project | Click a card (current Cursor window) |
| Open in a separate window | **⌘ / Ctrl / Shift+click** a card |
| Run a project's web app | **▶ Run** — starts the server, opens Chrome |
| Code and the running app together | **🚀 Both** |
| See what changed recently | **Feed** view |
| Compare many projects | **Table** view (branch, dirty, remote, port, …) |
| Find something | Search box or category chips |
| See uncommitted work | Orange **●N** pill, or sort **Dirty** |
| Public vs private on GitHub | **🌐 public / 🔒 private** on the card |
| Grab a repo that is not on this machine | Dashed **☁ GitHub** card → **⬇ Clone** (lands in `~/<name>`) |
| Stop a leftover dev server | Live Servers bar, or **🔌 Ports** → Stop |
| Avoid port fights | **🔌 Ports**; **Manage → 🎲 Suggest** for a free port |
| Document a project for the homepage | **Manage → ✨ Auto-generate catalogue + screenshot** |
| Decode the icons | **? Legend** |

## The three views

- **▦ Grid** — cards in one list. Filter by category (Tools, Research, Home,
  GitHub…); sort by recent activity, last commit, or name.
- **☰ Feed** — newest activity first: description, latest commit, recent
  changes, branches.
- **▤ Table** — sortable spreadsheet: Project, Category, Branch, Sync, Dirty,
  Remote, Last commit, Modified, Status, Port, **Cat**, **Shot**, Actions.

Deep links: `#grid`, `#feed`, `#table`.

## How projects are organized

Discovery is **this machine's folders first**, then GitHub fills gaps.

| On disk | Category |
|---|---|
| `~/Coding/RESEARCH`, `TEACHING`, `TOOLS`, `PUZZLES`, `HARDWARE` | that name |
| Other first-level folders under `~/Coding` | **OTHER** |
| Top-level folders in `~` (minus system/cloud dirs) | **HOME** |

Every first-level folder is a card. `catalogue.json` and `screenshot.png` are
optional; without them you still get a title from the folder name.

A local folder whose `origin` is already on GitHub stays a **local** card in
that folder category. It is not shown again under GitHub. Local-only folders
(no remote, or not a git repo) stay local, marked **⊘ local** or a file count.

Repos on GitHub that are **not** cloned here appear as dashed **☁ GitHub**
cards (after `gh auth login` and **↻ GitHub**). **💻 Local** is every folder
on this disk, including ones that already have a remote. **☁ GitHub** is only
the uncloned ones.

This repo does **not** sync local-only folders or local-only git repos between
machines. Pins, recents, and the generated dashboard are gitignored. Publishing
a local folder to GitHub is still `git init` + `gh repo create` in a terminal.

## Git status on every card

For git repos: current **branch**, **↑/↓** vs origin, **●N** uncommitted (or
**✓** clean), **public / private / ⊘ local**, and last commit date. For
non-repos: a **file count**. Uncloned GitHub cards show **☁ GitHub**,
visibility, language, and last push.

## Ports

Each project's server port is a pill. The dashboard detects **conflicts** and
live **running** state. **🔌 Ports** lists every port, who uses it, and Stop.
**🎲 Suggest** (Manage) picks the next free, non-conflicting port.

## Manage a project (⚙ on any local card)

- **Open**: Cursor, the README, any `.md`, or the running page.
- **✨ Auto-generate catalogue + screenshot**: builds `catalogue.json` from
  folder name, README, git remote, and detected server; captures a small
  `screenshot.png`.
- **Catalogue editor**: title, one-liner, description, demo URL, categories,
  tags, kind, status, server block. **✨ Auto-fill** suggests values. Save
  **merges** so homepage-only fields (`demoUrl`, `screenshot`) are kept.
- **📸 Capture screenshot**: starts the server, screenshots it, saves
  `screenshot.png` in the project.

## catalogue.json

Optional. Powers this dashboard **and** the nightly homepage build. The
launcher adds an optional `server` block:

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

`server.type`: `static` (live-server or Python `http.server`), `node`
(`npm run dev`, Vite/Next aware), `liveserver`, `python`, or `custom` (with
`command`). No `server` block → type is auto-detected.

## Files

- `server.py` — local server (port 8847) and actions (open, run, screenshot,
  catalogue, ports, clone).
- `generate_dashboard.py` — scans folders and writes `dashboard.html`
  (git-ignored: private names, local paths, embedded shots). `--public` writes
  a sanitized `dashboard_public.html` (public GitHub repos only, no local paths).
- `github_repos.py` — `gh repo list` cache (`github_cache.json`, git-ignored).
- `server_launcher.py` — resolves and runs each project's dev server.
- `extension/` — Cursor / VS Code companion: status-bar **▶ Run :PORT**.
- `CursorLauncher.app` — Dock launcher (regenerate + server + browser).
- Runtime (git-ignored): `running.json`, `ports.json`, `pinned.json`,
  `recent.json`, `.visibility_cache.json`, `gh_assets/`, `logs/`.

## In-editor Run button

`extension/` is a Cursor / VS Code extension that adds **▶ Run :PORT** to the
status bar (`Cmd+Alt+R` / `Cmd+Alt+Shift+R` to stop). It reads the same
`catalogue.json` `server` block as the dashboard (or auto-detects). Details
and settings: [extension/README.md](extension/README.md).

```bash
cd extension
npx @vscode/vsce package
cursor --install-extension cursor-server-launcher-0.2.0.vsix
```

For development, symlink `extension/` into `~/.cursor/extensions/` instead of
repackaging.
