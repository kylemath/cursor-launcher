# Cross-Machine Sync Plan for Cursor Launcher

> Future evolution of cursor-launcher into a synchronized, multi-machine development environment manager.

## Vision

Transform cursor-launcher from a local project dashboard into a cross-machine synchronized launcher that:

1. Shows the same layout across all machines
2. Displays the latest repos from any machine
3. Shows all GitHub repos as "potential" repos (greyed out like unpurchased instruments in GarageBand)
4. Maintains a unified recent order from all machines
5. Auto-updates itself when loaded

---

## Current Architecture

- **Static dashboard generator** scanning `/Users/kylemathewson/Coding/`
- **Local state** in `pinned.json` and `recent.json`
- **Cursor integration** reading recent workspaces from Cursor's storage
- **Optional server mode** for interactivity
- **GitHub Actions** for auto-updating dashboard HTML

---

## Proposed Architecture

### 1. Sync Backend: Use GitHub as the Sync Layer

Use cursor-launcher's own repo as the sync backend since GitHub is already:
- The source of truth for code
- Authenticated on each machine
- No new infrastructure needed

**Directory Structure:**
```
cursor-launcher/
├── sync/
│   ├── machines/
│   │   ├── macbook-pro.json      # State from machine A
│   │   ├── work-desktop.json     # State from machine B
│   │   └── linux-server.json     # State from machine C
│   └── unified-state.json        # Aggregated view (generated)
```

**Sync Flow:**
1. Each machine pushes its local state to its own file
2. Each machine pulls all machine states
3. Unified view is generated locally from all machine states

### 2. Mapping Local Repos to GitHub Origins

Parse `.git/config` to extract origin URLs and normalize them:

```python
def discover_repo_with_origin(path):
    """Returns local path + GitHub origin info if available"""
    git_config = path / ".git" / "config"
    if git_config.exists():
        # Parse remote origin URL
        # Normalize: git@github.com:user/repo.git → user/repo
        # Normalize: https://github.com/user/repo.git → user/repo
    return {
        "local_path": str(path),
        "local_name": path.name,
        "github_repo": "kylemathewson/repo-name",  # or None
        "origin_url": "git@github.com:...",
    }
```

This allows matching repos across machines even if local folder names differ.

### 3. GitHub Repos as "Potential" (GarageBand-style)

Fetch all repos from GitHub and merge with local discovery:

```python
def fetch_github_repos():
    """Returns all repos from your GitHub account"""
    # Uses gh CLI: gh repo list --json name,url,isPrivate,updatedAt --limit 1000
    
def build_unified_catalog():
    local_repos = discover_local_repos()  # {github_id: local_info}
    github_repos = fetch_github_repos()   # All repos from GitHub
    
    for repo in github_repos:
        if repo.id in local_repos:
            repo.status = "cloned"      # Full color, clickable to open
        else:
            repo.status = "available"   # Greyed out, "Clone" button
```

**UI Treatment:**
- **Cloned locally**: Full color card, click to open in Cursor
- **Available on GitHub**: Greyed/faded card, "Clone" button to download

### 4. Unified Recent Order Across Machines

Each machine tracks activity with UTC timestamps:

```json
// sync/machines/macbook-pro.json
{
  "machine_id": "macbook-pro",
  "machine_name": "Kyle's MacBook Pro",
  "last_sync": "2026-02-02T15:30:00Z",
  "repos": {
    "kylemathewson/cursor-launcher": {
      "local_path": "/Users/kylemathewson/Coding/TOOLS/cursor-launcher",
      "last_opened": "2026-02-02T15:25:00Z",
      "last_pushed": "2026-02-02T14:00:00Z"
    },
    "kylemathewson/other-project": {
      "local_path": "/Users/kylemathewson/Coding/RESEARCH/other-project",
      "last_opened": "2026-02-01T10:00:00Z",
      "last_pushed": null
    }
  }
}
```

The unified view merges by taking the **most recent timestamp across all machines** for each repo.

### 5. Auto-Update Cursor-Launcher on Load

Add self-update logic to launch scripts:

```bash
# In launch.sh or start-server.sh
cd "$(dirname "$0")"
git fetch origin main --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "Updating cursor-launcher..."
    git pull --ff-only origin main
fi
python generate_dashboard.py
```

---

## Known Issues & Solutions

| Issue | Solution |
|-------|----------|
| **Different local names vs origin** | Parse `.git/config` to get origin URL; use GitHub repo ID as canonical key |
| **Public vs private repos** | `gh repo list` returns `isPrivate` flag; show lock icon for private repos |
| **GitHub auth on different machines** | Check `gh auth status`; show "Configure GitHub" prompt if not authenticated |
| **Auto-pull cursor-launcher updates** | On startup: `git pull --ff-only` before generating dashboard |
| **Merge conflicts in sync files** | Each machine only writes its own file; unified view is generated, not committed |

---

## Sync Flow Diagram

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MacBook Pro   │     │  Work Desktop   │     │  Linux Server   │
│                 │     │                 │     │                 │
│ Local Discovery │     │ Local Discovery │     │ Local Discovery │
│       ↓         │     │       ↓         │     │       ↓         │
│ machine-A.json  │     │ machine-B.json  │     │ machine-C.json  │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ↓
                    ┌────────────────────────┐
                    │  cursor-launcher repo  │
                    │   (GitHub - sync/)     │
                    │                        │
                    │  + GitHub API repos    │
                    └────────────────────────┘
                                 ↓
              ┌──────────────────────────────────┐
              │       Unified Dashboard          │
              │                                  │
              │  [Cloned locally] [Available]    │
              │  ████████████████  ░░░░░░░░░░    │
              └──────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Foundation
- [ ] Add git remote/origin detection to existing discovery
- [ ] Add auto-update on launch (self-pull)
- [ ] Create machine ID system

### Phase 2: GitHub Integration
- [ ] Add `gh repo list` fetching
- [ ] Merge GitHub repos with local discovery
- [ ] UI for "available" (not cloned) repos with clone button

### Phase 3: Cross-Machine Sync
- [ ] Create sync directory structure
- [ ] Implement machine state push/pull
- [ ] Build unified state aggregation
- [ ] Add conflict-free sync logic

### Phase 4: Polish
- [ ] Handle auth edge cases gracefully
- [ ] Add "last seen on [machine]" indicators
- [ ] Clone repo functionality (pick target directory)
- [ ] Settings for sync frequency

---

## Open Questions

1. **Sync trigger**: On every dashboard load? On a schedule? Manual button?
2. **Clone location**: When cloning an "available" repo, which category folder? User prompt?
3. **Stale machine data**: How long before a machine's data is considered stale? Show indicator?
4. **Org repos**: Include repos from GitHub orgs, or just personal repos?
5. **Archived repos**: Show archived GitHub repos? Separate section?

---

*Plan created: February 2, 2026*
