# Quick start

macOS, Python 3, and [Cursor](https://cursor.com) with its shell command installed (`Cursor` → **Install 'cursor' command in PATH**). The GitHub CLI (`gh`) is optional until you want private repos and clone-from-dashboard.

## 1. Put it here

```bash
mkdir -p ~/Coding/TOOLS
git clone git@github.com:kylemath/cursor-launcher.git ~/Coding/TOOLS/cursor-launcher
cd ~/Coding/TOOLS/cursor-launcher
```

The scanner expects this tree (create empty category folders if they do not exist yet):

```
~/Coding/RESEARCH/
~/Coding/TEACHING/
~/Coding/TOOLS/          ← this repo lives here
~/Coding/PUZZLES/
~/Coding/HARDWARE/
```

First-level folders under those names become cards. Other first-level folders in `~/Coding` show as **OTHER**. Top-level folders in `~` show as **HOME**.

## 2. Start the dashboard

```bash
python3 server.py
```

That regenerates `dashboard.html` and opens [http://localhost:8847](http://localhost:8847).

Alternatively, double-click **CursorLauncher.app** (Dock-friendly). To stop: **⏹ Stop server** in the header, or `lsof -ti :8847 | xargs kill`.

Opening `dashboard.html` as a `file://` page is read-only. Clone, run, ports, and pin need the server.

## 3. Connect GitHub (other machine or first time)

```bash
gh auth login
```

Then in the dashboard click **↻ GitHub**. That lists every repo on `kylemath` (public and private) without cloning them.

## What you will see

| Kind | How it appears |
|---|---|
| Folder on **this** machine that already has a GitHub `origin` | Full-color card in RESEARCH / TOOLS / HOME / … — not a second GitHub card |
| Folder on this machine with **no** remote, or not a git repo | Same local card, marked **⊘ local** or a file count |
| Repo on GitHub **not** cloned here | Dashed **☁ GitHub** card — **⬇ Clone** into `~/<name>` |

Nothing in this repo copies other machines' local-only folders or local-only git repos. Pins, recents, and `dashboard.html` are gitignored and stay on each machine. After you clone a GitHub card (or copy a folder yourself), regenerate or restart so it shows as local.

Publishing a local-only folder to GitHub is still manual (`git init` + `gh repo create --source=. --push`). There is no dashboard button for that yet.

## Optional

**Shell alias** (add to `~/.zshrc`):

```bash
alias projects='cd ~/Coding/TOOLS/cursor-launcher && python3 server.py'
```

**Cursor CLI** must be at `/usr/local/bin/cursor` for Dock-app launches. If `cursor` works in a terminal but not from the app, install the command from Cursor's palette and confirm that path.

## Troubleshooting

| Problem | Check |
|---|---|
| Empty or missing categories | Folders exist under `~/Coding/RESEARCH` (etc.). Every first-level subfolder is a project; `catalogue.json` is not required. |
| No GitHub cards / no private repos | `gh auth status`, then **↻ GitHub**. |
| Click does not open Cursor | `cursor --version` in a terminal; install the shell command from Cursor. |
| Clone / Run / Ports do nothing | Use `http://localhost:8847`, not a `file://` dashboard. |
| Port already in use | `lsof -ti :8847 \| xargs kill`, then start again. |

Full feature list: [README.md](README.md).
