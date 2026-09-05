#!/usr/bin/env python3
"""
Generate a local Cursor project launcher dashboard.
Scans the entire CODING folder and creates an HTML page
with clickable cards that open projects in Cursor.
"""

import json
import os
import re
import subprocess
import html
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set
import base64

import server_launcher
import github_repos

# Cache for remote public/private lookups (keyed by "owner/repo")
VISIBILITY_CACHE_FILE = Path(__file__).parent / ".visibility_cache.json"
_VIS_CACHE: Optional[Dict[str, str]] = None

# Configuration
CODING_ROOT = Path.home() / "Coding"
OUTPUT_FILE = Path(__file__).parent / "dashboard.html"
PUBLIC_OUTPUT_FILE = Path(__file__).parent / "dashboard_public.html"

# Public mode (--public): produce a shareable dashboard that contains only
# repos that are public on GitHub, no home-folder scan, and no absolute
# local paths. The default (private) mode is unchanged and stays local-only.
PUBLIC_MODE = False
PINNED_FILE = Path(__file__).parent / "pinned.json"
CURSOR_STORAGE = Path.home() / "Library/Application Support/Cursor/User/globalStorage/storage.json"
CATALOGUE_FILE = "catalogue.json"
SCREENSHOT_FILE = "screenshot.png"
GROUPS_FILE = Path(__file__).parent / "repo_groups.json"
GROUPS_LOCAL_FILE = Path(__file__).parent / "repo_groups.local.json"
REPOS_FILE = Path(__file__).parent / "repos.json"
REPOS_LOCAL_FILE = Path(__file__).parent / "repos.local.json"

# Main categories (subdirectories to scan recursively)
MAIN_CATEGORIES = ["RESEARCH", "TEACHING", "TOOLS", "PUZZLES", "HARDWARE"]

# Folders to ignore
IGNORE_FOLDERS = {'.git', 'node_modules', 'venv', '__pycache__', '.vscode', '.cursor', 
                  'build', 'dist', '.DS_Store', 'env', '.env'}

# How many recent projects to show
MAX_RECENT = 10

# Standard macOS / cloud home folders that are never projects.
# These are excluded entirely from scanning and from every view.
COMMON_OSX_FOLDERS = {
    'Applications', 'Desktop', 'Documents', 'Downloads', 'Library',
    'Movies', 'Music', 'Pictures', 'Public', 'Dropbox',
    'OneDrive', 'Google Drive', 'GoogleDrive', 'Creative Cloud Files',
    'Sites', 'iCloud Drive', 'Parallels', 'VirtualBox VMs',
}


def _read_json_file(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_json_prefer_local(public_path: Path) -> Optional[Dict]:
    """Prefer the gitignored *.local.json copy, then the committed public file."""
    local_path = public_path.with_name(f"{public_path.stem}.local.json")
    return _read_json_file(local_path) or _read_json_file(public_path)


def load_repos_catalog() -> Dict:
    """Full repo list for the sorter. Local file includes private names."""
    return load_json_prefer_local(REPOS_FILE) or {"repos": []}


def public_repo_names(catalog: Optional[Dict] = None) -> Set[str]:
    """Repo names that are safe to publish (visibility == public)."""
    data = catalog if catalog is not None else load_repos_catalog()
    names: Set[str] = set()
    for repo in data.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        vis = str(repo.get("visibility") or "").lower()
        name = repo.get("name")
        if name and vis == "public":
            names.add(name)
    return names


def sanitize_groups_for_public(group_data: Dict, allowed_names: Set[str]) -> Dict:
    """Drop private / unknown repo names from sorter groups."""
    allowed_lower = {n.lower() for n in allowed_names}
    columns = []
    by_repo: Dict[str, Dict] = {}
    for col in group_data.get("columns") or []:
        names = []
        seen = set()
        for name in col.get("names") or []:
            if not name or name.lower() in seen:
                continue
            if name not in allowed_names and name.lower() not in allowed_lower:
                continue
            seen.add(name.lower())
            names.append(name)
        if not names and str(col.get("id")) != "general":
            continue
        title = (col.get("title") or "Untitled").strip() or "Untitled"
        cid = str(col.get("id") or title)
        entry = {"id": cid, "title": title}
        cleaned = {"id": cid, "title": title, "names": names}
        columns.append(cleaned)
        for name in names:
            by_repo[name] = entry
            by_repo[name.lower()] = entry
    return {
        "columns": columns,
        "by_repo": by_repo,
        "colsPerRow": str(group_data.get("colsPerRow") or "auto"),
    }


def write_public_identity_files() -> Dict[str, int]:
    """Write anonymized repos.json + repo_groups.json for the public repo."""
    catalog = load_repos_catalog()
    public_names = public_repo_names(catalog)
    public_repos = []
    for repo in catalog.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        if str(repo.get("visibility") or "").lower() != "public":
            continue
        public_repos.append({
            "name": repo.get("name") or "",
            "description": repo.get("description") or "",
            "visibility": "public",
        })
    repos_out = {
        "count": len(public_repos),
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "owner": catalog.get("owner") or "",
        "public_count": len(public_repos),
        "repos": public_repos,
    }
    REPOS_FILE.write_text(json.dumps(repos_out, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")

    groups = load_json_prefer_local(GROUPS_FILE) or {"columns": []}
    public_groups = sanitize_groups_for_public(groups, public_names)
    groups_out = {
        "saved": datetime.now().isoformat(),
        "colsPerRow": public_groups.get("colsPerRow") or "auto",
        "public": True,
        "columns": public_groups.get("columns") or [],
    }
    GROUPS_FILE.write_text(json.dumps(groups_out, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    return {
        "public_repos": len(public_repos),
        "public_groups": len(groups_out["columns"]),
    }


def anonymize_project_for_public(project: Dict) -> None:
    """Strip local machine state so the public dashboard stays anonymous."""
    project["is_pinned"] = False
    project["cursor_recent_idx"] = None
    project["path"] = ""
    project["runnable"] = False
    project["server_url"] = None
    project["server_port"] = None
    project["port_designated"] = False
    project["port_conflict"] = False
    g = project.get("git") or {}
    g["uncommitted"] = 0
    g["file_count"] = 0
    g["remote_url"] = None
    for branch in g.get("branches") or []:
        branch["ahead"] = 0
        branch["behind"] = 0
    project["git"] = g


def load_repo_groups() -> Dict:
    """Load sorter groups. Prefers repo_groups.local.json (private names)."""
    data = load_json_prefer_local(GROUPS_FILE)
    if not data:
        return {"columns": [], "by_repo": {}, "colsPerRow": "auto"}
    columns = data.get("columns") or []
    by_repo: Dict[str, Dict] = {}
    for col in columns:
        title = (col.get("title") or "Untitled").strip() or "Untitled"
        cid = str(col.get("id") or title)
        entry = {"id": cid, "title": title}
        for name in col.get("names") or []:
            if not name:
                continue
            by_repo[name] = entry
            by_repo[name.lower()] = entry
    return {
        "columns": columns,
        "by_repo": by_repo,
        "colsPerRow": str(data.get("colsPerRow") or "auto"),
    }


def assign_sorter_group(project: Dict, by_repo: Dict) -> None:
    """Attach sorter_group / sorter_group_id by matching repo or folder name."""
    keys = []
    git = project.get("git") or {}
    for key in (
        git.get("repo_name"),
        project.get("id"),
        Path(project["path"]).name if project.get("path") else None,
        project.get("title"),
        (project.get("rel_path") or "").rsplit("/", 1)[-1],
    ):
        if key and key not in keys:
            keys.append(key)
    hit = None
    matched = None
    for key in keys:
        if key in by_repo:
            hit = by_repo[key]
            matched = key
            break
        low = by_repo.get(key.lower())
        if low:
            hit = low
            matched = key
            break
    project["sorter_group"] = hit["title"] if hit else ""
    project["sorter_group_id"] = hit["id"] if hit else ""
    project["sorter_repo"] = matched or (keys[0] if keys else "")


def _project_name_keys(project: Dict) -> List[str]:
    keys = []
    git = project.get("git") or {}
    for key in (
        git.get("repo_name"),
        project.get("id"),
        Path(project["path"]).name if project.get("path") else None,
        project.get("title"),
        (project.get("rel_path") or "").rsplit("/", 1)[-1],
    ):
        if key and key not in keys:
            keys.append(key)
    return keys


def order_projects_by_names(projects: List[Dict], names: List[str]) -> List[Dict]:
    index = {n.lower(): i for i, n in enumerate(names) if n}
    def sort_key(p):
        for key in _project_name_keys(p):
            if key.lower() in index:
                return (0, index[key.lower()])
        return (1, (p.get("title") or "").lower())
    return sorted(projects, key=sort_key)


def item_filter_attrs(project: Dict) -> str:
    """data-* attributes used by location + sorter-group filters."""
    cat = html.escape(str(project.get("category") or ""), quote=True)
    pinned = "true" if project.get("is_pinned") else "false"
    source = html.escape(str(project.get("source") or "local"), quote=True)
    gid = html.escape(str(project.get("sorter_group_id") or ""), quote=True)
    glabel = html.escape(str(project.get("sorter_group") or ""), quote=True)
    repo = html.escape(str(project.get("sorter_repo") or ""), quote=True)
    return (
        f'data-category="{cat}" data-pinned="{pinned}" '
        f'data-source="{source}" data-group="{gid}" data-group-label="{glabel}" '
        f'data-repo="{repo}"'
    )


def group_select_html(project: Dict, columns: List[Dict]) -> str:
    """Dropdown to reassign a project to a sorter group."""
    if PUBLIC_MODE:
        return html.escape(project.get("sorter_group") or "—")
    current = str(project.get("sorter_group_id") or "general")
    repo = html.escape(str(project.get("sorter_repo") or ""), quote=True)
    opts = []
    for col in columns:
        cid = str(col.get("id") or "")
        if not cid:
            continue
        title = (col.get("title") or "Untitled").strip() or "Untitled"
        sel = " selected" if cid == current else ""
        opts.append(
            f'<option value="{html.escape(cid, quote=True)}"{sel}>{html.escape(title)}</option>'
        )
    if not opts:
        return html.escape(project.get("sorter_group") or "—")
    return (
        f'<select class="group-pick" data-repo="{repo}" '
        f'onclick="event.stopPropagation()" onchange="changeProjectGroup(this, event)">'
        f'{"".join(opts)}</select>'
    )


def _js_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def scan_home_folders(pinned_paths: List[str], cursor_recent: List[str],
                      seen_paths: Set[str]) -> List[Dict]:
    """Scan ~ for top-level directories, returning them as project entries."""
    home = Path.home()
    folders = []
    try:
        for item in sorted(home.iterdir()):
            if not item.is_dir() or item.name.startswith('.'):
                continue
            # Never include standard macOS / cloud system folders in any view.
            if item.name in COMMON_OSX_FOLDERS:
                continue
            item_str = str(item)
            if item_str in seen_paths:
                continue
            seen_paths.add(item_str)
            project = create_project_entry(item, "HOME", pinned_paths, cursor_recent)
            if project:
                project['is_common_osx'] = False
                folders.append(project)
    except PermissionError:
        pass
    return folders


def load_pinned() -> List[str]:
    """Load list of pinned project paths."""
    if PINNED_FILE.exists():
        try:
            with open(PINNED_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return []


def load_cursor_recent() -> List[str]:
    """Load Cursor's recent workspaces from its storage."""
    recent_paths = []
    if CURSOR_STORAGE.exists():
        try:
            with open(CURSOR_STORAGE, 'r') as f:
                data = json.load(f)
            
            # Get from backupWorkspaces.folders
            backup = data.get('backupWorkspaces', {})
            folders = backup.get('folders', [])
            
            for folder in folders:
                uri = folder.get('folderUri', '')
                if uri.startswith('file://'):
                    path = uri[7:]  # Remove 'file://'
                    if path.startswith(str(CODING_ROOT)):
                        recent_paths.append(path)
        except Exception as e:
            print(f"⚠️  Could not read Cursor storage: {e}")
    
    return recent_paths


def get_folder_mtime(path: Path) -> float:
    """Get the most recent modification time of a folder (checks common files)."""
    mtime = path.stat().st_mtime
    
    # Check some common files that indicate recent activity
    for fname in ['.git/HEAD', '.git/index', 'package.json', 'Cargo.toml', 
                  'pyproject.toml', 'requirements.txt', 'main.py', 'index.js']:
        fpath = path / fname
        if fpath.exists():
            try:
                file_mtime = fpath.stat().st_mtime
                mtime = max(mtime, file_mtime)
            except:
                pass
    
    return mtime


def _git(project_dir: Path, args: List[str], timeout: int = 5) -> Optional[str]:
    """Run a git command in project_dir, returning stdout or None on failure."""
    try:
        out = subprocess.run(
            ['git', '-C', str(project_dir), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return None


def _load_vis_cache() -> Dict[str, str]:
    global _VIS_CACHE
    if _VIS_CACHE is None:
        _VIS_CACHE = {}
        if VISIBILITY_CACHE_FILE.exists():
            try:
                _VIS_CACHE = json.loads(VISIBILITY_CACHE_FILE.read_text())
            except Exception:
                _VIS_CACHE = {}
    return _VIS_CACHE


def _save_vis_cache():
    try:
        VISIBILITY_CACHE_FILE.write_text(json.dumps(_VIS_CACHE or {}, indent=2))
    except Exception:
        pass


def _parse_github_remote(url: str):
    """Return (owner, repo) for a GitHub remote URL, else (None, None)."""
    if not url:
        return None, None
    m = re.search(r'github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$', url.strip())
    if m:
        return m.group(1), m.group(2)
    return None, None


def get_remote_visibility(owner: str, repo: str) -> str:
    """'public' | 'private' | 'unknown' for a GitHub repo (cached)."""
    cache = _load_vis_cache()
    key = f'{owner}/{repo}'
    if key in cache:
        return cache[key]
    result = 'unknown'
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{owner}/{repo}')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('User-Agent', 'cursor-launcher')
        token = os.getenv('GITHUB_TOKEN')
        if token:
            req.add_header('Authorization', f'token {token}')
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.load(resp)
            result = 'private' if data.get('private') else 'public'
    except urllib.error.HTTPError as e:
        result = 'private' if e.code == 404 else 'unknown'
    except Exception:
        result = 'unknown'
    cache[key] = result
    _save_vis_cache()
    return result


def get_git_info(project_dir: Path) -> Dict:
    """Collect rich git status for a folder (or a file count if not a repo)."""
    info = {
        'is_repo': False,
        'last_commit_iso': None,
        'last_commit_rel': None,
        'last_commit_subject': None,
        'last_commit_ts': 0,
        'recent_subjects': [],
        'has_remote': False,
        'remote_url': None,
        'owner': None,
        'repo_name': None,
        'visibility': None,           # 'public' | 'private' | 'unknown'
        'current_branch': None,
        'branches': [],               # [{name, upstream, ahead, behind, gone, current}]
        'uncommitted': 0,
        'file_count': 0,
    }

    if not (project_dir / '.git').exists():
        # Not a repo: report a top-level item count instead.
        try:
            info['file_count'] = len([e for e in os.listdir(project_dir) if e != '.DS_Store'])
        except Exception:
            info['file_count'] = 0
        return info

    info['is_repo'] = True

    # Last commit + recent subjects
    log1 = _git(project_dir, ['log', '-1', '--format=%cI%x1f%cr%x1f%s'])
    if log1 and log1.strip():
        parts = log1.strip().split('\x1f')
        if len(parts) >= 3:
            info['last_commit_iso'] = parts[0]
            info['last_commit_rel'] = parts[1]
            info['last_commit_subject'] = parts[2]
            try:
                info['last_commit_ts'] = datetime.fromisoformat(parts[0]).timestamp()
            except Exception:
                info['last_commit_ts'] = 0
    log5 = _git(project_dir, ['log', '-5', '--format=%s'])
    if log5:
        info['recent_subjects'] = [s for s in log5.strip().split('\n') if s][:5]

    # Remote origin + visibility
    remote = _git(project_dir, ['remote', 'get-url', 'origin'])
    if remote and remote.strip():
        info['has_remote'] = True
        info['remote_url'] = remote.strip()
        owner, repo = _parse_github_remote(remote.strip())
        if owner and repo:
            info['owner'] = owner
            info['repo_name'] = repo
            info['visibility'] = get_remote_visibility(owner, repo)

    # Local branches + tracking status vs upstream
    fmt = '%(HEAD)\t%(refname:short)\t%(upstream:short)\t%(upstream:track)'
    branches_out = _git(project_dir, ['for-each-ref', '--format=' + fmt, 'refs/heads'])
    if branches_out:
        for line in branches_out.splitlines():
            cols = (line.split('\t') + ['', '', '', ''])[:4]
            head, name, upstream, track = cols
            if not name:
                continue
            ahead = int(re.search(r'ahead (\d+)', track).group(1)) if 'ahead' in track else 0
            behind = int(re.search(r'behind (\d+)', track).group(1)) if 'behind' in track else 0
            current = head.strip() == '*'
            branch = {
                'name': name,
                'upstream': upstream or None,
                'ahead': ahead,
                'behind': behind,
                'gone': 'gone' in track,
                'current': current,
            }
            info['branches'].append(branch)
            if current:
                info['current_branch'] = name

    # Uncommitted changes
    status = _git(project_dir, ['status', '--porcelain'])
    if status is not None:
        info['uncommitted'] = len([l for l in status.splitlines() if l.strip()])

    return info


def find_all_projects() -> List[Dict]:
    """Scan CODING folder for all projects."""
    projects = []
    pinned_paths = load_pinned()
    cursor_recent = load_cursor_recent()
    seen_paths: Set[str] = set()
    
    # Scan main categories - only first level subfolders are projects
    for category in MAIN_CATEGORIES:
        cat_path = CODING_ROOT / category
        if not cat_path.exists():
            continue
        
        try:
            for project_folder in sorted(cat_path.iterdir()):
                if not project_folder.is_dir():
                    continue
                if project_folder.name in IGNORE_FOLDERS:
                    continue
                
                folder_str = str(project_folder)
                if folder_str in seen_paths:
                    continue
                
                # Every first-level subfolder is a project - don't scan deeper
                seen_paths.add(folder_str)
                project = create_project_entry(project_folder, category, pinned_paths, cursor_recent)
                if project:
                    projects.append(project)
        except PermissionError:
            pass
    
    # Scan root CODING folder for "OTHER" projects (first level only).
    # Skip entirely if ~/Coding was deleted or never created.
    if CODING_ROOT.is_dir():
        try:
            for item in CODING_ROOT.iterdir():
                if not item.is_dir():
                    continue
                if item.name in MAIN_CATEGORIES or item.name in IGNORE_FOLDERS:
                    continue

                item_str = str(item)
                if item_str in seen_paths:
                    continue

                # Every first-level folder outside main categories is "OTHER"
                seen_paths.add(item_str)
                project = create_project_entry(item, "OTHER", pinned_paths, cursor_recent)
                if project:
                    projects.append(project)
        except PermissionError:
            pass
    
    # Scan home directory for top-level folders (skips already-seen paths like ~/Coding).
    # Never in public mode: the home listing is private machine layout.
    if not PUBLIC_MODE:
        home_projects = scan_home_folders(pinned_paths, cursor_recent, seen_paths)
        projects.extend(home_projects)
    
    return projects


def create_project_entry(project_dir: Path, category: str, 
                        pinned_paths: List[str], cursor_recent: List[str]) -> Optional[Dict]:
    """Create a project entry dict from a folder."""
    try:
        path_str = str(project_dir)
        
        # Try to load catalogue.json
        catalogue_path = project_dir / CATALOGUE_FILE
        metadata = {}
        if catalogue_path.exists():
            try:
                with open(catalogue_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except:
                pass
        
        # Get screenshot path
        screenshot_path = project_dir / SCREENSHOT_FILE
        screenshot_exists = screenshot_path.exists()
        
        # Get relative path for display
        try:
            rel_path = project_dir.relative_to(CODING_ROOT)
        except ValueError:
            try:
                rel_path = "~" / project_dir.relative_to(Path.home())
            except ValueError:
                rel_path = project_dir
        
        # Get modification time
        mtime = get_folder_mtime(project_dir)
        
        # Check if in Cursor's recent
        cursor_recent_idx = None
        for idx, rpath in enumerate(cursor_recent):
            if rpath == path_str:
                cursor_recent_idx = idx
                break

        # Determine whether this project has a launchable dev server
        # (explicit catalogue `server` block, or auto-detected).
        server_info = server_launcher.resolve_server(path_str)
        runnable = bool(server_info.get('available'))

        # Latest git activity (for Feed/Table views)
        git_info = get_git_info(project_dir)

        project = {
            'id': metadata.get('id', project_dir.name),
            'title': metadata.get('title', project_dir.name),
            'oneLiner': metadata.get('oneLiner') or metadata.get('description', ''),
            'categories': metadata.get('categories', []),
            'tags': metadata.get('tags', []),
            'kind': metadata.get('kind', 'project'),
            'status': metadata.get('status', 'active'),
            'path': path_str,
            'rel_path': str(rel_path),
            'screenshot_path': str(screenshot_path) if screenshot_exists else None,
            'screenshot_url': metadata.get('screenshot'),
            'category': category,
            'mtime': mtime,
            'has_catalogue': catalogue_path.exists(),
            'is_pinned': path_str in pinned_paths,
            'cursor_recent_idx': cursor_recent_idx,  # None if not in Cursor recent
            'cursor_url': f"cursor://file/{project_dir}",
            'runnable': runnable,
            'server_type': server_info.get('type') if runnable else None,
            'server_url': server_info.get('url') if runnable else None,
            'server_port': server_info.get('port') if runnable else None,
            'port_designated': bool((metadata.get('server') or {}).get('port')),
            'has_server_block': bool(metadata.get('server')),
            'description': metadata.get('description') or metadata.get('oneLiner') or '',
            'git': git_info,
            'last_commit_ts': git_info.get('last_commit_ts') or 0,
            'last_commit_rel': git_info.get('last_commit_rel'),
            'last_commit_subject': git_info.get('last_commit_subject'),
            'recent_subjects': git_info.get('recent_subjects', []),
        }
        
        return project
        
    except Exception as e:
        print(f"⚠️  Error processing {project_dir}: {e}")
        return None


def encode_image_to_base64(image_path: str) -> Optional[str]:
    """Convert image to base64 for embedding in HTML."""
    try:
        with open(image_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
            return f"data:image/png;base64,{encoded}"
    except:
        return None


def public_open_url(project: Dict) -> str:
    """Best public link: live demo, else the GitHub repo."""
    for key in ("homepage", "html_url"):
        url = (project.get(key) or "").strip()
        if url.startswith(("http://", "https://")):
            return url
    git = project.get("git") or {}
    owner = git.get("owner")
    repo = git.get("repo_name") or project.get("id")
    if owner and repo:
        return f"https://github.com/{owner}/{repo}"
    rel = project.get("rel_path") or ""
    if "/" in rel:
        return f"https://github.com/{rel}"
    return ""


def _js_url(url: str) -> str:
    return (url or "").replace("\\", "\\\\").replace("'", "\\'")


def github_open_url(project: Dict) -> str:
    if PUBLIC_MODE:
        return public_open_url(project) or (project.get("html_url") or "")
    return project.get("html_url") or ""


def github_card_open_actions(project: Dict) -> str:
    """Action buttons on a GitHub card. Public pages omit clone (needs localhost)."""
    html_url = _js_url(github_open_url(project))
    if PUBLIC_MODE:
        return (
            f'<button class="action-btn both-btn" onclick="openGithub(\'{html_url}\', event)" '
            f'title="Open">↗ Open</button>'
        )
    clone_url = _js_url(project.get("clone_url") or "")
    name = (project.get("id") or "").replace("'", "\\'")
    return (
        f'<button class="action-btn clone-btn" onclick="cloneRepo(\'{clone_url}\', \'{name}\', event)" '
        f'title="Clone into ~/{name} and open in Cursor">⬇ Clone</button>'
        f'<button class="action-btn gen-btn" onclick="cloneRepoSetup(\'{clone_url}\', \'{name}\', event)" '
        f'title="Clone, then auto-generate catalogue.json + screenshot.png locally">⬇✨</button>'
        f'<button class="action-btn both-btn" onclick="openGithub(\'{html_url}\', event)" '
        f'title="Open on GitHub">↗</button>'
    )


def resolve_screenshot_src(project: Dict) -> Optional[str]:
    """Return a value usable as an <img src> for a project card.

    Order of preference:
      1. A physical file (local screenshot.png or a downloaded GitHub asset),
         embedded as a base64 data URI (skipped in --public so Pages HTML stays small).
      2. The catalogue.json `screenshot` field (the same field the homepage
         uses). Absolute http(s)/data URLs are used as-is; relative paths like
         `./screenshot.png` are resolved against the repo's raw URL (for remote
         GitHub repos) or the local project dir (for local projects).
    Returns None if nothing usable is found.
    """
    # 1) Physical file: local screenshot.png or a downloaded gh_assets/*.png
    # Public dashboard hotlinks instead of embedding (keeps the Pages file small).
    file_path = project.get('screenshot_path')
    if file_path and not PUBLIC_MODE:
        data = encode_image_to_base64(file_path)
        if data:
            return data

    # 2) Fall back to the catalogue `screenshot` field
    url = (project.get('screenshot_url') or '').strip()
    if not url and project.get('has_catalogue') and project.get('raw_base'):
        url = './screenshot.png'
    if not url:
        return None
    if url.startswith(('http://', 'https://', 'data:')):
        return url

    # Relative path (e.g. "./screenshot.png" or "assets/shot.png")
    rel = url.lstrip('/')
    if rel.startswith('./'):
        rel = rel[2:]

    if project.get('source') == 'github':
        # Resolve against the repo's raw.githubusercontent.com base
        base = project.get('raw_base')
        if base:
            return base.rstrip('/') + '/' + rel
        return None

    # Local project: resolve relative to the project folder and embed it
    if PUBLIC_MODE:
        return None
    proj_path = project.get('path')
    if proj_path:
        return encode_image_to_base64(os.path.join(proj_path, rel))
    return None


def render_git_status(project: Dict) -> str:
    """Compact one-line git status used on grid/feed cards."""
    g = project.get('git') or {}
    if project.get('source') == 'github':
        vis = g.get('visibility')
        vis_pill = ('<span class="git-pill pub" title="public on GitHub">🌐 public</span>'
                    if vis == 'public' else
                    '<span class="git-pill priv" title="private on GitHub">🔒 private</span>')
        date = (f'<span class="git-pill date" title="last pushed">{html.escape(g.get("last_commit_rel") or "")}</span>'
                if g.get('last_commit_rel') else '')
        lang = (f'<span class="git-pill">{html.escape(project.get("language"))}</span>'
                if project.get('language') else '')
        return ('<div class="gitline">'
                '<span class="git-pill cloud" title="on GitHub, not cloned locally">☁ GitHub</span>'
                f'{vis_pill}{lang}{date}</div>')
    if not g.get('is_repo'):
        n = g.get('file_count', 0)
        return f'<div class="gitline not-repo"><span class="git-pill files">📁 {n} item{"" if n == 1 else "s"}</span></div>'

    parts = []
    cur = next((b for b in g.get('branches', []) if b.get('current')), None)
    branch = g.get('current_branch') or (g['branches'][0]['name'] if g.get('branches') else '')
    if branch:
        parts.append(f'<span class="git-pill branch" title="current branch">⎇ {html.escape(branch)}</span>')
    if cur:
        if cur.get('ahead'):
            parts.append(f'<span class="git-pill ahead" title="commits ahead of origin">↑{cur["ahead"]}</span>')
        if cur.get('behind'):
            parts.append(f'<span class="git-pill behind" title="commits behind origin">↓{cur["behind"]}</span>')
    unc = g.get('uncommitted', 0)
    if unc:
        parts.append(f'<span class="git-pill dirty" title="uncommitted files">●{unc}</span>')
    else:
        parts.append('<span class="git-pill clean" title="working tree clean">✓</span>')
    if not g.get('has_remote'):
        parts.append('<span class="git-pill no-remote" title="no remote origin">⊘ local</span>')
    elif g.get('visibility') == 'public':
        parts.append('<span class="git-pill pub" title="public on remote">🌐 public</span>')
    elif g.get('visibility') == 'private':
        parts.append('<span class="git-pill priv" title="private on remote">🔒 private</span>')
    else:
        parts.append('<span class="git-pill remote" title="has remote origin">⬆ remote</span>')
    if g.get('last_commit_rel'):
        parts.append(f'<span class="git-pill date" title="last commit">{html.escape(g["last_commit_rel"])}</span>')
    return '<div class="gitline">' + ''.join(parts) + '</div>'


def render_git_branches(project: Dict) -> str:
    """Collapsible per-branch tracking detail (Feed view)."""
    g = project.get('git') or {}
    branches = g.get('branches') or []
    if not g.get('is_repo') or not branches:
        return ''
    items = []
    for b in branches:
        if b.get('gone'):
            sync = '<span class="b-gone">upstream gone</span>'
        elif b.get('upstream'):
            bits = []
            if b.get('ahead'):
                bits.append(f'↑{b["ahead"]}')
            if b.get('behind'):
                bits.append(f'↓{b["behind"]}')
            sync = ' '.join(bits) if bits else '<span class="b-ok">up to date</span>'
        else:
            sync = '<span class="b-noup">no upstream</span>'
        name = html.escape(b['name'])
        label = f'<b>{name}</b>' if b.get('current') else name
        items.append(f'<li>{label} <span class="b-sync">{sync}</span></li>')
    return (
        f'<details class="feed-branches"><summary>{len(branches)} branch'
        f'{"" if len(branches) == 1 else "es"}</summary><ul>{"".join(items)}</ul></details>'
    )


def render_port(project: Dict) -> str:
    """Port pill: number, designated/auto, conflict warning, live state via JS."""
    port = project.get('server_port')
    if not port:
        return ''
    conflict = project.get('port_conflict')
    designated = project.get('port_designated')
    classes = 'port-pill'
    classes += ' conflict' if conflict else (' designated' if designated else ' auto')
    if conflict:
        title = 'Port conflict — another project also uses this port'
    elif designated:
        title = 'Designated port (from catalogue.json)'
    else:
        title = 'Auto-detected port'
    warn = '⚠ ' if conflict else ''
    return f'<span class="{classes}" data-port="{port}" title="{title}">{warn}:{port}</span>'


def generate_github_card_html(project: Dict) -> str:
    """Card for a GitHub repo that is not cloned locally."""
    img_tag = '<div class="no-screenshot">☁</div>'
    src = resolve_screenshot_src(project)
    if src:
        img_tag = f'<img src="{html.escape(src, quote=True)}" alt="" class="screenshot" loading="lazy">'
    title = html.escape(project['title'])
    one_liner = html.escape(project.get('oneLiner') or 'No description')
    full = html.escape(project.get('rel_path', ''))
    html_url = _js_url(github_open_url(project))
    git_status_html = render_git_status(project)
    search_str = html.escape(
        f"{project['title']} {one_liner} {full} {' '.join(project.get('tags', []))} github {project.get('sorter_group','')}",
        quote=True,
    )
    cat_badge = ('<span class="badge cat-github">GitHub</span>')
    actions = github_card_open_actions(project)
    return f'''
    <div class="project-card github-card searchable" {item_filter_attrs(project)}
         data-search="{search_str}"
         data-name="{html.escape(project['title'].lower(), quote=True)}"
         data-mtime="{project.get('mtime', 0)}" data-commit="{project.get('last_commit_ts', 0)}"
         data-runnable="false" data-port="">
        <div class="screenshot-container" onclick="openGithub('{html_url}', event)">
            {img_tag}
            <div class="badges">{cat_badge}</div>
            <div class="card-actions">
                {actions}
            </div>
        </div>
        <div class="project-info" onclick="openGithub('{html_url}', event)">
            <h3>{title}</h3>
            <p class="one-liner">{one_liner}</p>
            {git_status_html}
        </div>
    </div>
    '''


def generate_card_html(project: Dict, compact: bool = False, show_category: bool = False, extra_attrs: str = '') -> str:
    """Generate HTML for a single project card."""
    if project.get('source') == 'github':
        return generate_github_card_html(project)
    # Get screenshot
    img_tag = '<div class="no-screenshot">📁</div>'
    src = resolve_screenshot_src(project)
    if src:
        img_tag = f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(project["title"], quote=True)}" class="screenshot" loading="lazy">'
    
    # Build tags HTML
    tags_html = ""
    if project['tags'] and not compact:
        tags_html = '<div class="tags">' + ''.join([f'<span class="tag">{tag}</span>' for tag in project['tags'][:3]]) + '</div>'
    
    # Pin button
    pin_icon = "📌" if project['is_pinned'] else "📍"
    pin_class = "pinned" if project['is_pinned'] else ""
    
    # Catalogue indicator
    catalogue_badge = '<span class="badge catalogue">📋</span>' if project['has_catalogue'] else ''

    # Runnable-server indicator + action buttons
    server_badge = ''
    server_actions = ''
    if project.get('runnable'):
        stype = project.get('server_type') or 'server'
        server_badge = f'<span class="badge server" title="{stype} server available">▶</span>'
    
    # Category badge for recent view (color-coded)
    cat_class = f'cat-{project["category"].lower()}'
    category_badge = f'<span class="badge {cat_class}">{project["category"]}</span>' if show_category else ''
    
    # Escape quotes in path for JavaScript
    escaped_path = project['path'].replace("'", "\\'").replace('"', '\\"')

    if not compact:
        btns = []
        if project.get('runnable'):
            stype = project.get('server_type') or 'server'
            btns.append(f'<button class="action-btn run-btn" onclick="launchApp(\'{escaped_path}\', event)" title="Run {stype} server">▶ Run</button>')
            btns.append(f'<button class="action-btn both-btn" onclick="openBoth(\'{escaped_path}\', event)" title="Open in Cursor and run the app">🚀</button>')
        missing_cat = not project.get('has_catalogue')
        missing_shot = (not project.get('screenshot_path')) and project.get('runnable')
        if missing_cat and missing_shot:
            btns.append(f'<button class="action-btn gen-btn" onclick="autogenBoth(\'{escaped_path}\', event)" title="Auto-generate catalogue.json + screenshot.png">✨</button>')
        else:
            if missing_cat:
                btns.append(f'<button class="action-btn gen-btn" onclick="autogenCatalogue(\'{escaped_path}\', event)" title="Create catalogue.json">＋📋</button>')
            if missing_shot:
                btns.append(f'<button class="action-btn gen-btn" onclick="autogenScreenshot(\'{escaped_path}\', event)" title="Capture screenshot.png">📸</button>')
        git = project.get('git') or {}
        if git.get('is_repo') and git.get('uncommitted'):
            btns.append(f'<button class="action-btn sync-btn" onclick="commitNow(\'{escaped_path}\', event)" title="Commit and push uncommitted files">⬆</button>')
        if not git.get('has_remote'):
            btns.append(f'<button class="action-btn pub-btn" onclick="publishNow(\'{escaped_path}\', event)" title="Publish to GitHub with recommended defaults">🐙</button>')
        if btns:
            server_actions = '<div class="card-actions">' + ''.join(btns) + '</div>'

    card_class = "project-card compact" if compact else "project-card"
    
    # One-liner or fallback
    one_liner = project['oneLiner'] or 'No description'
    
    extra = f' {extra_attrs}' if extra_attrs else ''
    search_str = html.escape(
        f"{project['title']} {one_liner} {project.get('rel_path','')} "
        f"{' '.join(project.get('tags', []))} {project.get('category','')} {project.get('sorter_group','')}",
        quote=True,
    )
    name_key = html.escape(project['title'].lower(), quote=True)
    git_status_html = render_git_status(project)
    port_badge = render_port(project)
    data_attrs = (
        f'{item_filter_attrs(project)} '
        f'data-name="{name_key}" '
        f'data-mtime="{project.get("mtime", 0)}" '
        f'data-commit="{project.get("last_commit_ts", 0)}" '
        f'data-runnable="{str(project.get("runnable", False)).lower()}" '
        f'data-port="{project.get("server_port") or ""}"'
    )
    return f'''
    <div class="{card_class} {pin_class} searchable" data-path="{project['path']}" data-id="{project['id']}" data-search="{search_str}" {data_attrs}{extra}>
        <div class="screenshot-container" onclick="openProject('{escaped_path}', event)">
            {img_tag}
            <div class="badges">{catalogue_badge}{server_badge}{category_badge}{port_badge}</div>
            {server_actions}
        </div>
        <div class="project-info" onclick="openProject('{escaped_path}', event)">
            <h3>{project['title']}</h3>
            <p class="one-liner">{one_liner}</p>
            {git_status_html}
            {f'<p class="project-path">{project["rel_path"]}</p>' if not compact else ''}
            {tags_html}
        </div>
        <button class="manage-btn" onclick="openManage('{escaped_path}', event)" title="Manage project (publish, catalogue, screenshot)">⚙</button>
        <button class="pin-btn {pin_class}" onclick="togglePin('{escaped_path}', event)" title="{'Unpin' if project['is_pinned'] else 'Pin'} this project">
            {pin_icon}
        </button>
    </div>
    '''


def generate_home_folders_html(home_projects: List[Dict]) -> str:
    """Generate the Home Folders row with toggle for common macOS folders."""
    if not home_projects:
        return ''

    custom = [p for p in home_projects if not p.get('is_common_osx')]
    common = [p for p in home_projects if p.get('is_common_osx')]
    sorted_projects = custom + common

    cards_html = ''.join(
        generate_card_html(p, show_category=False, extra_attrs='data-osx="true"' if p.get('is_common_osx') else '')
        for p in sorted_projects
    )
    total = len(home_projects)
    hidden = len(common)

    return f'''
        <div class="category-row row-home" id="category-home">
            <div class="row-header">
                <h2 class="cat-home">🏠 Home Folders</h2>
                <span class="count">{total} folders</span>
                <label class="toggle-label">
                    <input type="checkbox" id="showOsxFolders" onchange="toggleOsxFolders(this.checked)">
                    <span class="toggle-switch"></span>
                    <span class="toggle-text">Show system folders ({hidden})</span>
                </label>
            </div>
            <div class="row-content" id="homeFoldersContent">
                {cards_html}
            </div>
        </div>
    '''


ROW_DOTS = [
    "#667eea", "#48bb78", "#ed8936", "#9f7aea",
    "#e53e3e", "#38b2ac", "#4fd1c5", "#d69e2e",
]


def generate_group_rows_html(projects: List[Dict], group_data: Dict) -> str:
    """Netflix-style rows from sorter.html categories, in saved column order."""
    columns = [c for c in (group_data.get("columns") or []) if c.get("id")]
    if not columns:
        return ""

    by_gid: Dict[str, List[Dict]] = {}
    unassigned: List[Dict] = []
    for p in projects:
        gid = str(p.get("sorter_group_id") or "")
        if gid:
            by_gid.setdefault(gid, []).append(p)
        else:
            unassigned.append(p)

    if unassigned:
        by_gid.setdefault("general", []).extend(unassigned)

    def render_row(col, idx, locked=False):
        cid = str(col.get("id"))
        items = by_gid.get(cid) or []
        if not items:
            return ""
        items = order_projects_by_names(items, col.get("names") or [])
        title = (col.get("title") or "Untitled").strip() or "Untitled"
        cards = "".join(generate_card_html(p, show_category=False) for p in items)
        dot = ROW_DOTS[idx % len(ROW_DOTS)]
        stripe = "row-even" if idx % 2 == 0 else "row-odd"
        safe_id = html.escape(cid, quote=True)
        handle = (
            ""
            if locked
            else '<span class="row-handle" draggable="true" title="Drag to reorder this category">⋮⋮</span>'
        )
        locked_attr = ' data-locked="1"' if locked else ""
        return (
            f'''<div class="category-row {stripe}" data-group-id="{safe_id}"{locked_attr}>
            <div class="row-header">
                {handle}
                <h2 style="--dot:{dot}">{html.escape(title)}</h2>
                <span class="count">{len(items)}</span>
            </div>
            <div class="row-content">{cards}</div>
        </div>'''
        )

    rows = []
    idx = 0
    general_col = None
    for col in columns:
        if str(col.get("id")) == "general":
            general_col = col
            continue
        html_row = render_row(col, idx)
        if html_row:
            rows.append(html_row)
            idx += 1
    if general_col:
        html_row = render_row(general_col, idx, locked=True)
        if html_row:
            rows.append(html_row)

    if not rows:
        return ""
    return f'<div class="categories-container" id="groupRows">{"".join(rows)}</div>'


def generate_feed_card_html(project: Dict) -> str:
    """A large, social-feed-style card with description + latest git changes."""
    img_tag = '<div class="no-screenshot">📁</div>'
    src = resolve_screenshot_src(project)
    if src:
        img_tag = f'<img src="{html.escape(src, quote=True)}" alt="" class="feed-screenshot" loading="lazy">'

    escaped_path = project['path'].replace("'", "\\'").replace('"', '\\"')
    title = html.escape(project['title'])
    desc = html.escape(project.get('description') or project.get('oneLiner') or 'No description')
    cat = project['category']
    cat_label = html.escape(cat)
    git = project.get('git') or {}

    if git.get('last_commit_subject'):
        commit_html = (
            f'<div class="feed-commit">'
            f'<span class="commit-label">latest</span>'
            f'<span class="commit-subject">{html.escape(git["last_commit_subject"])}</span>'
            f'<span class="commit-date">{html.escape(git.get("last_commit_rel") or "")}</span>'
            f'</div>'
        )
    elif project.get('mtime'):
        mod = datetime.fromtimestamp(project['mtime']).strftime('%b %d, %Y')
        commit_html = (
            f'<div class="feed-commit"><span class="commit-label">modified</span>'
            f'<span class="commit-date">{mod}</span></div>'
        )
    else:
        commit_html = ''

    subs = git.get('recent_subjects') or []
    changes_html = ''
    if len(subs) > 1:
        items = ''.join(f'<li>{html.escape(s)}</li>' for s in subs)
        changes_html = (
            f'<details class="feed-changes"><summary>{len(subs)} recent changes</summary>'
            f'<ul>{items}</ul></details>'
        )

    tags_html = ''
    if project.get('tags'):
        tags_html = '<div class="feed-tags">' + ''.join(
            f'<span class="tag">{html.escape(t)}</span>' for t in project['tags'][:5]
        ) + '</div>'

    actions = ''
    if project.get('runnable'):
        stype = project.get('server_type') or 'server'
        actions = (
            f'<button class="action-btn run-btn" onclick="launchApp(\'{escaped_path}\', event)" title="Run {stype} server">▶ Run</button>'
            f'<button class="action-btn both-btn" onclick="openBoth(\'{escaped_path}\', event)" title="Open in Cursor + run app">🚀 Both</button>'
        )
    missing_cat = not project.get('has_catalogue')
    missing_shot = (not project.get('screenshot_path')) and project.get('runnable')
    if missing_cat and missing_shot:
        actions += f'<button class="action-btn gen-btn" onclick="autogenBoth(\'{escaped_path}\', event)" title="Auto-generate catalogue + screenshot">✨ Generate</button>'
    else:
        if missing_cat:
            actions += f'<button class="action-btn gen-btn" onclick="autogenCatalogue(\'{escaped_path}\', event)" title="Create catalogue.json">＋ Catalogue</button>'
        if missing_shot:
            actions += f'<button class="action-btn gen-btn" onclick="autogenScreenshot(\'{escaped_path}\', event)" title="Capture screenshot.png">📸 Screenshot</button>'
    git = project.get('git') or {}
    if git.get('is_repo') and git.get('uncommitted'):
        actions += f'<button class="action-btn sync-btn" onclick="commitNow(\'{escaped_path}\', event)" title="Commit and push uncommitted files">⬆ Commit</button>'
    if not git.get('has_remote'):
        actions += f'<button class="action-btn pub-btn" onclick="publishNow(\'{escaped_path}\', event)" title="Publish to GitHub with recommended defaults">🐙 Publish</button>'

    search_str = html.escape(
        f"{project['title']} {desc} {project.get('rel_path','')} "
        f"{' '.join(project.get('tags', []))} {cat} {project.get('sorter_group','')}",
        quote=True,
    )
    git_status_html = render_git_status(project)
    git_branches_html = render_git_branches(project)
    port_badge = render_port(project)
    group = project.get("sorter_group") or ""
    group_chip = (
        f'<span class="chip chip-group">{html.escape(group)}</span>' if group else ""
    )
    return f'''
    <article class="feed-card searchable" {item_filter_attrs(project)} data-search="{search_str}" data-port="{project.get('server_port') or ''}">
        <div class="feed-thumb" onclick="openProject('{escaped_path}', event)">{img_tag}</div>
        <div class="feed-body">
            <div class="feed-head">
                <span class="chip chip-{cat.lower()}">{cat_label}</span>
                {group_chip}
                <h3 onclick="openProject('{escaped_path}', event)">{title}</h3>
                {port_badge}
            </div>
            <p class="feed-desc">{desc}</p>
            {commit_html}
            {git_status_html}
            {git_branches_html}
            {changes_html}
            {tags_html}
            <div class="feed-actions">
                <button class="action-btn open-btn" onclick="openProject('{escaped_path}', event)">Open in Cursor</button>
                {actions}
                <button class="action-btn manage-inline" onclick="openManage('{escaped_path}', event)" title="Manage">⚙ Manage</button>
                <span class="feed-path">{html.escape(project.get('rel_path',''))}</span>
            </div>
        </div>
    </article>
    '''


def generate_github_feed_card_html(project: Dict) -> str:
    """Feed card for a GitHub repo that isn't cloned locally."""
    img_tag = '<div class="no-screenshot">☁</div>'
    src = resolve_screenshot_src(project)
    if src:
        img_tag = f'<img src="{html.escape(src, quote=True)}" alt="" class="feed-screenshot" loading="lazy">'
    title = html.escape(project['title'])
    desc = html.escape(project.get('description') or project.get('oneLiner') or 'No description')
    html_url = _js_url(github_open_url(project))
    git_status_html = render_git_status(project)
    search_str = html.escape(
        f"{project['title']} {desc} {project.get('rel_path','')} github {project.get('sorter_group','')}", quote=True)
    group = project.get("sorter_group") or ""
    group_chip = (
        f'<span class="chip chip-group">{html.escape(group)}</span>' if group else ""
    )
    actions = github_card_open_actions(project)
    return f'''
    <article class="feed-card github-card searchable" {item_filter_attrs(project)} data-search="{search_str}">
        <div class="feed-thumb" onclick="openGithub('{html_url}', event)">{img_tag}</div>
        <div class="feed-body">
            <div class="feed-head">
                <span class="chip chip-github">GitHub</span>
                {group_chip}
                <h3 onclick="openGithub('{html_url}', event)">{title}</h3>
            </div>
            <p class="feed-desc">{desc}</p>
            {git_status_html}
            <div class="feed-actions">
                {actions}
                <span class="feed-path">{html.escape(project.get('rel_path',''))}</span>
            </div>
        </div>
    </article>
    '''


def generate_feed_html(projects: List[Dict]) -> str:
    """Feed view: single column, most recent activity first (pinned float up)."""
    def recency(p):
        return max(p.get('last_commit_ts') or 0, p.get('mtime') or 0)
    ordered = sorted(projects, key=lambda p: (p.get('is_pinned', False), recency(p)), reverse=True)
    cards = ''.join(
        generate_github_feed_card_html(p) if p.get('source') == 'github'
        else generate_feed_card_html(p)
        for p in ordered
    )
    return f'<div class="feed-container">{cards}</div>'


def _github_table_row(p: Dict, columns: Optional[List[Dict]] = None) -> str:
    """A table row for a GitHub repo that isn't cloned locally."""
    title = html.escape(p['title'])
    html_url = _js_url(github_open_url(p))
    private = p.get('private')
    remote = '🔒 private' if private else '🌐 public'
    remote_sort = 2 if private else 3
    commit_ts = p.get('last_commit_ts') or 0
    commit_rel = html.escape(p.get('last_commit_rel') or '')
    has_cat = p.get('has_catalogue')
    has_shot = bool(p.get('screenshot_path') or p.get('screenshot_url') or p.get('has_catalogue'))
    cat_cell = '<span class="has-yes">✓</span>' if has_cat else '<span class="has-no">—</span>'
    shot_cell = '<span class="has-yes">✓</span>' if has_shot else '<span class="has-no">—</span>'
    actions = github_card_open_actions(p)
    group = p.get("sorter_group") or ""
    search_str = html.escape(f"{p['title']} {p.get('rel_path','')} github {group}", quote=True)
    return f'''<tr class="table-row github-row searchable" {item_filter_attrs(p)} data-search="{search_str}" onclick="openGithub('{html_url}', event)">
        <td class="td-title">{title} <span class="gh-tag">☁</span></td>
        <td><span class="chip chip-github">GitHub</span></td>
        <td data-sort="{html.escape(group.lower())}" onclick="event.stopPropagation()">{group_select_html(p, columns or [])}</td>
        <td data-sort="">—</td>
        <td data-sort="-1" class="td-mono">—</td>
        <td data-sort="-1" class="td-mono">—</td>
        <td data-sort="{remote_sort}">{remote}</td>
        <td data-sort="{commit_ts}">{commit_rel}</td>
        <td data-sort="{p.get('mtime', 0)}">{datetime.fromtimestamp(p['mtime']).strftime('%Y-%m-%d') if p.get('mtime') else ''}</td>
        <td>{html.escape(p.get('status') or '')}</td>
        <td data-sort="0" class="td-port">—</td>
        <td data-sort="{1 if has_cat else 0}" class="td-has">{cat_cell}</td>
        <td data-sort="{1 if has_shot else 0}" class="td-has">{shot_cell}</td>
        <td class="td-run" data-sort="0">{actions}</td>
    </tr>'''


def generate_table_html(projects: List[Dict], columns: Optional[List[Dict]] = None) -> str:
    """Sortable, Gmail-style table view."""
    columns = columns or []
    def recency(p):
        return max(p.get('last_commit_ts') or 0, p.get('mtime') or 0)
    ordered = sorted(projects, key=recency, reverse=True)

    rows = ''
    for p in ordered:
        if p.get('source') == 'github':
            rows += _github_table_row(p, columns)
            continue
        escaped_path = p['path'].replace("'", "\\'").replace('"', '\\"')
        title = html.escape(p['title'])
        cat = p['category']
        g = p.get('git') or {}
        is_repo = bool(g.get('is_repo'))
        commit_ts = p.get('last_commit_ts') or 0
        commit_rel = html.escape(p.get('last_commit_rel') or ('' if is_repo else '—'))
        mtime = p.get('mtime') or 0
        mod = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d') if mtime else ''
        status = html.escape(p.get('status') or '')

        # Git dimension cells
        cur = next((b for b in g.get('branches', []) if b.get('current')), None)
        branch = html.escape(g.get('current_branch') or '') if is_repo else '—'
        if cur and (cur.get('ahead') or cur.get('behind')):
            sync = f'↑{cur.get("ahead",0)} ↓{cur.get("behind",0)}'
            sync_sort = cur.get('ahead', 0) + cur.get('behind', 0)
        elif is_repo:
            sync = '✓' if g.get('has_remote') else '—'
            sync_sort = 0
        else:
            sync = '—'
            sync_sort = -1
        if is_repo:
            dirty = g.get('uncommitted', 0)
            dirty_disp = f'●{dirty}' if dirty else '✓'
            dirty_sort = dirty
        else:
            dirty = g.get('file_count', 0)
            dirty_disp = f'{dirty} files'
            dirty_sort = dirty
        if not is_repo:
            remote = '—'; remote_sort = 0
        elif not g.get('has_remote'):
            remote = 'local'; remote_sort = 1
        elif g.get('visibility') == 'public':
            remote = '🌐 public'; remote_sort = 3
        elif g.get('visibility') == 'private':
            remote = '🔒 private'; remote_sort = 2
        else:
            remote = 'remote'; remote_sort = 2

        run_cell = ''
        if p.get('runnable'):
            run_cell = (
                f'<button class="action-btn run-btn tbl-run" onclick="launchApp(\'{escaped_path}\', event)" '
                f'title="Run server">▶</button>'
            )
        manage_cell = (
            f'<button class="action-btn manage-inline tbl-run" onclick="openManage(\'{escaped_path}\', event)" '
            f'title="Manage">⚙</button>'
        )
        git = p.get('git') or {}
        if git.get('is_repo') and git.get('uncommitted'):
            manage_cell += (
                f'<button class="action-btn sync-btn tbl-run" onclick="commitNow(\'{escaped_path}\', event)" '
                f'title="Commit and push">⬆</button>'
            )
        if not git.get('has_remote'):
            manage_cell += (
                f'<button class="action-btn pub-btn tbl-run" onclick="publishNow(\'{escaped_path}\', event)" '
                f'title="Publish to GitHub">🐙</button>'
            )
        has_cat = p.get('has_catalogue')
        has_shot = bool(p.get('screenshot_path'))
        cat_cell = ('<span class="has-yes" title="catalogue.json present">✓</span>'
                    if has_cat else
                    f'<button class="mini-gen" onclick="autogenCatalogue(\'{escaped_path}\', event)" title="Create catalogue.json">＋</button>')
        shot_cell = ('<span class="has-yes" title="screenshot.png present">✓</span>'
                     if has_shot else
                     (f'<button class="mini-gen" onclick="autogenScreenshot(\'{escaped_path}\', event)" title="Capture screenshot">📸</button>'
                      if p.get('runnable') else '<span class="has-no">—</span>'))
        port = p.get('server_port')
        if port:
            pcls = 'port-pill ' + ('conflict' if p.get('port_conflict') else ('designated' if p.get('port_designated') else 'auto'))
            warn = '⚠ ' if p.get('port_conflict') else ''
            port_cell = f'<span class="{pcls}" data-port="{port}">{warn}:{port}</span>'
            port_sort = port
        else:
            port_cell = '—'
            port_sort = 0
        group = p.get("sorter_group") or ""
        search_str = html.escape(
            f"{p['title']} {p.get('rel_path','')} {cat} {status} {branch} {group}", quote=True
        )
        rows += f'''<tr class="table-row searchable" {item_filter_attrs(p)} data-search="{search_str}" data-port="{port or ''}" onclick="openProject('{escaped_path}', event)">
            <td class="td-title">{title}</td>
            <td><span class="chip chip-{cat.lower()}">{html.escape(cat)}</span></td>
            <td data-sort="{html.escape(group.lower())}" onclick="event.stopPropagation()">{group_select_html(p, columns)}</td>
            <td data-sort="{html.escape((g.get('current_branch') or '').lower())}">{branch}</td>
            <td data-sort="{sync_sort}" class="td-mono">{sync}</td>
            <td data-sort="{dirty_sort}" class="td-mono">{dirty_disp}</td>
            <td data-sort="{remote_sort}">{remote}</td>
            <td data-sort="{commit_ts}">{commit_rel}</td>
            <td data-sort="{mtime}">{mod}</td>
            <td>{status}</td>
            <td data-sort="{port_sort}" class="td-port">{port_cell}</td>
            <td data-sort="{1 if has_cat else 0}" class="td-has">{cat_cell}</td>
            <td data-sort="{1 if has_shot else 0}" class="td-has">{shot_cell}</td>
            <td class="td-run" data-sort="{1 if p.get('runnable') else 0}">{run_cell}{manage_cell}</td>
        </tr>'''

    return f'''
    <div class="table-container">
        <table class="data-table" id="dataTable">
            <thead><tr>
                <th class="sortable-th" onclick="sortTable(0,'text')">Project</th>
                <th class="sortable-th" onclick="sortTable(1,'text')">Category</th>
                <th class="sortable-th" onclick="sortTable(2,'text')">Group</th>
                <th class="sortable-th" onclick="sortTable(3,'text')">Branch</th>
                <th class="sortable-th" onclick="sortTable(4,'num')">Sync</th>
                <th class="sortable-th" onclick="sortTable(5,'num')">Dirty</th>
                <th class="sortable-th" onclick="sortTable(6,'num')">Remote</th>
                <th class="sortable-th" onclick="sortTable(7,'num')">Last commit</th>
                <th class="sortable-th" onclick="sortTable(8,'num')">Modified</th>
                <th class="sortable-th" onclick="sortTable(9,'text')">Status</th>
                <th class="sortable-th" onclick="sortTable(10,'num')">Port</th>
                <th class="sortable-th" onclick="sortTable(11,'num')" title="catalogue.json present?">Cat</th>
                <th class="sortable-th" onclick="sortTable(12,'num')" title="screenshot.png present?">Shot</th>
                <th class="sortable-th" onclick="sortTable(13,'num')">Actions</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    '''


def generate_html(projects: List[Dict]) -> str:
    """Generate HTML dashboard."""

    group_data = load_repo_groups()

    if PUBLIC_MODE:
        try:
            display_projects = github_repos.load_public_projects(
                progress=lambda m: print(f"   {m}", flush=True))
        except Exception as e:
            print(f"⚠️  Public GitHub repos unavailable: {e}")
            display_projects = []
        allowed = set()
        for p in display_projects:
            p.setdefault('source', 'github')
            anonymize_project_for_public(p)
            allowed.update(_project_name_keys(p))
        allowed.update(public_repo_names())
        group_data = sanitize_groups_for_public(group_data, allowed)
        for p in display_projects:
            assign_sorter_group(p, group_data["by_repo"])
    else:
        # Common macOS system folders are noise in a single list; hide them.
        display_projects = [p for p in projects if not p.get('is_common_osx')]
        for p in display_projects:
            p.setdefault('source', 'local')

        # Append remote-only GitHub repos (not cloned locally). Deduped by the
        # owner/repo of each local clone's origin remote.
        local_remotes = set()
        for p in display_projects:
            g = p.get('git') or {}
            if g.get('owner') and g.get('repo_name'):
                local_remotes.add(f"{g['owner']}/{g['repo_name']}")
        try:
            remote_projects = github_repos.load_remote_projects(local_remotes)
        except Exception as e:
            print(f"⚠️  GitHub repos unavailable: {e}")
            remote_projects = []
        display_projects = display_projects + remote_projects

        for p in display_projects:
            assign_sorter_group(p, group_data["by_repo"])

        # Port registry: detect collisions (same port designated by >1 project) and
        # write a ports.json the server uses for the live Ports overview.
        port_owners: Dict[int, List[Dict]] = {}
        for p in display_projects:
            port = p.get('server_port')
            if port:
                port_owners.setdefault(port, []).append(p)
        for p in display_projects:
            port = p.get('server_port')
            p['port_conflict'] = bool(port and len(port_owners.get(port, [])) > 1)
        try:
            registry = {
                'generated': datetime.now().isoformat(),
                'projects': [
                    {
                        'title': p['title'],
                        'path': p['path'],
                        'port': p.get('server_port'),
                        'designated': p.get('port_designated', False),
                        'type': p.get('server_type'),
                    }
                    for p in display_projects if p.get('server_port')
                ],
            }
            (Path(__file__).parent / 'ports.json').write_text(json.dumps(registry, indent=2))
        except Exception:
            pass

    pinned_projects = [p for p in display_projects if p['is_pinned']]

    # Default ordering for the single grid: most recent activity first,
    # pinned projects floated to the top. Client-side JS re-sorts on demand.
    def recency(p):
        return max(p.get('last_commit_ts') or 0, p.get('mtime') or 0)
    grid_ordered = sorted(
        display_projects,
        key=lambda p: (p.get('is_pinned', False), recency(p)),
        reverse=True,
    )
    grid_cards_html = ''.join(generate_card_html(p, show_category=True) for p in grid_ordered)

    # Category filter chips (only categories that actually have projects)
    cat_emoji = {"RESEARCH": "🔬", "TEACHING": "📚", "TOOLS": "🛠️",
                 "PUZZLES": "🧩", "HARDWARE": "🔧", "OTHER": "📂", "HOME": "🏠",
                 "GITHUB": "☁"}
    cat_label_override = {"GITHUB": "GitHub"}
    present_categories = []
    for cat in MAIN_CATEGORIES + ["OTHER", "HOME", "GITHUB"]:
        count = sum(1 for p in display_projects if p['category'] == cat)
        if count:
            present_categories.append((cat, count))

    n_local = sum(1 for p in display_projects if p.get('source') != 'github')
    n_github = sum(1 for p in display_projects if p.get('source') == 'github')

    filter_chips = ['<button class="fchip active" data-filter="all" onclick="setFilter(this,\'all\')">All</button>']
    if not PUBLIC_MODE:
        filter_chips.append(
            f'<button class="fchip" data-filter="__local" onclick="setFilter(this,\'__local\')">💻 Local <span class="fchip-count">{n_local}</span></button>'
        )
        if pinned_projects:
            filter_chips.append(
                f'<button class="fchip" data-filter="__pinned" onclick="setFilter(this,\'__pinned\')">📌 Pinned</button>'
            )
        for cat, count in present_categories:
            emoji = cat_emoji.get(cat, '📁')
            label = cat_label_override.get(cat, cat.title())
            filter_chips.append(
                f'<button class="fchip" data-filter="{cat}" onclick="setFilter(this,\'{cat}\')">'
                f'{emoji} {label} <span class="fchip-count">{count}</span></button>'
            )
    filter_chips_html = ''.join(filter_chips)

    group_chip_bits = []
    for col in group_data.get("columns") or []:
        cid = str(col.get("id") or "")
        title = (col.get("title") or "Untitled").strip() or "Untitled"
        count = sum(1 for p in display_projects if p.get("sorter_group_id") == cid)
        if not cid or count == 0:
            continue
        group_chip_bits.append(
            f'<button class="fchip" data-group="{html.escape(cid, quote=True)}" '
            f'onclick="setGroupFilter(this,\'{_js_str(cid)}\')">'
            f'{html.escape(title)} <span class="fchip-count">{count}</span></button>'
        )
    if group_chip_bits:
        group_chips_html = (
            '<button class="fchip active" data-group="all" onclick="setGroupFilter(this,\'all\')">All groups</button>'
            + ''.join(group_chip_bits)
        )
        group_filters_block = (
            '<div class="filter-row">'
            '<span class="filter-row-label">Groups</span>'
            f'<div class="filter-chips group-chips">{group_chips_html}</div>'
            + ('' if PUBLIC_MODE else
               '<a class="rows-hint" href="sorter.html" style="margin:6px 0 0;white-space:nowrap">Edit categories</a>')
            + '</div>'
        )
    else:
        group_filters_block = ''

    # Stats
    total = len(display_projects)
    with_catalogue = len([p for p in display_projects if p['has_catalogue']])

    # Feed + Table + sorter-category rows
    feed_html = generate_feed_html(display_projects)
    table_html = generate_table_html(display_projects, group_data.get("columns") or [])
    group_rows_html = generate_group_rows_html(display_projects, group_data)
    groups_json = json.dumps({
        "colsPerRow": group_data.get("colsPerRow") or "auto",
        "columns": group_data.get("columns") or [],
    }, ensure_ascii=False)
    has_group_rows = "true" if group_rows_html else "false"
    rows_view_btn = (
        '<button class="view-btn" data-view="rows" onclick="switchView(\'rows\')">☰ Rows</button>'
        if group_rows_html else ""
    )
    rows_view_block = (
        f'<div id="view-rows" class="view" style="display:none">'
        f'<p class="rows-hint">Rows are the categories from the repo sorter.'
        + ('' if PUBLIC_MODE else ' Drag ⋮⋮ to reorder. <a href="sorter.html">Edit categories</a>')
        + '</p>'
        f'{group_rows_html}</div>'
        if group_rows_html else ""
    )

    if PUBLIC_MODE:
        page_title = "Kyle Mathewson — Projects"
        page_description = (
            '<meta name="description" content="Public GitHub projects in grid and feed views.">\n'
            '    <link rel="canonical" href="https://kylemath.github.io/cursor-launcher/">'
        )
        header_heading = "Projects"
        header_right = f'''<div class="stats">
                            <div class="stat">{total} public repos</div>
                            <div class="stat">{with_catalogue} catalogued</div>
                        </div>'''
        extra_controls = '''<a class="port-overview-btn" href="https://github.com/kylemath">GitHub</a>
                    <a class="port-overview-btn" href="https://kylemathewson.com">Homepage</a>
                    <button class="legend-btn" onclick="toggleLegend()" title="Show key for icons and colors">? Legend</button>'''
        public_page_js = "true"
    else:
        page_title = "Cursor Project Launcher"
        page_description = ""
        header_heading = "Project Launcher"
        header_right = f'''<div class="stats">
                            <div class="stat">{total} projects</div>
                            <div class="stat">{with_catalogue} catalogued</div>
                            <div class="stat">{len(pinned_projects)} pinned</div>
                            <div class="stat" id="serverStatus">⏳</div>
                        </div>
                        <button class="shutdown-btn" onclick="shutdownDashboard()" title="Stop the Project Launcher server">⏹ Stop server</button>'''
        extra_controls = '''<button class="port-overview-btn" id="portsBtn" onclick="openPorts()" title="All designated ports + conflicts">🔌 Ports</button>
                    <button class="port-overview-btn newproj-btn" onclick="newProject()" title="Create a new folder in ~ and open it in Cursor">＋ New project</button>
                    <button class="port-overview-btn" id="refreshBtn" onclick="reloadWithFreshCards()" title="Rescan local folders and git status, then reload">↻ Refresh</button>
                    <button class="port-overview-btn" id="ghRefreshBtn" onclick="refreshGithub()" title="Re-fetch your GitHub repos (incl. private)">↻ GitHub</button>
                    <button class="legend-btn" onclick="toggleLegend()" title="Show key for icons and colors">? Legend</button>'''
        public_page_js = "false"

    # Full HTML
    page = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    {page_description}
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #fff;
        }}
        
        .main-layout {{
            min-height: 100vh;
        }}
        
        .main-content {{ padding: 20px 40px; }}
        
        header {{ text-align: center; margin-bottom: 25px; }}
        
        header h1 {{
            font-size: 32px;
            margin-bottom: 6px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        header p {{ font-size: 13px; opacity: 0.7; }}
        
        .stats {{
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-top: 12px;
            flex-wrap: wrap;
        }}
        
        .stat {{
            background: rgba(255,255,255,0.1);
            padding: 6px 14px;
            border-radius: 15px;
            font-size: 12px;
        }}
        
        .search-box {{ max-width: 500px; margin: 0 auto 25px; }}
        
        .search-box input {{
            width: 100%;
            padding: 10px 18px;
            font-size: 14px;
            border: none;
            border-radius: 20px;
            background: rgba(255,255,255,0.1);
            color: white;
            outline: none;
        }}
        
        .search-box input::placeholder {{ color: rgba(255,255,255,0.4); }}
        .search-box input:focus {{ background: rgba(255,255,255,0.15); box-shadow: 0 0 0 2px rgba(102,126,234,0.5); }}
        
        /* Category rows layout (Netflix-style) */
        .categories-container {{
            display: flex;
            flex-direction: column;
            gap: 25px;
        }}
        
        .category-row {{
            padding: 0;
        }}
        
        .category-row.row-even {{
            background: rgba(255,255,255,0.02);
            margin: 0 -40px;
            padding: 15px 40px;
        }}
        
        .category-row.row-odd {{
            background: rgba(0,0,0,0.1);
            margin: 0 -40px;
            padding: 15px 40px;
        }}
        
        .category-row.row-pinned,
        .category-row.row-recent {{
            margin: 0 -40px;
            padding: 15px 40px;
        }}
        
        .row-header {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }}
        
        .row-header h2 {{
            font-size: 18px;
            color: #fff;
            margin: 0;
            padding: 6px 14px;
            border-radius: 6px;
        }}
        
        .row-header .count {{
            background: rgba(255,255,255,0.15);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            color: rgba(255,255,255,0.8);
        }}

        .row-handle {{
            flex-shrink: 0;
            cursor: grab;
            color: rgba(255,255,255,0.35);
            font-size: 14px;
            line-height: 1;
            letter-spacing: -1px;
            padding: 4px 2px;
            user-select: none;
        }}
        .row-handle:hover {{ color: rgba(255,255,255,0.8); }}
        .row-handle:active {{ cursor: grabbing; }}
        .category-row.row-dragging {{ opacity: 0.35; }}
        .row-placeholder {{
            height: 8px;
            border-radius: 4px;
            background: #667eea;
            box-shadow: 0 0 10px rgba(102,126,234,0.6);
            margin: 2px 0 10px;
        }}
        .rows-hint {{
            font-size: 12.5px;
            opacity: 0.6;
            margin: 0 0 16px;
        }}
        .rows-hint a {{ color: #a5b4fc; }}
        
        /* Category colors */
        .cat-pinned {{ background: linear-gradient(135deg, #f6e05e 0%, #d69e2e 100%); color: #744210; }}
        .cat-recent {{ background: linear-gradient(135deg, #4fd1c5 0%, #319795 100%); }}
        .cat-research {{ background: linear-gradient(135deg, #667eea 0%, #5a67d8 100%); }}
        .cat-teaching {{ background: linear-gradient(135deg, #48bb78 0%, #38a169 100%); }}
        .cat-tools {{ background: linear-gradient(135deg, #ed8936 0%, #dd6b20 100%); }}
        .cat-puzzles {{ background: linear-gradient(135deg, #9f7aea 0%, #805ad5 100%); }}
        .cat-hardware {{ background: linear-gradient(135deg, #e53e3e 0%, #c53030 100%); }}
        .cat-other {{ background: linear-gradient(135deg, #718096 0%, #4a5568 100%); }}
        .cat-home {{ background: linear-gradient(135deg, #38b2ac 0%, #2c7a7b 100%); }}
        
        .row-pinned {{ background: rgba(246,224,94,0.08) !important; }}
        .row-recent {{ background: rgba(79,209,197,0.08) !important; }}
        .row-home {{ background: rgba(56,178,172,0.06) !important; margin: 0 -40px; padding: 15px 40px; }}
        
        .row-content {{
            display: flex;
            gap: 15px;
            overflow-x: auto;
            padding-bottom: 10px;
            scroll-snap-type: x mandatory;
        }}
        
        .row-content::-webkit-scrollbar {{
            height: 6px;
        }}
        
        .row-content::-webkit-scrollbar-track {{
            background: rgba(255,255,255,0.05);
            border-radius: 3px;
        }}
        
        .row-content::-webkit-scrollbar-thumb {{
            background: rgba(255,255,255,0.2);
            border-radius: 3px;
        }}
        
        .row-content::-webkit-scrollbar-thumb:hover {{
            background: rgba(255,255,255,0.3);
        }}
        
        .project-card {{
            background: rgba(255,255,255,0.08);
            border-radius: 10px;
            overflow: hidden;
            transition: all 0.2s ease;
            display: flex;
            flex-direction: column;
            cursor: pointer;
            position: relative;
            border: 1px solid rgba(255,255,255,0.08);
            flex-shrink: 0;
            width: 180px;
            scroll-snap-align: start;
        }}
        
        .project-card:hover {{
            transform: scale(1.05);
            background: rgba(255,255,255,0.12);
            border-color: rgba(102,126,234,0.4);
            z-index: 10;
        }}
        
        .project-card.pinned {{ border-color: rgba(255,193,7,0.4); }}
        
        .project-card.compact {{
            flex-direction: row;
            height: 65px;
        }}
        
        .project-card.compact .screenshot-container {{
            width: 85px;
            height: 65px;
            flex-shrink: 0;
        }}
        
        .project-card.compact .project-info {{
            padding: 6px 10px;
            justify-content: center;
        }}
        
        .project-card.compact .project-info h3 {{
            font-size: 12px;
            margin-bottom: 2px;
        }}
        
        .project-card.compact .one-liner {{
            font-size: 10px;
            -webkit-line-clamp: 2;
        }}
        
        .project-card.compact .pin-btn {{
            padding: 3px;
            font-size: 11px;
            width: 22px;
            height: 22px;
        }}
        
        .screenshot-container {{
            width: 100%;
            height: 220px;
            background: rgba(0,0,0,0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }}
        
        .screenshot {{ width: 100%; height: 100%; object-fit: cover; }}
        .no-screenshot {{ font-size: 40px; opacity: 0.3; }}
        
        .badges {{
            position: absolute;
            top: 4px;
            left: 4px;
            display: flex;
            gap: 3px;
        }}
        
        .badge {{
            background: rgba(0,0,0,0.6);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 9px;
            font-weight: 500;
        }}
        
        /* Category badge colors matching headers */
        .badge.cat-pinned {{ background: rgba(214,158,46,0.9); color: #744210; }}
        .badge.cat-recent {{ background: rgba(49,151,149,0.9); }}
        .badge.cat-research {{ background: rgba(102,126,234,0.85); }}
        .badge.cat-teaching {{ background: rgba(72,187,120,0.85); }}
        .badge.cat-tools {{ background: rgba(237,137,54,0.85); }}
        .badge.cat-puzzles {{ background: rgba(159,122,234,0.85); }}
        .badge.cat-hardware {{ background: rgba(229,62,62,0.85); }}
        .badge.cat-other {{ background: rgba(113,128,150,0.85); }}
        .badge.cat-home {{ background: rgba(56,178,172,0.85); }}
        .badge.server {{ background: rgba(76,175,80,0.9); color: #fff; font-weight: 700; }}
        
        /* Run / Open-both action buttons (bottom of screenshot, reveal on hover) */
        .card-actions {{
            position: absolute;
            bottom: 6px;
            left: 6px;
            right: 6px;
            display: flex;
            gap: 6px;
            opacity: 0;
            transform: translateY(6px);
            transition: opacity 0.2s, transform 0.2s;
        }}
        
        .project-card:hover .card-actions {{ opacity: 1; transform: translateY(0); }}
        
        .action-btn {{
            border: none;
            border-radius: 6px;
            padding: 5px 8px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            color: #fff;
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .action-btn.run-btn {{ background: rgba(76,175,80,0.92); flex: 1; }}
        .action-btn.run-btn:hover {{ background: rgba(76,175,80,1); }}
        .action-btn.both-btn {{ background: rgba(102,126,234,0.92); }}
        .action-btn.both-btn:hover {{ background: rgba(102,126,234,1); }}
        .action-btn:active {{ transform: scale(0.95); }}
        
        .project-info {{
            padding: 10px;
            flex-grow: 1;
            display: flex;
            flex-direction: column;
        }}
        
        .project-info h3 {{
            font-size: 13px;
            margin-bottom: 4px;
            color: #fff;
            line-height: 1.2;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        
        .one-liner {{
            font-size: 11px;
            color: rgba(255,255,255,0.5);
            margin-bottom: 0;
            flex-grow: 1;
            line-height: 1.3;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}
        
        .project-path {{
            display: none;
        }}
        
        .tags {{ display: none; }}
        
        .pin-btn {{
            position: absolute;
            top: 6px;
            right: 6px;
            background: rgba(0,0,0,0.5);
            border: none;
            border-radius: 50%;
            width: 26px;
            height: 26px;
            cursor: pointer;
            opacity: 0;
            transition: opacity 0.2s, transform 0.2s;
            font-size: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        
        .project-card:hover .pin-btn {{ opacity: 1; }}
        .pin-btn:hover {{ transform: scale(1.1); }}
        .pin-btn.pinned {{ opacity: 1; background: rgba(255,193,7,0.3); }}
        
        footer {{
            text-align: center;
            padding: 25px;
            opacity: 0.4;
            font-size: 11px;
        }}
        
        .notification {{
            position: fixed;
            top: 15px;
            right: 15px;
            padding: 10px 16px;
            border-radius: 6px;
            color: white;
            font-size: 13px;
            z-index: 1000;
            animation: slideIn 0.3s ease;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        
        .notification.success {{ background: #4caf50; }}
        .notification.error {{ background: #f44336; }}
        .notification.info {{ background: #2196f3; }}
        
        /* Home folder osx toggle */
        #homeFoldersContent .project-card[data-osx="true"] {{
            display: none;
        }}
        #homeFoldersContent .project-card[data-osx="true"].visible {{
            display: flex;
        }}

        /* Toggle switch */
        .toggle-label {{
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            margin-left: auto;
            font-size: 12px;
            user-select: none;
        }}
        .toggle-label input {{ display: none; }}
        .toggle-switch {{
            width: 34px;
            height: 18px;
            background: rgba(255,255,255,0.15);
            border-radius: 9px;
            position: relative;
            transition: background 0.2s;
        }}
        .toggle-switch::after {{
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 14px;
            height: 14px;
            background: rgba(255,255,255,0.6);
            border-radius: 50%;
            transition: transform 0.2s;
        }}
        .toggle-label input:checked + .toggle-switch {{
            background: rgba(56,178,172,0.6);
        }}
        .toggle-label input:checked + .toggle-switch::after {{
            transform: translateX(16px);
            background: #fff;
        }}
        .toggle-text {{ color: rgba(255,255,255,0.6); }}

        @keyframes slideIn {{
            from {{ transform: translateX(100px); opacity: 0; }}
            to {{ transform: translateX(0); opacity: 1; }}
        }}

        /* ============================================================== */
        /* Modern, high-contrast, neutral theme (overrides + new views)   */
        /* ============================================================== */
        :root {{
            --bg:#0a0a0b;
            --bg-grad: radial-gradient(1100px 560px at 72% -12%, #16161b 0%, #0a0a0b 62%);
            --surface:#151518;
            --surface-2:#1c1c20;
            --surface-3:#26262c;
            --border:#2a2a31;
            --border-strong:#3b3b44;
            --text:#f5f5f6;
            --text-dim:#b6b6bf;
            --text-faint:#7c7c87;
            --accent:#6ea8fe;
            --accent-2:#9b8cff;
            --green:#3ecf8e;
            --green-strong:#33bd80;
            --radius:12px;
            --shadow:0 10px 32px rgba(0,0,0,.5);
            --c-research:#7c9cff; --c-teaching:#5ec98b; --c-tools:#e0a35e;
            --c-puzzles:#b48ef0; --c-hardware:#ef6e6e; --c-other:#9aa0aa;
            --c-home:#5ec9c0; --c-pinned:#e6c45e; --c-recent:#6cc6d6;
            --c-github:#b3b9c4;
        }}

        body {{
            font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',Roboto,sans-serif;
            background:var(--bg); background-image:var(--bg-grad);
            background-attachment:fixed; color:var(--text);
            -webkit-font-smoothing:antialiased;
        }}

        .main-content {{ padding:24px clamp(16px,4vw,48px); max-width:1640px; margin:0 auto; }}

        header {{ display:flex; flex-direction:column; gap:14px; margin-bottom:22px; text-align:left; }}
        .header-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
        header h1 {{
            font-size:22px; font-weight:700; letter-spacing:-.01em; margin:0 0 4px 0;
            background:none; -webkit-text-fill-color:currentColor; color:var(--text);
            display:flex; align-items:center; gap:10px;
        }}
        header h1 .logo-dot {{ width:11px; height:11px; border-radius:3px;
            background:linear-gradient(135deg,var(--accent),var(--accent-2)); }}
        .subtitle {{ font-size:12.5px; color:var(--text-faint); }}

        .stats {{ margin-top:0; }}
        .stat {{ background:var(--surface); border:1px solid var(--border); color:var(--text-dim);
            padding:6px 12px; border-radius:999px; font-size:12px; }}

        .controls {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
        .search-box {{ flex:1; min-width:220px; max-width:none; margin:0; }}
        .search-box input {{
            padding:11px 16px; font-size:14px; border-radius:10px;
            background:var(--surface); border:1px solid var(--border); color:var(--text);
            transition:border-color .15s, box-shadow .15s;
        }}
        .search-box input::placeholder {{ color:var(--text-faint); }}
        .search-box input:focus {{ background:var(--surface); border-color:var(--accent);
            box-shadow:0 0 0 3px rgba(110,168,254,.18); }}

        .view-switcher {{ display:flex; background:var(--surface); border:1px solid var(--border);
            border-radius:10px; padding:3px; gap:2px; }}
        .view-btn {{ border:none; background:transparent; color:var(--text-dim); cursor:pointer;
            padding:7px 13px; border-radius:7px; font-size:13px; font-weight:600;
            display:flex; align-items:center; gap:6px; transition:background .15s,color .15s; }}
        .view-btn:hover {{ color:var(--text); }}
        .view-btn.active {{ background:var(--surface-3); color:var(--text); }}

        .view {{ animation:fadeView .2s ease; }}
        @keyframes fadeView {{ from {{ opacity:0; transform:translateY(4px); }} to {{ opacity:1; transform:none; }} }}
        .search-hidden {{ display:none !important; }}

        /* Chips (neutral with a small category-colored dot) */
        .chip {{ display:inline-flex; align-items:center; gap:6px; background:var(--surface-2);
            border:1px solid var(--border); color:var(--text-dim); padding:3px 9px;
            border-radius:999px; font-size:11px; font-weight:600; text-transform:uppercase;
            letter-spacing:.04em; white-space:nowrap; }}
        .chip::before {{ content:''; width:6px; height:6px; border-radius:50%; background:var(--c-other); }}
        .chip-research::before{{background:var(--c-research);}} .chip-teaching::before{{background:var(--c-teaching);}}
        .chip-tools::before{{background:var(--c-tools);}} .chip-puzzles::before{{background:var(--c-puzzles);}}
        .chip-hardware::before{{background:var(--c-hardware);}} .chip-other::before{{background:var(--c-other);}}
        .chip-home::before{{background:var(--c-home);}} .chip-pinned::before{{background:var(--c-pinned);}}
        .chip-recent::before{{background:var(--c-recent);}} .chip-github::before{{background:var(--c-github);}}
        .chip-group::before{{background:#667eea;}}
        .group-pick {{
            max-width: 160px; background:var(--surface); color:var(--text);
            border:1px solid var(--border); border-radius:8px; padding:4px 6px;
            font-size:12px; cursor:pointer; outline:none;
        }}
        .group-pick:focus {{ border-color:var(--accent); }}
        .cat-github{{--dot:var(--c-github);background:none;color:var(--text);}}
        .badge.cat-github {{ background:rgba(0,0,0,.6); color:var(--text); }}

        /* GitHub (not-cloned) cards */
        .github-card {{ border-style:dashed; border-color:var(--border-strong); }}
        .github-card .screenshot-container {{ background:var(--surface-2); }}
        .github-card:hover {{ border-style:solid; }}
        .git-pill.cloud {{ color:var(--text); background:var(--surface-3); }}
        .action-btn.clone-btn {{ background:var(--accent); color:#0a0a0b; flex:1; }}
        .action-btn.clone-btn:hover {{ filter:brightness(1.08); }}
        .newproj-btn {{ background:var(--accent); color:#0a0a0b; border-color:var(--accent); }}
        .newproj-btn:hover {{ filter:brightness(1.08); color:#0a0a0b; }}
        .gh-tag {{ font-size:10px; color:var(--text-faint); }}
        .github-row td {{ opacity:.92; }}

        /* Grid view neutralization */
        .categories-container {{ gap:22px; }}
        .category-row.row-even, .category-row.row-odd,
        .category-row.row-pinned, .category-row.row-recent, .row-home {{
            margin:0 !important; padding:0 !important; background:transparent !important;
        }}
        .row-header h2 {{ font-size:13px; font-weight:700; text-transform:uppercase;
            letter-spacing:.06em; color:var(--text); padding:0; background:none !important;
            display:flex; align-items:center; gap:8px; }}
        .row-header h2::before {{ content:''; width:8px; height:8px; border-radius:3px;
            background:var(--dot,var(--c-other)); }}
        .cat-pinned{{--dot:var(--c-pinned);background:none;color:var(--text);}}
        .cat-recent{{--dot:var(--c-recent);background:none;color:var(--text);}}
        .cat-research{{--dot:var(--c-research);background:none;color:var(--text);}}
        .cat-teaching{{--dot:var(--c-teaching);background:none;color:var(--text);}}
        .cat-tools{{--dot:var(--c-tools);background:none;color:var(--text);}}
        .cat-puzzles{{--dot:var(--c-puzzles);background:none;color:var(--text);}}
        .cat-hardware{{--dot:var(--c-hardware);background:none;color:var(--text);}}
        .cat-other{{--dot:var(--c-other);background:none;color:var(--text);}}
        .cat-home{{--dot:var(--c-home);background:none;color:var(--text);}}
        .row-handle {{ color:var(--text-faint); }}
        .row-handle:hover {{ color:var(--text); }}
        .rows-hint {{ color:var(--text-faint); }}
        .rows-hint a {{ color:var(--accent); }}
        .row-header .count {{ background:var(--surface); border:1px solid var(--border);
            color:var(--text-faint); padding:3px 10px; }}

        .row-content {{ gap:14px; }}
        .row-content::-webkit-scrollbar {{ height:8px; }}
        .row-content::-webkit-scrollbar-track {{ background:transparent; }}
        .row-content::-webkit-scrollbar-thumb {{ background:var(--border-strong); border-radius:4px; }}
        .row-content::-webkit-scrollbar-thumb:hover {{ background:var(--text-faint); }}

        .project-card {{ background:var(--surface); border:1px solid var(--border);
            border-radius:var(--radius); width:200px;
            transition:transform .18s ease,border-color .18s ease,background .18s ease; }}
        .project-card:hover {{ transform:translateY(-3px); background:var(--surface-2);
            border-color:var(--border-strong); box-shadow:var(--shadow); }}
        .screenshot-container {{ height:120px; background:var(--surface-3); }}
        .no-screenshot {{ opacity:.25; }}

        .badge {{ background:rgba(0,0,0,.6); border:1px solid var(--border); color:var(--text-dim);
            border-radius:6px; padding:2px 7px; backdrop-filter:blur(6px); }}
        .badge.cat-pinned,.badge.cat-recent,.badge.cat-research,.badge.cat-teaching,
        .badge.cat-tools,.badge.cat-puzzles,.badge.cat-hardware,.badge.cat-other,.badge.cat-home {{
            background:rgba(0,0,0,.6); color:var(--text); }}
        .badge.server {{ color:var(--green);
            background:color-mix(in srgb,var(--green) 20%, #000);
            border-color:color-mix(in srgb,var(--green) 40%, transparent); }}

        .action-btn {{ border:1px solid transparent; border-radius:8px; color:#0a0a0b; }}
        .action-btn.run-btn {{ background:var(--green); }}
        .action-btn.run-btn:hover {{ background:var(--green-strong); }}
        .action-btn.both-btn {{ background:var(--surface-3); color:var(--text); border-color:var(--border-strong); }}
        .action-btn.both-btn:hover {{ background:var(--border-strong); }}
        .action-btn.gen-btn {{ background:var(--accent-2); color:#0a0a0b; }}
        .action-btn.gen-btn:hover {{ filter:brightness(1.1); }}

        .project-info h3 {{ font-weight:600; color:var(--text); -webkit-line-clamp:1; }}
        .one-liner {{ color:var(--text-faint); }}
        .pin-btn {{ background:rgba(0,0,0,.6); border:1px solid var(--border); }}
        .pin-btn.pinned {{ background:color-mix(in srgb,var(--c-pinned) 28%, #000); }}

        /* Feed view */
        .feed-container {{ display:flex; flex-direction:column; gap:14px; max-width:780px; margin:0 auto; }}
        .feed-card {{ display:flex; gap:16px; background:var(--surface); border:1px solid var(--border);
            border-radius:14px; padding:14px; transition:border-color .18s,background .18s; }}
        .feed-card:hover {{ border-color:var(--border-strong); background:var(--surface-2); }}
        .feed-thumb {{ flex:0 0 45%; width:45%; aspect-ratio:16/10; align-self:stretch; min-height:170px;
            border-radius:10px; overflow:hidden;
            background:var(--surface-3); display:flex; align-items:center; justify-content:center; cursor:pointer; }}
        .feed-screenshot {{ width:100%; height:100%; object-fit:cover; }}
        .feed-body {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:8px; }}
        .feed-head {{ display:flex; align-items:center; gap:10px; }}
        .feed-head h3 {{ font-size:16px; font-weight:700; color:var(--text); cursor:pointer; margin:0; }}
        .feed-head h3:hover {{ color:var(--accent); }}
        .feed-desc {{ font-size:13.5px; color:var(--text-dim); line-height:1.5; }}
        .feed-commit {{ display:flex; align-items:center; gap:8px; font-size:12.5px; color:var(--text-dim);
            background:var(--surface-2); border:1px solid var(--border); border-radius:8px; padding:6px 10px; }}
        .feed-commit .commit-label {{ text-transform:uppercase; font-size:10px; letter-spacing:.05em;
            color:var(--text-faint); border-right:1px solid var(--border); padding-right:8px; }}
        .feed-commit .commit-subject {{ flex:1; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; color:var(--text); }}
        .feed-commit .commit-date {{ color:var(--text-faint); white-space:nowrap; }}
        .feed-changes {{ font-size:12.5px; color:var(--text-dim); }}
        .feed-changes summary {{ cursor:pointer; color:var(--text-faint); user-select:none; }}
        .feed-changes ul {{ margin:6px 0 0 18px; color:var(--text-dim); }}
        .feed-changes li {{ margin:2px 0; }}
        .feed-tags {{ display:flex; gap:6px; flex-wrap:wrap; }}
        .feed-tags .tag {{ display:inline-block; font-size:11px; color:var(--text-faint);
            background:var(--surface-2); border:1px solid var(--border); padding:2px 8px; border-radius:999px; }}
        .feed-actions {{ display:flex; align-items:center; gap:8px; margin-top:2px; flex-wrap:wrap; }}
        .feed-actions .action-btn {{ flex:0 0 auto; }}
        .feed-actions .open-btn {{ background:var(--surface-3); color:var(--text); border:1px solid var(--border-strong); }}
        .feed-actions .open-btn:hover {{ background:var(--border-strong); }}
        .feed-path {{ margin-left:auto; font-size:11px; color:var(--text-faint);
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}

        /* Table view */
        .table-container {{ overflow-x:auto; border:1px solid var(--border); border-radius:12px;
            background:var(--surface); }}
        .data-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        .data-table thead th {{ position:sticky; top:0; background:var(--surface-2); color:var(--text-dim);
            text-align:left; font-weight:600; padding:11px 14px; border-bottom:1px solid var(--border);
            white-space:nowrap; user-select:none; }}
        .data-table th.sortable-th {{ cursor:pointer; }}
        .data-table th.sortable-th:hover {{ color:var(--text); }}
        .data-table th.sort-asc::after {{ content:' ↑'; color:var(--accent); }}
        .data-table th.sort-desc::after {{ content:' ↓'; color:var(--accent); }}
        .data-table tbody td {{ padding:10px 14px; border-bottom:1px solid var(--border); color:var(--text-dim); }}
        .data-table tbody tr {{ cursor:pointer; transition:background .12s; }}
        .data-table tbody tr:hover {{ background:var(--surface-2); }}
        .data-table tbody tr:last-child td {{ border-bottom:none; }}
        .td-title {{ color:var(--text); font-weight:600; white-space:nowrap; }}
        .td-desc {{ color:var(--text-faint); max-width:340px; overflow:hidden;
            text-overflow:ellipsis; white-space:nowrap; }}
        .td-run {{ text-align:center; }}
        .tbl-run {{ padding:4px 9px; font-size:12px; flex:0 0 auto; }}

        footer {{ color:var(--text-faint); opacity:1; }}

        .notification {{ background:var(--surface-2); border:1px solid var(--border-strong); color:var(--text); }}
        .notification.success {{ background:var(--surface-2); border-color:color-mix(in srgb,var(--green) 50%, transparent); }}
        .notification.error {{ background:var(--surface-2); border-color:#ef6e6e; }}
        .notification.info {{ background:var(--surface-2); border-color:var(--accent); }}

        .toggle-switch {{ background:var(--surface-3); }}
        .toggle-label input:checked + .toggle-switch {{ background:var(--accent); }}
        .toggle-text {{ color:var(--text-faint); }}

        /* ===== Single wrapping grid + toolbar (Grid view) ===== */
        .grid-toolbar {{ display:flex; align-items:center; justify-content:space-between;
            gap:14px; flex-wrap:wrap; margin-bottom:18px; }}
        .filters-bar {{ display:flex; flex-direction:column; gap:10px; margin-bottom:16px; }}
        .filter-row {{ display:flex; align-items:flex-start; gap:10px; flex-wrap:wrap; }}
        .filter-row-label {{ font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase;
            opacity:.45; padding-top:8px; min-width:64px; }}
        .filter-chips {{ display:flex; gap:8px; flex-wrap:wrap; }}
        .fchip {{ border:1px solid var(--border); background:var(--surface); color:var(--text-dim);
            padding:6px 12px; border-radius:999px; font-size:12.5px; font-weight:600; cursor:pointer;
            display:inline-flex; align-items:center; gap:6px; transition:all .15s; }}
        .fchip:hover {{ color:var(--text); border-color:var(--border-strong); }}
        .fchip.active {{ background:var(--text); color:#0a0a0b; border-color:var(--text); }}
        .fchip-count {{ font-size:10.5px; opacity:.65; }}
        .sort-control {{ display:flex; align-items:center; gap:8px; color:var(--text-faint); font-size:12.5px; }}
        .sort-control select {{ background:var(--surface); border:1px solid var(--border); color:var(--text);
            border-radius:8px; padding:7px 10px; font-size:13px; cursor:pointer; outline:none; }}
        .sort-control select:focus {{ border-color:var(--accent); }}

        .card-grid {{ display:flex; flex-wrap:wrap; gap:14px; align-items:flex-start; }}
        .card-grid .project-card {{ width:210px; }}
        .filter-hidden {{ display:none !important; }}

        /* ===== Git status pills ===== */
        .gitline {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }}
        .git-pill {{ font-size:10px; font-weight:600; padding:2px 6px; border-radius:5px;
            background:var(--surface-3); color:var(--text-dim); border:1px solid var(--border);
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace; white-space:nowrap; }}
        .git-pill.branch {{ color:var(--text); }}
        .git-pill.ahead {{ color:#7dd3a8; border-color:rgba(62,207,142,.35); }}
        .git-pill.behind {{ color:#e0a35e; border-color:rgba(224,163,94,.35); }}
        .git-pill.dirty {{ color:#efb06e; border-color:rgba(224,163,94,.4); }}
        .git-pill.clean {{ color:var(--green); }}
        .git-pill.pub {{ color:#7dd3a8; }}
        .git-pill.priv {{ color:#e6c45e; }}
        .git-pill.no-remote, .git-pill.files {{ color:var(--text-faint); }}
        .git-pill.date {{ color:var(--text-faint); }}
        .gitline.not-repo {{ opacity:.85; }}

        /* Manage button (top-right, beside pin) */
        .manage-btn {{ position:absolute; top:6px; right:36px; background:rgba(0,0,0,.6);
            border:1px solid var(--border); border-radius:50%; width:26px; height:26px; cursor:pointer;
            opacity:0; transition:opacity .18s,transform .18s; font-size:12px; color:var(--text-dim);
            display:flex; align-items:center; justify-content:center; }}
        .project-card:hover .manage-btn {{ opacity:1; }}
        .manage-btn:hover {{ transform:scale(1.12); color:var(--text); }}
        .action-btn.manage-inline {{ background:var(--surface-3); color:var(--text); border:1px solid var(--border-strong); }}
        .action-btn.manage-inline:hover {{ background:var(--border-strong); }}

        /* Feed branches + table mono */
        .feed-branches {{ font-size:12px; color:var(--text-dim); }}
        .feed-branches summary {{ cursor:pointer; color:var(--text-faint); }}
        .feed-branches ul {{ margin:6px 0 0 18px; }}
        .feed-branches li {{ margin:2px 0; }}
        .feed-branches .b-sync {{ color:var(--text-faint); font-family:ui-monospace,Menlo,monospace; }}
        .feed-branches .b-gone {{ color:#e0a35e; }} .feed-branches .b-ok {{ color:var(--green); }}
        .feed-branches .b-noup {{ color:var(--text-faint); }}
        .td-mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}

        /* ===== Manage modal ===== */
        .modal-overlay {{ position:fixed; inset:0; background:rgba(0,0,0,.6); backdrop-filter:blur(3px);
            display:none; align-items:center; justify-content:center; z-index:2000; padding:20px; }}
        .modal-overlay.open {{ display:flex; }}
        .modal {{ background:var(--surface); border:1px solid var(--border-strong); border-radius:16px;
            width:min(720px,100%); max-height:88vh; overflow:auto; box-shadow:var(--shadow); }}
        .modal-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px;
            padding:18px 22px; border-bottom:1px solid var(--border); position:sticky; top:0;
            background:var(--surface); z-index:1; }}
        .modal-head h2 {{ font-size:17px; font-weight:700; color:var(--text); margin:0; }}
        .modal-head .modal-sub {{ font-size:12px; color:var(--text-faint);
            font-family:ui-monospace,Menlo,monospace; }}
        .modal-close {{ background:var(--surface-3); border:1px solid var(--border); color:var(--text);
            width:30px; height:30px; border-radius:8px; cursor:pointer; font-size:16px; }}
        .modal-close:hover {{ background:var(--border-strong); }}
        .modal-body {{ padding:18px 22px; display:flex; flex-direction:column; gap:18px; }}
        .modal-section {{ display:flex; flex-direction:column; gap:10px; }}
        .modal-section h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:.05em;
            color:var(--text-faint); font-weight:700; margin:0; }}
        .quick-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
        .qbtn {{ border:1px solid var(--border-strong); background:var(--surface-2); color:var(--text);
            padding:8px 13px; border-radius:9px; font-size:13px; font-weight:600; cursor:pointer;
            display:inline-flex; align-items:center; gap:7px; }}
        .qbtn:hover {{ background:var(--surface-3); }}
        .qbtn.primary {{ background:var(--green); color:#0a0a0b; border-color:var(--green); }}
        .qbtn.primary:hover {{ background:var(--green-strong); }}
        .qbtn.accent {{ background:var(--accent); color:#0a0a0b; border-color:var(--accent); }}
        .form-grid {{ display:grid; grid-template-columns:120px 1fr; gap:10px 14px; align-items:center; }}
        .form-grid label {{ font-size:13px; color:var(--text-dim); }}
        .form-grid input, .form-grid select, .form-grid textarea {{
            background:var(--surface-2); border:1px solid var(--border); color:var(--text);
            border-radius:8px; padding:8px 10px; font-size:13px; outline:none; width:100%;
            font-family:inherit; }}
        .form-grid input:focus, .form-grid select:focus, .form-grid textarea:focus {{ border-color:var(--accent); }}
        .form-grid textarea {{ resize:vertical; min-height:48px; }}
        .form-row-full {{ grid-column:1 / -1; }}
        .modal-hint {{ font-size:11.5px; color:var(--text-faint); }}
        .screenshot-preview {{ max-width:100%; border-radius:10px; border:1px solid var(--border); margin-top:8px; }}
        .modal-md-list {{ display:flex; gap:8px; flex-wrap:wrap; }}
        .modal-md-list .qbtn {{ font-weight:500; font-size:12px; padding:6px 10px; }}

        /* ===== Port pills + Ports overview ===== */
        .port-pill {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:10px;
            font-weight:700; padding:2px 6px; border-radius:5px; background:rgba(0,0,0,.6);
            border:1px solid var(--border); color:var(--text-dim); white-space:nowrap; }}
        .port-pill.designated {{ color:var(--accent); border-color:rgba(110,168,254,.4); }}
        .port-pill.auto {{ color:var(--text-faint); }}
        .port-pill.conflict {{ color:#0a0a0b; background:#ef6e6e; border-color:#ef6e6e; }}
        .port-pill.running {{ color:#0a0a0b; background:var(--green); border-color:var(--green); }}
        .feed-head .port-pill {{ margin-left:auto; }}
        .td-port .port-pill {{ background:var(--surface-2); }}

        /* ===== Shutdown + legend buttons ===== */
        .shutdown-btn {{ border:1px solid var(--border); background:var(--surface); color:var(--text-faint);
            border-radius:10px; padding:7px 12px; font-size:12.5px; font-weight:600; cursor:pointer; }}
        .shutdown-btn:hover {{ border-color:#ef6e6e; color:#ef6e6e; }}
        .legend-btn {{ border:1px solid var(--border); background:var(--surface); color:var(--text-dim);
            border-radius:10px; padding:9px 13px; font-size:13px; font-weight:600; cursor:pointer; }}
        .legend-btn:hover {{ color:var(--text); border-color:var(--border-strong); }}

        /* ===== Live servers bar ===== */
        .live-bar {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap;
            background:color-mix(in srgb,var(--green) 12%, var(--surface));
            border:1px solid color-mix(in srgb,var(--green) 35%, transparent);
            border-radius:10px; padding:10px 16px; margin-bottom:16px; }}
        .live-bar-label {{ font-size:12px; font-weight:700; color:var(--green); text-transform:uppercase;
            letter-spacing:.05em; white-space:nowrap; }}
        .live-bar-items {{ display:flex; gap:8px; flex-wrap:wrap; flex:1; }}
        .live-server-chip {{ display:inline-flex; align-items:center; gap:8px;
            background:rgba(0,0,0,.35); border:1px solid color-mix(in srgb,var(--green) 30%, transparent);
            border-radius:8px; padding:5px 10px; font-size:13px; color:var(--text); }}
        .live-server-chip a {{ color:var(--green); text-decoration:none; font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
        .live-server-chip a:hover {{ text-decoration:underline; }}
        .live-server-stop {{ border:none; background:none; color:var(--text-faint); cursor:pointer;
            font-size:14px; padding:0 2px; line-height:1; }}
        .live-server-stop:hover {{ color:#ef6e6e; }}
        .live-bar-stopall {{ border:1px solid color-mix(in srgb,#ef6e6e 50%, transparent);
            background:rgba(239,110,110,.12); color:#ef6e6e; border-radius:8px;
            padding:5px 12px; font-size:12px; font-weight:600; cursor:pointer; white-space:nowrap; }}
        .live-bar-stopall:hover {{ background:rgba(239,110,110,.25); }}

        /* ===== Legend panel ===== */
        .legend-panel {{ background:var(--surface); border:1px solid var(--border); border-radius:14px;
            padding:20px 22px; margin-bottom:18px; position:relative; }}
        .legend-close {{ position:absolute; top:12px; right:14px; cursor:pointer; font-size:18px;
            color:var(--text-faint); width:28px; height:28px; display:flex; align-items:center;
            justify-content:center; border-radius:6px; }}
        .legend-close:hover {{ background:var(--surface-3); color:var(--text); }}
        .legend-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:22px; }}
        .legend-section {{ display:flex; flex-direction:column; gap:7px; }}
        .legend-title {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
            color:var(--text-faint); margin-bottom:4px; }}
        .legend-row {{ display:flex; align-items:center; gap:8px; font-size:12.5px; color:var(--text-dim); }}
        .legend-row span {{ flex-shrink:0; }}
        .legend-row b {{ color:var(--text); }}

        .port-overview-btn {{ border:1px solid var(--border); background:var(--surface); color:var(--text-dim);
            border-radius:10px; padding:9px 13px; font-size:13px; font-weight:600; cursor:pointer;
            display:inline-flex; align-items:center; gap:6px; text-decoration:none; }}
        .port-overview-btn:hover {{ color:var(--text); border-color:var(--border-strong); }}
        .port-overview-btn .badge-dot {{ width:8px; height:8px; border-radius:50%; background:var(--green); display:none; }}
        .port-overview-btn.has-conflict {{ border-color:#ef6e6e; color:#ef6e6e; }}

        .ports-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        .ports-table th {{ text-align:left; color:var(--text-faint); font-weight:600; font-size:11px;
            text-transform:uppercase; letter-spacing:.04em; padding:8px 10px; border-bottom:1px solid var(--border); }}
        .ports-table td {{ padding:9px 10px; border-bottom:1px solid var(--border); color:var(--text-dim); vertical-align:top; }}
        .ports-table tr:last-child td {{ border-bottom:none; }}
        .ports-table .p-num {{ font-family:ui-monospace,Menlo,monospace; font-weight:700; color:var(--text); }}
        .ports-table .p-proj {{ color:var(--text); }}
        .ports-table .p-proj .muted {{ color:var(--text-faint); }}
        .p-state {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:999px; }}
        .p-state.listening {{ color:#0a0a0b; background:var(--green); }}
        .p-state.free {{ color:var(--text-faint); background:var(--surface-3); }}
        .p-conflict {{ color:#ef6e6e; font-weight:700; font-size:11px; }}
        .ports-row.is-conflict td {{ background:rgba(239,110,110,.08); }}
        .p-stop {{ border:1px solid var(--border-strong); background:var(--surface-2); color:var(--text);
            padding:4px 10px; border-radius:7px; font-size:12px; cursor:pointer; }}
        .p-stop:hover {{ background:var(--border-strong); }}
        .port-status-line {{ font-size:12px; color:var(--text-faint); margin-top:4px; }}

        /* Catalogue / Screenshot presence cells */
        .td-has {{ text-align:center; }}
        .has-yes {{ color:var(--green); font-weight:700; }}
        .has-no {{ color:var(--text-faint); }}
        .mini-gen {{ border:1px solid var(--border-strong); background:var(--surface-2); color:var(--text);
            border-radius:6px; padding:2px 8px; font-size:12px; cursor:pointer; }}
        .mini-gen:hover {{ background:var(--accent); color:#0a0a0b; border-color:var(--accent); }}
        .qbtn.gen {{ background:var(--accent-2); color:#0a0a0b; border-color:var(--accent-2); }}
        .qbtn.gen:hover {{ filter:brightness(1.1); }}
        .qbtn:disabled {{ opacity:.55; cursor:wait; }}
        .action-btn.pub-btn {{ background:#7c6af7; color:#fff; }}
        .action-btn.pub-btn:hover {{ filter:brightness(1.1); }}
        .publish-row {{ display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
        .publish-name-row {{ display:grid; grid-template-columns:140px 1fr; gap:10px 14px; align-items:center; }}
        .publish-name-row label {{ font-size:13px; color:var(--text-dim); }}
        .publish-name-row input {{
            background:var(--surface-2); border:1px solid var(--border); color:var(--text);
            border-radius:8px; padding:8px 10px; font-size:13px; outline:none; width:100%;
            font-family:ui-monospace,Menlo,monospace; }}
        .publish-name-row input:focus {{ border-color:var(--accent); }}
        .publish-name-row input:disabled {{ opacity:.6; }}
        .publish-choice {{ display:inline-flex; align-items:center; gap:6px; font-size:13px; color:var(--text-dim); cursor:pointer; }}
        .publish-choice input {{ width:auto; accent-color:var(--accent); }}
        .publish-log {{ margin:4px 0 0; padding-left:18px; font-size:12px; color:var(--text-dim); }}
        .publish-log .ok {{ color:var(--green); }}
        .publish-log .skip {{ color:var(--text-faint); }}
        .publish-log .err {{ color:#ef6e6e; }}
        .commit-opts {{ display:flex; flex-direction:column; gap:8px; }}
        .commit-files-head {{ display:flex; justify-content:space-between; align-items:center;
            font-size:12px; color:var(--text-faint); margin-top:4px; }}
        .commit-files {{ max-height:180px; overflow:auto; border:1px solid var(--border);
            border-radius:8px; padding:6px 8px; background:var(--surface-2); }}
        .commit-file {{ display:flex; align-items:center; gap:8px; font-size:12px;
            font-family:ui-monospace,Menlo,monospace; color:var(--text-dim); padding:3px 0; }}
        .commit-file input {{ width:auto; }}
        .commit-xy {{ width:2.2em; font-weight:700; color:var(--accent); flex-shrink:0; }}
        .commit-xy.untracked {{ color:var(--green); }}
        .action-btn.sync-btn {{ background:#3d8b6e; color:#fff; }}
        .action-btn.sync-btn:hover {{ filter:brightness(1.1); }}
    </style>
</head>
<body>
    <div class="main-layout">
        <main class="main-content">
            <header>
                <div class="header-top">
                    <div>
                        <h1><span class="logo-dot"></span> {header_heading}</h1>
                    </div>
                    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
                        {header_right}
                    </div>
                </div>
                <div class="controls">
                    <div class="search-box">
                        <input type="text" id="searchInput" placeholder="Search projects…" onkeyup="filterProjects()">
                    </div>
                    <div class="view-switcher">
                        {rows_view_btn}
                        <button class="view-btn" data-view="grid" onclick="switchView('grid')">▦ Grid</button>
                        <button class="view-btn" data-view="feed" onclick="switchView('feed')">☰ Feed</button>
                        <button class="view-btn" data-view="table" onclick="switchView('table')">▤ Table</button>
                    </div>
                    {extra_controls}
                </div>
            </header>

            <!-- Live servers bar: hidden when nothing is running -->
            <div id="liveBar" class="live-bar" style="display:none">
                <span class="live-bar-label">▶ Running</span>
                <div class="live-bar-items" id="liveBarItems"></div>
                <button class="live-bar-stopall" onclick="stopAllServers()">Stop all</button>
            </div>

            <!-- Legend -->
            <div id="legendPanel" class="legend-panel" style="display:none">
                <div class="legend-close" onclick="toggleLegend()">×</div>
                <div class="legend-grid">
                    <div class="legend-section">
                        <div class="legend-title">Git status (on every card)</div>
                        <div class="legend-row"><span class="git-pill branch">⎇ main</span> Current branch name</div>
                        <div class="legend-row"><span class="git-pill ahead">↑2</span> Commits ahead of remote (unpushed)</div>
                        <div class="legend-row"><span class="git-pill behind">↓1</span> Commits behind remote (need pull)</div>
                        <div class="legend-row"><span class="git-pill dirty">●3</span> Files with uncommitted changes</div>
                        <div class="legend-row"><span class="git-pill clean">✓</span> Working tree clean — nothing to commit</div>
                        <div class="legend-row"><span class="git-pill pub">🌐 public</span> Repo is public on GitHub</div>
                        <div class="legend-row"><span class="git-pill priv">🔒 private</span> Repo is private on GitHub</div>
                        <div class="legend-row"><span class="git-pill no-remote">⊘ local</span> No remote origin configured</div>
                        <div class="legend-row"><span class="git-pill date">9 days ago</span> Date of last commit</div>
                        <div class="legend-row"><span class="git-pill files">📁 5 items</span> Not a git repo — file count shown instead</div>
                    </div>
                    <div class="legend-section">
                        <div class="legend-title">Port pills (server status)</div>
                        <div class="legend-row"><span class="port-pill designated">:5173</span> Port set explicitly in catalogue.json</div>
                        <div class="legend-row"><span class="port-pill auto">:8080</span> Port auto-detected from project type</div>
                        <div class="legend-row"><span class="port-pill conflict">⚠ :8080</span> Same port used by another project — will conflict</div>
                        <div class="legend-row"><span class="port-pill running">:5173</span> Server is currently running on this port</div>
                    </div>
                    <div class="legend-section">
                        <div class="legend-title">Card badges (top-left corner)</div>
                        <div class="legend-row"><span class="badge catalogue">📋</span> Has a catalogue.json metadata file</div>
                        <div class="legend-row"><span class="badge server">▶</span> Has a launchable dev server</div>
                        <div class="legend-row"><span class="chip chip-tools">TOOLS</span> Category label (colored dot = category)</div>
                    </div>
                    <div class="legend-section">
                        <div class="legend-title">Card actions</div>
                        <div class="legend-row"><b>Click</b> → Open project in current Cursor window</div>
                        <div class="legend-row"><b>⌘/Ctrl+Click</b> → Open in a new Cursor window</div>
                        <div class="legend-row"><b>▶ Run</b> → Start dev server + open in Chrome</div>
                        <div class="legend-row"><b>🚀 Both</b> → Open in Cursor + start server + Chrome</div>
                        <div class="legend-row"><b>⚙ Manage</b> → Edit catalogue, publish to GitHub, capture screenshot</div>
                        <div class="legend-row"><b>🐙 Publish</b> → git + catalogue + screenshot + GitHub (Pages optional)</div>
                        <div class="legend-row"><b>⬆ Commit</b> → Add, commit, and push uncommitted files</div>
                        <div class="legend-row"><b>📍</b> → Pin / unpin project (pinned stay at top)</div>
                    </div>
                </div>
            </div>

            <div class="filters-bar">
                <div class="filter-row">
                    <span class="filter-row-label">Location</span>
                    <div class="filter-chips loc-chips">{filter_chips_html}</div>
                </div>
                {group_filters_block}
            </div>

            {rows_view_block}

            <div id="view-grid" class="view">
                <div class="grid-toolbar">
                    <div class="sort-control">
                        <label for="sortSelect">Sort</label>
                        <select id="sortSelect" onchange="sortGrid(this.value)">
                            <option value="recency">Recent activity</option>
                            <option value="commit">Last commit</option>
                            <option value="modified">Last modified</option>
                            <option value="alpha">Name A–Z</option>
                            <option value="alpha-desc">Name Z–A</option>
                            <option value="group">Group</option>
                        </select>
                    </div>
                </div>
                <div class="card-grid" id="cardGrid">{grid_cards_html}</div>
            </div>

            <div id="view-feed" class="view" style="display:none">
                {feed_html}
            </div>

            <div id="view-table" class="view" style="display:none">
                {table_html}
            </div>
            
            <footer>
                <p>Generated {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
            </footer>
        </main>
    </div>

    <!-- Manage modal -->
    <div class="modal-overlay" id="manageModal" onclick="if(event.target===this) closeManage()">
        <div class="modal">
            <div class="modal-head">
                <div>
                    <h2 id="mgTitle">Manage project</h2>
                    <div class="modal-sub" id="mgPath"></div>
                </div>
                <button class="modal-close" onclick="closeManage()">×</button>
            </div>
            <div class="modal-body">
                <div class="modal-section">
                    <h3>Open</h3>
                    <div class="quick-actions">
                        <button class="qbtn" onclick="mgOpenCursor()">📂 Open in Cursor</button>
                        <button class="qbtn" id="mgReadmeBtn" onclick="mgOpenReadme()">📖 Open README</button>
                        <button class="qbtn primary" id="mgRunBtn" onclick="mgRun()" style="display:none">▶ Open webpage / server</button>
                    </div>
                    <div class="modal-md-list" id="mgMdList"></div>
                </div>

                <div class="modal-section" id="mgCommitSection" style="display:none">
                    <h3>Commit &amp; push</h3>
                    <div class="modal-hint" id="mgCommitStatus">No local git changes.</div>
                    <div class="quick-actions">
                        <button class="qbtn primary" id="mgCommitBtn" onclick="mgCommitPush()" title="Stage selected files, commit, and push">⬆ Commit &amp; push</button>
                        <button class="qbtn" id="mgCommitOptsBtn" onclick="mgToggleCommitOpts()">Options</button>
                    </div>
                    <div id="mgCommitOpts" class="commit-opts" style="display:none">
                        <label class="publish-choice"><input type="checkbox" id="mgIncUntracked" checked> Include untracked files</label>
                        <label class="publish-choice"><input type="checkbox" id="mgDoPush" checked> Push after commit</label>
                        <div class="publish-name-row" style="margin-top:8px">
                            <label for="mgCommitMsg">Commit message</label>
                            <input id="mgCommitMsg" type="text" placeholder="Update project" autocomplete="off">
                        </div>
                        <div class="commit-files-head">
                            <span>Files to include</span>
                            <span>
                                <button type="button" class="mini-gen" onclick="mgCommitSelect(true)">all</button>
                                <button type="button" class="mini-gen" onclick="mgCommitSelect(false)">none</button>
                            </span>
                        </div>
                        <div id="mgCommitFiles" class="commit-files"></div>
                    </div>
                    <ol id="mgCommitLog" class="publish-log" style="display:none"></ol>
                </div>

                <div class="modal-section">
                    <h3>Publish to GitHub</h3>
                    <div class="modal-hint" id="mgPubStatus">Recommended defaults are filled from the project type (static → public + Pages; backend → private).</div>
                    <div class="publish-name-row">
                        <label for="mgRepoName">GitHub repo name</label>
                        <input id="mgRepoName" type="text" placeholder="repo-name" autocomplete="off" spellcheck="false">
                    </div>
                    <div class="modal-hint" id="mgRepoNameHint">This is the GitHub repository name (not the catalogue title). Local folder stays the same.</div>
                    <div class="publish-row">
                        <label class="publish-choice"><input type="radio" name="mgVis" value="public"> 🌐 Public</label>
                        <label class="publish-choice"><input type="radio" name="mgVis" value="private" checked> 🔒 Private</label>
                        <label class="publish-choice"><input type="checkbox" id="mgPages"> GitHub Pages</label>
                    </div>
                    <div class="quick-actions">
                        <button class="qbtn primary" id="mgPublishCustomBtn" onclick="mgPublish(false)" title="Create or update the GitHub repo using the name, visibility, and Pages above, plus catalogue/screenshot already in the folder">✨ Create repo with these settings</button>
                        <button class="qbtn" id="mgPublishBtn" onclick="mgPublish(true)" title="Ignore the form and use recommended name, visibility, and Pages">🚀 Publish with defaults</button>
                        <button class="qbtn" id="mgPublishResetBtn" onclick="mgFillPublishDefaults()" title="Put the recommended name, visibility, and Pages back into the form">Reset form</button>
                    </div>
                    <div class="modal-hint">Green button uses the repo name, public/private, and Pages above (and any catalogue/screenshot already saved). Defaults ignores the form. Requires <code>gh auth login</code>.</div>
                    <ol id="mgPubLog" class="publish-log" style="display:none"></ol>
                </div>

                <div class="modal-section">
                    <h3>Auto-generate (local only)</h3>
                    <div class="quick-actions">
                        <button class="qbtn gen" id="mgGenAllBtn" onclick="mgGenerateAll()" title="Create catalogue.json AND capture a screenshot in one step">✨ Auto-generate catalogue + screenshot</button>
                    </div>
                    <div class="modal-hint">Creates <code>catalogue.json</code> (from folder/README/git/server) and, for runnable projects, captures <code>screenshot.png</code> — does not create a GitHub repo.</div>
                </div>

                <div class="modal-section">
                    <h3>Screenshot</h3>
                    <div class="quick-actions">
                        <button class="qbtn accent" id="mgShotBtn" onclick="mgCapture()">📸 Capture small screenshot</button>
                    </div>
                    <div class="modal-hint">Starts the project's server (if any), captures the page, resizes it small, and saves <code>screenshot.png</code> in the project.</div>
                    <img id="mgShotPreview" class="screenshot-preview" style="display:none" alt="screenshot preview">
                </div>

                <div class="modal-section">
                    <h3>Catalogue.json</h3>
                    <div class="form-grid">
                        <label>Title</label><input id="mgF_title" type="text" placeholder="Project title">
                        <label>One-liner</label><input id="mgF_oneLiner" type="text" placeholder="Short tagline">
                        <label>Description</label><textarea id="mgF_description" placeholder="Longer description"></textarea>
                        <label>Demo URL</label><input id="mgF_demoUrl" type="text" placeholder="https://… (optional)">
                        <label>Categories</label><input id="mgF_categories" type="text" placeholder="comma,separated">
                        <label>Tags</label><input id="mgF_tags" type="text" placeholder="comma,separated">
                        <label>Kind</label>
                        <select id="mgF_kind"><option>project</option><option>longform</option><option>page</option></select>
                        <label>Status</label>
                        <select id="mgF_status"><option>active</option><option>published</option><option>draft</option><option>archived</option></select>
                        <label>Server type</label>
                        <select id="mgF_serverType">
                            <option value="">(auto-detect)</option>
                            <option value="static">static</option>
                            <option value="node">node</option>
                            <option value="liveserver">liveserver</option>
                            <option value="python">python</option>
                            <option value="custom">custom</option>
                        </select>
                        <label>Server port</label>
                        <div style="display:flex; gap:8px; align-items:center">
                            <input id="mgF_serverPort" type="number" placeholder="e.g. 5173" style="flex:1">
                            <button class="qbtn" type="button" onclick="mgSuggestPort()" title="Find a free, non-conflicting port">🎲 Suggest</button>
                        </div>
                        <label>Server command</label><input id="mgF_serverCommand" type="text" placeholder="(custom) e.g. npm run dev">
                        <label class="form-row-full" style="display:flex;gap:8px;align-items:center">
                            <input id="mgF_autoStart" type="checkbox" style="width:auto"> Auto-start server with "Open both"
                        </label>
                    </div>
                    <div class="quick-actions">
                        <button class="qbtn accent" onclick="mgSaveCatalogue()">💾 Save catalogue.json</button>
                        <button class="qbtn gen" onclick="mgAutogen()" title="Fill from folder name, README, git remote, and detected server">✨ Auto-fill from project</button>
                        <span class="modal-hint" id="mgSaveHint"></span>
                    </div>
                    <div class="modal-hint">Auto-fill suggests values from the folder; review, then Save. "Auto-generate everything" below also captures a screenshot.</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Ports overview modal -->
    <div class="modal-overlay" id="portsModal" onclick="if(event.target===this) closePorts()">
        <div class="modal">
            <div class="modal-head">
                <div>
                    <h2>Ports</h2>
                    <div class="modal-sub" id="portsSummary">Designated server ports across your projects</div>
                </div>
                <div style="display:flex; gap:8px; align-items:center">
                    <button class="qbtn" onclick="loadPorts()">↻ Refresh</button>
                    <button class="modal-close" onclick="closePorts()">×</button>
                </div>
            </div>
            <div class="modal-body">
                <div id="portsTableWrap"><div class="modal-hint">Loading…</div></div>
            </div>
        </div>
    </div>

    <script>
        const isLocalServer = window.location.protocol === 'http:' && window.location.hostname === 'localhost';
        const PUBLIC_PAGE = {public_page_js};
        const HAS_GROUP_ROWS = {has_group_rows};
        const REPO_GROUPS = {groups_json};
        let mgPath = null;

        function persistRepoGroups(okMsg) {{
            if (!isLocalServer) {{
                showNotification('Run the launcher server to save groups', 'info');
                return Promise.resolve();
            }}
            const body = Object.assign({{ regenerate: false }}, REPO_GROUPS);
            return fetch('/save-repo-groups', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(body),
            }}).then(r => r.json()).then(d => {{
                if (d.status === 'ok') showNotification(okMsg || 'Groups saved', 'success');
                else showNotification(d.message || 'Could not save groups', 'error');
                return d;
            }}).catch(() => showNotification('Could not save groups', 'error'));
        }}

        function changeProjectGroup(sel, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            const repo = sel.getAttribute('data-repo');
            const gid = sel.value;
            const label = (sel.options[sel.selectedIndex] && sel.options[sel.selectedIndex].textContent) || '';
            if (!repo || !Array.isArray(REPO_GROUPS.columns)) return;
            REPO_GROUPS.columns.forEach(c => {{
                c.names = (c.names || []).filter(n => n !== repo);
            }});
            let dest = REPO_GROUPS.columns.find(c => String(c.id) === String(gid));
            if (!dest) dest = REPO_GROUPS.columns.find(c => c.id === 'general');
            if (dest) dest.names.push(repo);
            const row = sel.closest('.searchable');
            if (row) {{
                row.setAttribute('data-group', gid);
                row.setAttribute('data-group-label', label);
            }}
            const cell = sel.closest('td');
            if (cell) cell.setAttribute('data-sort', label.toLowerCase());
            persistRepoGroups('Moved to ' + label);
        }}
        
        function filterProjects() {{
            const term = document.getElementById('searchInput').value.toLowerCase().trim();
            document.querySelectorAll('.searchable').forEach(el => {{
                const hay = (el.getAttribute('data-search') || '').toLowerCase();
                el.classList.toggle('search-hidden', !!term && !hay.includes(term));
            }});
            applyRowVisibility();
        }}
        
        function switchView(name) {{
            ['rows', 'grid', 'feed', 'table'].forEach(v => {{
                const el = document.getElementById('view-' + v);
                if (el) el.style.display = (v === name) ? '' : 'none';
            }});
            document.querySelectorAll('.view-btn').forEach(b =>
                b.classList.toggle('active', b.getAttribute('data-view') === name));
            try {{ localStorage.setItem('dashboardView', name); }} catch (e) {{}}
        }}
        
        let sortState = {{ col: null, dir: 'asc' }};
        function sortTable(col, type) {{
            const table = document.getElementById('dataTable');
            if (!table) return;
            const tbody = table.tBodies[0];
            const rows = Array.from(tbody.querySelectorAll('tr'));
            // Numeric/date columns default to descending (most recent / largest
            // first); text columns default to ascending. Re-clicking toggles.
            let dir;
            if (sortState.col === col) {{
                dir = sortState.dir === 'asc' ? 'desc' : 'asc';
            }} else {{
                dir = (type === 'num') ? 'desc' : 'asc';
            }}
            sortState = {{ col, dir }};
            rows.sort((a, b) => {{
                const ac = a.children[col], bc = b.children[col];
                let av, bv;
                if (type === 'num') {{
                    av = parseFloat(ac.getAttribute('data-sort') || '0');
                    bv = parseFloat(bc.getAttribute('data-sort') || '0');
                }} else {{
                    av = (ac.textContent || '').trim().toLowerCase();
                    bv = (bc.textContent || '').trim().toLowerCase();
                }}
                if (av < bv) return dir === 'asc' ? -1 : 1;
                if (av > bv) return dir === 'asc' ? 1 : -1;
                return 0;
            }});
            rows.forEach(r => tbody.appendChild(r));
            table.querySelectorAll('thead th').forEach((th, i) => {{
                th.classList.remove('sort-asc', 'sort-desc');
                if (i === col) th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');
            }});
        }}
        
        let locFilter = 'all';
        let groupFilter = 'all';
        function setFilter(btn, filter) {{
            locFilter = filter;
            document.querySelectorAll('.loc-chips .fchip').forEach(b => b.classList.toggle('active', b === btn));
            applyFilters();
        }}
        function setGroupFilter(btn, filter) {{
            groupFilter = filter;
            document.querySelectorAll('.group-chips .fchip').forEach(b => b.classList.toggle('active', b === btn));
            applyFilters();
        }}
        function applyFilters() {{
            document.querySelectorAll('.project-card, .feed-card, .table-row').forEach(el => {{
                let locOk;
                if (locFilter === 'all') locOk = true;
                else if (locFilter === '__pinned') locOk = el.getAttribute('data-pinned') === 'true';
                else if (locFilter === '__local') locOk = el.getAttribute('data-source') !== 'github';
                else locOk = el.getAttribute('data-category') === locFilter;
                const groupOk = groupFilter === 'all' || el.getAttribute('data-group') === groupFilter;
                el.classList.toggle('filter-hidden', !(locOk && groupOk));
            }});
            applyRowVisibility();
        }}
        function applyRowVisibility() {{
            document.querySelectorAll('#groupRows .category-row').forEach(row => {{
                const gid = row.getAttribute('data-group-id') || '';
                const groupOk = groupFilter === 'all' || gid === groupFilter;
                const visible = row.querySelectorAll('.project-card:not(.filter-hidden):not(.search-hidden)').length;
                row.classList.toggle('filter-hidden', !groupOk || visible === 0);
            }});
        }}
        
        function sortGrid(mode) {{
            const grid = document.getElementById('cardGrid');
            if (!grid) return;
            const cards = Array.from(grid.querySelectorAll('.project-card'));
            const num = (c, a) => parseFloat(c.getAttribute(a) || '0');
            const nm = c => (c.getAttribute('data-name') || '');
            cards.sort((a, b) => {{
                switch (mode) {{
                    case 'alpha': return nm(a).localeCompare(nm(b));
                    case 'alpha-desc': return nm(b).localeCompare(nm(a));
                    case 'group': return (a.getAttribute('data-group-label') || '').localeCompare(b.getAttribute('data-group-label') || '');
                    case 'commit': return num(b, 'data-commit') - num(a, 'data-commit');
                    case 'modified': return num(b, 'data-mtime') - num(a, 'data-mtime');
                    default: return Math.max(num(b,'data-commit'), num(b,'data-mtime'))
                                  - Math.max(num(a,'data-commit'), num(a,'data-mtime'));
                }}
            }});
            cards.forEach(c => grid.appendChild(c));
        }}
        
        /* ---- Manage modal ---- */
        function setVal(id, v) {{ const e = document.getElementById(id); if (e) e.value = v; }}
        function closeManage() {{ document.getElementById('manageModal').classList.remove('open'); }}
        
        function openManage(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            mgPath = path;
            document.getElementById('mgPath').textContent = path;
            document.getElementById('mgTitle').textContent = 'Manage · ' + path.split('/').pop();
            document.getElementById('mgShotPreview').style.display = 'none';
            document.getElementById('mgSaveHint').textContent = '';
            document.getElementById('mgMdList').innerHTML = '';
            document.getElementById('mgRunBtn').style.display = 'none';
            if (isLocalServer) {{
                fetch('/project-info?path=' + encodeURIComponent(path)).then(r => r.json()).then(info => {{
                    const c = info.catalogue || {{}};
                    setVal('mgF_title', c.title || info.name || '');
                    setVal('mgF_oneLiner', c.oneLiner || '');
                    setVal('mgF_description', c.description || '');
                    setVal('mgF_demoUrl', c.demoUrl || '');
                    setVal('mgF_categories', (c.categories || []).join(', '));
                    setVal('mgF_tags', (c.tags || []).join(', '));
                    setVal('mgF_kind', c.kind || 'project');
                    setVal('mgF_status', c.status || 'active');
                    const srv = c.server || {{}};
                    setVal('mgF_serverType', srv.type || '');
                    setVal('mgF_serverPort', srv.port || '');
                    setVal('mgF_serverCommand', srv.command || '');
                    document.getElementById('mgF_autoStart').checked = !!srv.autoStart;
                    const list = document.getElementById('mgMdList');
                    (info.md_files || []).forEach(f => {{
                        const b = document.createElement('button');
                        b.className = 'qbtn'; b.textContent = '📄 ' + f;
                        b.onclick = () => mgOpenFile(f);
                        list.appendChild(b);
                    }});
                    if (info.runnable) {{
                        const rb = document.getElementById('mgRunBtn');
                        rb.style.display = '';
                        rb.textContent = '▶ Open webpage (' + (info.server_url || 'server') + ')';
                    }}
                    document.getElementById('mgReadmeBtn').style.opacity = info.readme ? '1' : '.45';
                    fillPublishFromPreview(info.publish);
                    fillCommitFromGit(info.git);
                }}).catch(() => {{}});
            }}
            document.getElementById('manageModal').classList.add('open');
        }}
        
        function mgOpenCursor() {{
            if (!mgPath) return;
            if (isLocalServer) fetch('/open-in-cursor?path=' + encodeURIComponent(mgPath) + '&new=false');
            showNotification('Opening in Cursor', 'success');
        }}
        function mgOpenReadme() {{ mgOpenFile('README.md'); }}
        function mgOpenFile(f) {{
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/open-file?path=' + encodeURIComponent(mgPath) + '&file=' + encodeURIComponent(f))
                .then(r => r.json())
                .then(d => showNotification(d.status === 'ok' ? ('Opened ' + f) : (d.message || 'Not found'),
                                            d.status === 'ok' ? 'success' : 'error'))
                .catch(() => showNotification('Error', 'error'));
        }}
        function mgRun() {{ if (mgPath) launchApp(mgPath, new Event('x')); }}
        function mgCapture() {{
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            const btn = document.getElementById('mgShotBtn');
            btn.textContent = '📸 Capturing…'; btn.disabled = true;
            fetch('/capture-screenshot?path=' + encodeURIComponent(mgPath)).then(r => r.json()).then(d => {{
                btn.textContent = '📸 Capture small screenshot'; btn.disabled = false;
                if (d.status === 'ok') {{
                    showNotification('Screenshot saved to project', 'success');
                    const img = document.getElementById('mgShotPreview');
                    img.src = '/screenshot-file?path=' + encodeURIComponent(mgPath) + '&t=' + Date.now();
                    img.style.display = '';
                    regenerateCards();
                }} else showNotification(d.message || 'Capture failed', 'error');
            }}).catch(() => {{ btn.textContent = '📸 Capture small screenshot'; btn.disabled = false; showNotification('Error', 'error'); }});
        }}
        function mgSaveCatalogue() {{
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            const val = id => document.getElementById(id).value.trim();
            const list = s => s ? s.split(',').map(x => x.trim()).filter(Boolean) : [];
            const cat = {{
                id: mgPath.split('/').pop(),
                title: val('mgF_title'),
                oneLiner: val('mgF_oneLiner'),
                description: val('mgF_description'),
                demoUrl: val('mgF_demoUrl'),
                categories: list(val('mgF_categories')),
                tags: list(val('mgF_tags')),
                kind: val('mgF_kind'),
                status: val('mgF_status'),
            }};
            const st = val('mgF_serverType'), sp = val('mgF_serverPort'), sc = val('mgF_serverCommand');
            const auto = document.getElementById('mgF_autoStart').checked;
            if (st || sp || sc || auto) {{
                cat.server = {{ openPath: '/', autoStart: auto }};
                if (st) cat.server.type = st;
                if (sp) cat.server.port = parseInt(sp, 10);
                if (sc) cat.server.command = sc;
            }}
            fetch('/save-catalogue', {{
                method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ path: mgPath, catalogue: cat }})
            }}).then(r => r.json()).then(d => {{
                document.getElementById('mgSaveHint').textContent = d.status === 'ok' ? 'Saved ✓' : (d.message || 'Error');
                showNotification(d.status === 'ok' ? 'catalogue.json saved' : 'Save failed',
                                 d.status === 'ok' ? 'success' : 'error');
                if (d.status === 'ok') regenerateCards();
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        /* ---- Ports overview ---- */
        function openPorts() {{
            if (!isLocalServer) {{ showNotification('Run server.py for the Ports overview', 'info'); return; }}
            document.getElementById('portsModal').classList.add('open');
            loadPorts();
        }}
        function closePorts() {{ document.getElementById('portsModal').classList.remove('open'); }}
        
        let portsData = [];
        function loadPorts() {{
            const wrap = document.getElementById('portsTableWrap');
            wrap.innerHTML = '<div class="modal-hint">Loading…</div>';
            fetch('/ports').then(r => r.json()).then(d => renderPorts(d.ports || [])).catch(() => {{
                wrap.innerHTML = '<div class="modal-hint">Failed to load ports.</div>';
            }});
        }}
        
        function renderPorts(ports) {{
            portsData = ports;
            const wrap = document.getElementById('portsTableWrap');
            const conflicts = ports.filter(p => p.conflict).length;
            const listening = ports.filter(p => p.listening).length;
            document.getElementById('portsSummary').textContent =
                ports.length + ' ports · ' + listening + ' listening · ' + conflicts + ' conflict' + (conflicts === 1 ? '' : 's');
            if (!ports.length) {{ wrap.innerHTML = '<div class="modal-hint">No designated ports yet. Add a server port via Manage → catalogue.json.</div>'; return; }}
            let rows = '';
            ports.forEach(p => {{
                const projs = p.projects.map(pr =>
                    '<div class="p-proj">' + (pr.title || '') +
                    (pr.designated ? '' : ' <span class="muted">(auto)</span>') + '</div>').join('');
                const state = p.listening
                    ? '<span class="p-state listening">listening</span>'
                    : '<span class="p-state free">free</span>';
                const conflict = p.conflict ? '<span class="p-conflict">⚠ conflict</span>' : '';
                let action = '';
                if (p.listening && p.managed_path) {{
                    action = '<button class="p-stop" onclick="stopPortByNum(' + p.port + ')">Stop</button>';
                }} else if (p.listening) {{
                    action = '<span class="modal-hint">external</span>';
                }}
                rows += '<tr class="ports-row' + (p.conflict ? ' is-conflict' : '') + '">' +
                    '<td class="p-num">:' + p.port + '</td>' +
                    '<td class="p-proj">' + projs + ' ' + conflict + '</td>' +
                    '<td>' + state + '</td>' +
                    '<td>' + action + '</td></tr>';
            }});
            wrap.innerHTML = '<table class="ports-table"><thead><tr><th>Port</th><th>Project(s)</th><th>Status</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>';
            document.getElementById('portsBtn').classList.toggle('has-conflict', conflicts > 0);
            markRunningPorts(ports);
        }}
        
        function stopPortByNum(port) {{
            const entry = portsData.find(p => p.port === port);
            if (!entry || !entry.managed_path) return;
            fetch('/stop-app?path=' + encodeURIComponent(entry.managed_path)).then(r => r.json()).then(() => {{
                showNotification('Stopped server on :' + port, 'success');
                setTimeout(loadPorts, 400);
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function markRunningPorts(ports) {{
            const live = new Set((ports || []).filter(p => p.listening).map(p => String(p.port)));
            document.querySelectorAll('.port-pill[data-port]').forEach(el => {{
                el.classList.toggle('running', live.has(el.getAttribute('data-port')));
            }});
        }}
        
        function refreshPortStates() {{
            if (!isLocalServer) return;
            fetch('/ports').then(r => r.json()).then(d => {{
                markRunningPorts(d.ports || []);
                const conflicts = (d.ports || []).filter(p => p.conflict).length;
                const btn = document.getElementById('portsBtn');
                if (btn) btn.classList.toggle('has-conflict', conflicts > 0);
            }}).catch(() => {{}});
        }}
        
        function mgSuggestPort() {{
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/suggest-port').then(r => r.json()).then(d => {{
                if (d.port) {{ setVal('mgF_serverPort', d.port); showNotification('Suggested free port ' + d.port, 'success'); }}
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function fillCatalogueForm(c) {{
            if (!c) return;
            setVal('mgF_title', c.title || '');
            setVal('mgF_oneLiner', c.oneLiner || '');
            setVal('mgF_description', c.description || '');
            setVal('mgF_demoUrl', c.demoUrl || '');
            setVal('mgF_categories', (c.categories || []).join(', '));
            setVal('mgF_tags', (c.tags || []).join(', '));
            setVal('mgF_kind', c.kind || 'project');
            setVal('mgF_status', c.status || 'active');
            const srv = c.server || {{}};
            setVal('mgF_serverType', srv.type || '');
            setVal('mgF_serverPort', srv.port || '');
            setVal('mgF_serverCommand', srv.command || '');
            document.getElementById('mgF_autoStart').checked = !!srv.autoStart;
        }}
        
        function mgAutogen() {{
            if (!isLocalServer || !mgPath) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/autogen-catalogue?path=' + encodeURIComponent(mgPath)).then(r => r.json()).then(d => {{
                if (d.status === 'ok') {{
                    fillCatalogueForm(d.catalogue);
                    document.getElementById('mgSaveHint').textContent = 'Auto-filled & saved ✓';
                    showNotification('catalogue.json auto-generated', 'success');
                    regenerateCards();
                }} else showNotification(d.message || 'Failed', 'error');
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function mgGenerateAll() {{
            if (!isLocalServer || !mgPath) {{ showNotification('Run server.py for this', 'info'); return; }}
            const btn = document.getElementById('mgGenAllBtn');
            btn.disabled = true; btn.textContent = '✨ Generating…';
            fetch('/autogen-catalogue?path=' + encodeURIComponent(mgPath)).then(r => r.json()).then(d => {{
                if (d.status === 'ok') fillCatalogueForm(d.catalogue);
                showNotification('catalogue.json created — capturing screenshot…', 'success');
                return fetch('/capture-screenshot?path=' + encodeURIComponent(mgPath));
            }}).then(r => r ? r.json() : null).then(d => {{
                btn.disabled = false; btn.textContent = '✨ Auto-generate catalogue + screenshot';
                if (d && d.status === 'ok') {{
                    showNotification('Done — catalogue + screenshot generated', 'success');
                    const img = document.getElementById('mgShotPreview');
                    img.src = '/screenshot-file?path=' + encodeURIComponent(mgPath) + '&t=' + Date.now();
                    img.style.display = '';
                    regenerateCards();
                }} else if (d) {{
                    showNotification('Catalogue saved; screenshot skipped: ' + (d.message || ''), 'info');
                }}
            }}).catch(() => {{
                btn.disabled = false; btn.textContent = '✨ Auto-generate catalogue + screenshot';
                showNotification('Error', 'error');
            }});
        }}

        let mgPubDefaults = null;

        function bindPublishFormWatchers() {{
            if (window._mgPubBound) return;
            window._mgPubBound = true;
            const nameEl = document.getElementById('mgRepoName');
            if (nameEl) nameEl.addEventListener('input', updatePublishButtons);
            document.querySelectorAll('input[name="mgVis"]').forEach(r => r.addEventListener('change', updatePublishButtons));
            const pages = document.getElementById('mgPages');
            if (pages) pages.addEventListener('change', updatePublishButtons);
        }}

        function publishFormMatchesDefaults() {{
            if (!mgPubDefaults) return true;
            const cur = currentPublishChoices(false);
            const recName = (mgPubDefaults.repo_name || '').trim();
            return cur.visibility === (mgPubDefaults.visibility || 'private')
                && !!cur.pages === !!mgPubDefaults.pages
                && (cur.repo_name || '') === recName;
        }}

        function updatePublishButtons() {{
            const creating = !(mgPubDefaults && mgPubDefaults.has_remote);
            const custom = document.getElementById('mgPublishCustomBtn');
            const defBtn = document.getElementById('mgPublishBtn');
            if (custom) {{
                custom.textContent = creating
                    ? '✨ Create repo with these settings'
                    : '✨ Update repo with these settings';
            }}
            if (defBtn) {{
                defBtn.textContent = creating
                    ? '🚀 Create repo with defaults'
                    : '🚀 Update with defaults';
            }}
        }}

        function fillPublishFromPreview(pub) {{
            const status = document.getElementById('mgPubStatus');
            const custom = document.getElementById('mgPublishCustomBtn');
            const defBtn = document.getElementById('mgPublishBtn');
            const log = document.getElementById('mgPubLog');
            if (log) {{ log.style.display = 'none'; log.innerHTML = ''; }}
            bindPublishFormWatchers();
            if (!pub || pub.status !== 'ok') {{
                if (status) status.textContent = (pub && pub.message) || 'Could not load publish defaults.';
                return;
            }}
            mgPubDefaults = pub.defaults || {{}};
            applyPublishDefaults(mgPubDefaults);
            const ghOk = pub.gh && pub.gh.ok;
            if (custom) custom.disabled = !ghOk;
            if (defBtn) defBtn.disabled = !ghOk;
            updatePublishButtons();
            if (status) {{
                const kind = (mgPubDefaults.kind || {{}});
                const kindNote = kind.backend
                    ? ('Detected ' + (kind.backend_type || 'backend') + ' — Pages off by default.')
                    : (kind.static ? 'Detected static site — public + Pages recommended.' : 'Could not detect site type.');
                const ghNote = ghOk ? '' : (' ' + ((pub.gh && pub.gh.message) || 'gh not ready.'));
                status.textContent = (pub.summary || '') + '. ' + kindNote + ghNote;
            }}
        }}

        function applyPublishDefaults(d) {{
            if (!d) return;
            const vis = d.visibility === 'public' ? 'public' : 'private';
            document.querySelectorAll('input[name="mgVis"]').forEach(r => {{ r.checked = r.value === vis; }});
            const pages = document.getElementById('mgPages');
            if (pages) pages.checked = !!d.pages;
            const nameEl = document.getElementById('mgRepoName');
            const hint = document.getElementById('mgRepoNameHint');
            if (nameEl) {{
                nameEl.value = d.repo_name || d.folder_name || '';
                nameEl.disabled = !!d.has_remote;
            }}
            if (hint) {{
                hint.textContent = d.has_remote
                    ? 'Already on GitHub — name is fixed to the existing remote. Visibility and Pages can still change.'
                    : 'GitHub repository name (not the catalogue title). Local folder stays the same.';
            }}
        }}

        function mgFillPublishDefaults() {{
            if (mgPubDefaults) applyPublishDefaults(mgPubDefaults);
            else if (mgPath) {{
                fetch('/publish-preview?path=' + encodeURIComponent(mgPath))
                    .then(r => r.json()).then(fillPublishFromPreview);
            }}
        }}

        function renderPublishLog(steps) {{
            const log = document.getElementById('mgPubLog');
            if (!log) return;
            log.innerHTML = '';
            (steps || []).forEach(s => {{
                const li = document.createElement('li');
                const cls = s.status === 'ok' ? 'ok' : (s.status === 'error' ? 'err' : 'skip');
                li.className = cls;
                li.textContent = s.name + ': ' + (s.detail || s.status);
                log.appendChild(li);
            }});
            log.style.display = steps && steps.length ? '' : 'none';
        }}

        function currentPublishChoices(useRecommended) {{
            if (useRecommended && mgPubDefaults) {{
                return {{
                    visibility: mgPubDefaults.visibility || 'private',
                    pages: !!mgPubDefaults.pages,
                    repo_name: mgPubDefaults.repo_name || '',
                    defaults: true,
                }};
            }}
            const nameEl = document.getElementById('mgRepoName');
            const typed = nameEl ? (nameEl.value || '').trim() : '';
            const visEl = document.querySelector('input[name="mgVis"]:checked');
            return {{
                visibility: (visEl && visEl.value) || 'private',
                pages: !!(document.getElementById('mgPages') && document.getElementById('mgPages').checked),
                repo_name: typed || (mgPubDefaults && mgPubDefaults.repo_name) || '',
                defaults: false,
            }};
        }}

        function runPublish(path, choices, btn) {{
            const label = btn ? btn.textContent : '';
            if (btn) {{ btn.disabled = true; btn.textContent = '🐙 Publishing…'; }}
            showNotification('Publishing ' + path.split('/').pop() + '…', 'info');
            return fetch('/publish-repo', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(Object.assign({{ path: path }}, choices)),
            }}).then(r => r.json()).then(d => {{
                if (btn) {{ btn.disabled = false; btn.textContent = label; }}
                updatePublishButtons();
                renderPublishLog(d.steps || []);
                if (d.status === 'ok') {{
                    showNotification(d.message || 'Published', 'success');
                    fetch('/project-info?path=' + encodeURIComponent(path)).then(r => r.json()).then(info => {{
                        fillCatalogueForm(info.catalogue || {{}});
                        fillPublishFromPreview(info.publish);
                        if (info.publish && info.publish.defaults && info.publish.defaults.has_screenshot) {{
                            const img = document.getElementById('mgShotPreview');
                            if (img) {{
                                img.src = '/screenshot-file?path=' + encodeURIComponent(path) + '&t=' + Date.now();
                                img.style.display = '';
                            }}
                        }}
                    }}).catch(() => {{}});
                    regenerateCards();
                }} else {{
                    showNotification(d.message || 'Publish failed', 'error');
                }}
                return d;
            }}).catch(() => {{
                if (btn) {{ btn.disabled = false; btn.textContent = label; }}
                updatePublishButtons();
                showNotification('Publish error', 'error');
            }});
        }}

        function mgPublish(useRecommended) {{
            if (!isLocalServer || !mgPath) {{ showNotification('Run server.py for this', 'info'); return; }}
            const choices = currentPublishChoices(!!useRecommended);
            const name = choices.repo_name || mgPath.split('/').pop();
            const pagesNote = choices.pages ? ' with GitHub Pages' : '';
            const creating = !(mgPubDefaults && mgPubDefaults.has_remote);
            const verb = creating ? 'Create' : 'Update';
            const how = useRecommended ? 'recommended defaults' : 'these settings';
            if (!confirm(verb + ' GitHub repo “' + name + '” as ' + choices.visibility + pagesNote + ' using ' + how + '?')) return;
            const btn = document.getElementById(useRecommended ? 'mgPublishBtn' : 'mgPublishCustomBtn');
            runPublish(mgPath, Object.assign(choices, {{ defaults: !!useRecommended }}), btn);
        }}

        function publishNow(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/publish-preview?path=' + encodeURIComponent(path)).then(r => r.json()).then(pub => {{
                if (!pub || pub.status !== 'ok') {{
                    showNotification((pub && pub.message) || 'Cannot publish this folder', 'error');
                    return;
                }}
                if (pub.gh && !pub.gh.ok) {{
                    showNotification(pub.gh.message || 'gh not ready', 'error');
                    return;
                }}
                const d = pub.defaults || {{}};
                const vis = d.visibility || 'private';
                const repo = d.repo_name || path.split('/').pop();
                const pagesNote = d.pages ? ' with GitHub Pages' : '';
                if (!confirm('Publish GitHub repo “' + repo + '” as ' + vis + pagesNote + ' using recommended defaults?')) return;
                runPublish(path, {{ visibility: vis, pages: !!d.pages, repo_name: repo, defaults: true }}, null);
            }}).catch(() => showNotification('Error', 'error'));
        }}

        let mgGitTree = null;

        function fillCommitFromGit(git) {{
            const section = document.getElementById('mgCommitSection');
            const status = document.getElementById('mgCommitStatus');
            const btn = document.getElementById('mgCommitBtn');
            const log = document.getElementById('mgCommitLog');
            if (log) {{ log.style.display = 'none'; log.innerHTML = ''; }}
            if (!git || git.status !== 'ok' || !git.is_repo) {{
                if (section) section.style.display = 'none';
                mgGitTree = null;
                return;
            }}
            mgGitTree = git;
            if (section) section.style.display = '';
            const bits = [];
            if (git.branch) bits.push('⎇ ' + git.branch);
            if (git.changed_count) bits.push(git.changed_count + ' changed');
            if (git.untracked_count) bits.push(git.untracked_count + ' untracked');
            if (git.ahead) bits.push('↑' + git.ahead);
            if (git.behind) bits.push('↓' + git.behind);
            if (!git.dirty && !git.ahead) bits.push('clean');
            if (status) status.textContent = bits.join(' · ') + (git.has_remote ? '' : ' · no origin (commit only)');
            const msg = document.getElementById('mgCommitMsg');
            if (msg) msg.value = git.suggested_message || 'Update project';
            const pushEl = document.getElementById('mgDoPush');
            if (pushEl) pushEl.checked = !!git.has_remote;
            renderCommitFiles(git);
            const inc = document.getElementById('mgIncUntracked');
            if (inc && !inc._bound) {{
                inc._bound = true;
                inc.addEventListener('change', () => {{ if (mgGitTree) renderCommitFiles(mgGitTree); }});
            }}
            if (btn) {{
                if (git.dirty) btn.textContent = '⬆ Commit & push';
                else if (git.ahead) btn.textContent = '⬆ Push ' + git.ahead + ' commit' + (git.ahead === 1 ? '' : 's');
                else btn.textContent = '⬆ Nothing to commit';
                btn.disabled = !git.dirty && !git.ahead;
            }}
        }}

        function renderCommitFiles(git) {{
            const wrap = document.getElementById('mgCommitFiles');
            if (!wrap) return;
            wrap.innerHTML = '';
            const includeUntracked = !!(document.getElementById('mgIncUntracked') && document.getElementById('mgIncUntracked').checked);
            (git.files || []).forEach(f => {{
                if (f.kind === 'untracked' && !includeUntracked) return;
                const row = document.createElement('label');
                row.className = 'commit-file';
                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = f.kind !== 'unmerged';
                cb.dataset.path = f.path;
                cb.dataset.kind = f.kind;
                const xy = document.createElement('span');
                xy.className = 'commit-xy' + (f.kind === 'untracked' ? ' untracked' : '');
                xy.textContent = f.xy || (f.kind === 'untracked' ? '??' : 'M');
                const name = document.createElement('span');
                name.textContent = f.path;
                row.appendChild(cb);
                row.appendChild(xy);
                row.appendChild(name);
                wrap.appendChild(row);
            }});
            if (!wrap.children.length) {{
                wrap.innerHTML = '<div class="modal-hint">No matching files.</div>';
            }}
        }}

        function mgToggleCommitOpts() {{
            const el = document.getElementById('mgCommitOpts');
            if (el) el.style.display = el.style.display === 'none' ? '' : 'none';
        }}

        function mgCommitSelect(on) {{
            document.querySelectorAll('#mgCommitFiles input[type=checkbox]').forEach(cb => {{ cb.checked = !!on; }});
        }}

        function selectedCommitFiles() {{
            const includeUntracked = !!(document.getElementById('mgIncUntracked') && document.getElementById('mgIncUntracked').checked);
            const boxes = document.querySelectorAll('#mgCommitFiles input[type=checkbox]');
            if (!boxes.length) return null;
            const files = [];
            boxes.forEach(cb => {{
                if (!cb.checked) return;
                if (cb.dataset.kind === 'untracked' && !includeUntracked) return;
                if (cb.dataset.path) files.push(cb.dataset.path);
            }});
            return files;
        }}

        function runCommitPush(path, payload, btn) {{
            const label = btn ? btn.textContent : '';
            if (btn) {{ btn.disabled = true; btn.textContent = '⬆ Working…'; }}
            return fetch('/git-commit-push', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(Object.assign({{ path: path }}, payload)),
            }}).then(r => r.json()).then(d => {{
                if (btn) {{ btn.disabled = false; btn.textContent = label; }}
                const log = document.getElementById('mgCommitLog');
                if (log) {{
                    log.innerHTML = '';
                    (d.steps || []).forEach(s => {{
                        const li = document.createElement('li');
                        li.className = s.status === 'ok' ? 'ok' : (s.status === 'error' ? 'err' : 'skip');
                        li.textContent = s.name + ': ' + (s.detail || s.status);
                        log.appendChild(li);
                    }});
                    log.style.display = (d.steps && d.steps.length) ? '' : 'none';
                }}
                if (d.status === 'ok') {{
                    showNotification(d.message || 'Committed', 'success');
                    if (d.tree) fillCommitFromGit(d.tree);
                    regenerateCards();
                }} else showNotification(d.message || 'Commit failed', 'error');
                return d;
            }}).catch(() => {{
                if (btn) {{ btn.disabled = false; btn.textContent = label; }}
                showNotification('Commit error', 'error');
            }});
        }}

        function mgCommitPush() {{
            if (!isLocalServer || !mgPath) {{ showNotification('Run server.py for this', 'info'); return; }}
            const files = selectedCommitFiles();
            const msgEl = document.getElementById('mgCommitMsg');
            const message = msgEl ? msgEl.value.trim() : '';
            const include = !!(document.getElementById('mgIncUntracked') && document.getElementById('mgIncUntracked').checked);
            const doPush = !!(document.getElementById('mgDoPush') && document.getElementById('mgDoPush').checked);
            const n = files ? files.length : ((mgGitTree && mgGitTree.default_files) || []).length;
            const pushNote = doPush ? ' and push' : '';
            if (!confirm('Commit ' + n + ' file(s)' + pushNote + (message ? (' as “' + message + '”') : '') + '?')) return;
            runCommitPush(mgPath, {{
                message: message,
                files: files,
                include_untracked: include,
                push: doPush,
            }}, document.getElementById('mgCommitBtn'));
        }}

        function commitNow(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/git-status?path=' + encodeURIComponent(path)).then(r => r.json()).then(git => {{
                if (!git || git.status !== 'ok') {{
                    showNotification((git && git.message) || 'Not a git repo', 'error');
                    return;
                }}
                const n = (git.default_files || []).length;
                const msg = git.suggested_message || 'Update project';
                const pushNote = git.has_remote ? ' and push' : ' (no remote — commit only)';
                if (!confirm('Commit ' + n + ' file(s)' + pushNote + ' as “' + msg + '”?')) return;
                runCommitPush(path, {{
                    message: msg,
                    include_untracked: true,
                    push: !!git.has_remote,
                }}, null);
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        /* Cards are baked into dashboard.html at generation time, so a plain
           reload re-fetches stale HTML. Ask the server to rebuild dashboard.html
           first (re-baking cards from the new catalogue.json / screenshot.png),
           then reload so the refreshed card shows immediately. */
        function reloadWithFreshCards(delay) {{
            const go = () => location.reload();
            if (!isLocalServer) {{ setTimeout(go, delay || 0); return; }}
            fetch('/regenerate-dashboard').then(r => r.json()).then(go).catch(go);
        }}

        /* Fire-and-forget rebuild of dashboard.html (no reload). Used by the
           Manage modal, which updates its own preview live but should still
           keep the baked cards in sync for the next load. */
        function regenerateCards() {{
            if (isLocalServer) fetch('/regenerate-dashboard').catch(() => {{}});
        }}

        /* Inline table generate buttons */
        function autogenCatalogue(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            fetch('/autogen-catalogue?path=' + encodeURIComponent(path)).then(r => r.json()).then(d => {{
                if (d.status === 'ok') {{
                    showNotification('catalogue.json created for ' + path.split('/').pop(), 'success');
                    reloadWithFreshCards();
                }} else showNotification(d.message || 'Failed', 'error');
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function autogenScreenshot(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            showNotification('Capturing screenshot for ' + path.split('/').pop() + '…', 'info');
            fetch('/capture-screenshot?path=' + encodeURIComponent(path)).then(r => r.json()).then(d => {{
                if (d.status === 'ok') {{
                    showNotification('Screenshot saved', 'success');
                    reloadWithFreshCards();
                }} else showNotification(d.message || 'Failed', 'error');
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function autogenBoth(path, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            const name = path.split('/').pop();
            showNotification('Generating catalogue + screenshot for ' + name + '…', 'info');
            fetch('/autogen-catalogue?path=' + encodeURIComponent(path)).then(r => r.json())
                .then(() => fetch('/capture-screenshot?path=' + encodeURIComponent(path)))
                .then(r => r.json()).then(d => {{
                    showNotification('Generated catalogue + screenshot for ' + name, 'success');
                    reloadWithFreshCards();
                }}).catch(() => {{
                    showNotification('catalogue.json created (screenshot may have failed)', 'info');
                    reloadWithFreshCards();
                }});
        }}
        
        /* ---- GitHub repos: open / clone ---- */
        function openGithub(url, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            window.open(url, '_blank');
        }}
        
        function cloneRepo(cloneUrl, name, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py to clone', 'info'); return; }}
            showNotification('Cloning ' + name + ' into ~/' + name + '…', 'info');
            fetch('/clone-repo?url=' + encodeURIComponent(cloneUrl) + '&name=' + encodeURIComponent(name))
                .then(r => r.json()).then(d => {{
                    showNotification(d.status === 'ok' ? (d.message || 'Cloned') : (d.message || 'Clone failed'),
                                     d.status === 'ok' ? 'success' : 'error');
                }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function cloneRepoSetup(cloneUrl, name, event) {{
            if (event) {{ event.preventDefault(); event.stopPropagation(); }}
            if (!isLocalServer) {{ showNotification('Run server.py to clone', 'info'); return; }}
            showNotification('Cloning ' + name + ' + generating catalogue/screenshot… (may take a moment)', 'info');
            fetch('/clone-repo?setup=1&url=' + encodeURIComponent(cloneUrl) + '&name=' + encodeURIComponent(name))
                .then(r => r.json()).then(d => {{
                    showNotification(d.status === 'ok' ? (d.message || 'Cloned + set up') : (d.message || 'Failed'),
                                     d.status === 'ok' ? 'success' : 'error');
                }}).catch(() => showNotification('Error', 'error'));
        }}
        
        /* ---- New project folder in ~ ---- */
        function newProject() {{
            if (!isLocalServer) {{ showNotification('Run server.py to create projects', 'info'); return; }}
            const name = prompt('New project name (folder created in your home directory ~):');
            if (!name) return;
            const clean = name.trim();
            if (!clean) return;
            showNotification('Creating ~/' + clean + '…', 'info');
            fetch('/new-project?name=' + encodeURIComponent(clean)).then(r => r.json()).then(d => {{
                if (d.status === 'ok') {{
                    showNotification('Created ' + d.path + ' — opening in Cursor', 'success');
                }} else {{
                    showNotification(d.message || 'Could not create project', 'error');
                }}
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        /* ---- Refresh GitHub cache ---- */
        function refreshGithub() {{
            if (!isLocalServer) {{ showNotification('Run server.py for this', 'info'); return; }}
            const btn = document.getElementById('ghRefreshBtn');
            if (btn) {{ btn.disabled = true; btn.textContent = '↻ Refreshing…'; }}
            showNotification('Refreshing GitHub repos (this can take a minute)…', 'info');
            fetch('/refresh-github').then(r => r.json()).then(d => {{
                showNotification(d.message || 'GitHub refresh started', d.status === 'ok' ? 'success' : 'error');
                if (btn) {{ btn.disabled = false; btn.textContent = '↻ GitHub'; }}
            }}).catch(() => {{
                if (btn) {{ btn.disabled = false; btn.textContent = '↻ GitHub'; }}
                showNotification('Error', 'error');
            }});
        }}
        
        document.addEventListener('keydown', e => {{ if (e.key === 'Escape') {{ closeManage(); closePorts(); }} }});
        
        (function() {{
            let v = PUBLIC_PAGE ? 'grid' : (HAS_GROUP_ROWS ? 'rows' : 'grid');
            const h = (location.hash || '').replace('#', '');
            if (['rows', 'grid', 'feed', 'table'].includes(h)) {{
                v = h;
            }} else {{
                try {{
                    const saved = localStorage.getItem('dashboardView');
                    if (saved && ['rows', 'grid', 'feed', 'table'].includes(saved)) v = saved;
                    else if (PUBLIC_PAGE) v = 'grid';
                    else if (HAS_GROUP_ROWS) v = 'rows';
                }} catch (e) {{}}
            }}
            switchView(v);
        }})();

        (function initRowDrag() {{
            const wrap = document.getElementById('groupRows');
            if (!wrap) return;
            let draggingId = null;
            let mark = null;

            function ensureMark() {{
                if (!mark) {{
                    mark = document.createElement('div');
                    mark.className = 'row-placeholder';
                }}
                return mark;
            }}
            function clearMark() {{
                mark && mark.remove();
                mark = null;
                wrap.querySelectorAll('.category-row.row-dragging').forEach(r => r.classList.remove('row-dragging'));
            }}
            function placeMark(clientY) {{
                const rows = [...wrap.querySelectorAll('.category-row:not(.row-dragging):not([data-locked])')];
                let target = null;
                for (const row of rows) {{
                    const r = row.getBoundingClientRect();
                    if (clientY < r.top + r.height / 2) {{
                        target = row;
                        break;
                    }}
                }}
                const el = ensureMark();
                if (target) wrap.insertBefore(el, target);
                else wrap.appendChild(el);
            }}
            function persistOrder() {{
                const ids = [...wrap.querySelectorAll('.category-row')].map(r => r.getAttribute('data-group-id'));
                const byId = {{}};
                (REPO_GROUPS.columns || []).forEach(c => {{ byId[String(c.id)] = c; }});
                const seen = new Set();
                const next = [];
                ids.forEach(id => {{
                    if (byId[id] && !seen.has(id)) {{
                        next.push(byId[id]);
                        seen.add(id);
                    }}
                }});
                (REPO_GROUPS.columns || []).forEach(c => {{
                    const id = String(c.id);
                    if (!seen.has(id)) next.push(c);
                }});
                REPO_GROUPS.columns = next;
                persistRepoGroups('Category order saved');
            }}

            wrap.addEventListener('dragstart', e => {{
                const handle = e.target.closest('.row-handle');
                if (!handle) return;
                const row = handle.closest('.category-row');
                draggingId = row.getAttribute('data-group-id');
                e.dataTransfer.setData('text/plain', draggingId);
                e.dataTransfer.effectAllowed = 'move';
                requestAnimationFrame(() => row.classList.add('row-dragging'));
            }});
            wrap.addEventListener('dragend', () => {{
                draggingId = null;
                clearMark();
            }});
            wrap.addEventListener('dragover', e => {{
                if (!draggingId) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                placeMark(e.clientY);
            }});
            wrap.addEventListener('drop', e => {{
                if (!draggingId) return;
                e.preventDefault();
                const row = wrap.querySelector('.category-row.row-dragging');
                const before = mark && mark.nextElementSibling;
                clearMark();
                if (row) wrap.insertBefore(row, before && before.parentNode === wrap ? before : null);
                draggingId = null;
                persistOrder();
            }});
        }})();
        
        function openProject(path, event) {{
            event.preventDefault();
            event.stopPropagation();
            const newWindow = event.ctrlKey || event.metaKey || event.shiftKey;
            
            if (isLocalServer) {{
                fetch('/open-in-cursor?path=' + encodeURIComponent(path) + '&new=' + newWindow)
                    .then(r => r.ok ? showNotification('Opening: ' + path.split('/').pop(), 'success') : showNotification('Error', 'error'))
                    .catch(() => showNotification('Server error', 'error'));
            }} else {{
                if (newWindow) {{
                    navigator.clipboard.writeText('cursor -n "' + path + '"');
                    showNotification('Command copied! Run server.py for click support', 'info');
                }} else {{
                    const link = document.createElement('a');
                    link.href = 'cursor://file/' + path;
                    link.click();
                    showNotification('Opening: ' + path.split('/').pop(), 'success');
                }}
            }}
        }}
        
        function launchApp(path, event) {{
            event.preventDefault();
            event.stopPropagation();
            if (!isLocalServer) {{
                showNotification('Run server.py to launch app servers', 'info');
                return;
            }}
            const name = path.split('/').pop();
            // The server starts the dev server and opens Chrome once it's ready.
            showNotification('Starting ' + name + '… opening in Chrome', 'info');
            fetch('/launch-app?path=' + encodeURIComponent(path))
                .then(r => r.json())
                .then(data => {{
                    if (data.url) {{
                        showNotification('Running ' + data.url + ' → Chrome', 'success');
                        setTimeout(refreshPortStates, 1500);
                    }} else {{
                        showNotification(data.reason || 'No server to run', 'error');
                    }}
                }})
                .catch(() => showNotification('Server error', 'error'));
        }}
        
        function openBoth(path, event) {{
            event.preventDefault();
            event.stopPropagation();
            const name = path.split('/').pop();
            if (!isLocalServer) {{
                // Fall back to just opening Cursor via the URL scheme.
                const link = document.createElement('a');
                link.href = 'cursor://file/' + path;
                link.click();
                showNotification('Opened in Cursor (run server.py to also launch app)', 'info');
                return;
            }}
            const newWindow = event.ctrlKey || event.metaKey || event.shiftKey;
            // The server opens the Cursor window AND opens the app in Chrome when ready.
            showNotification('Opening ' + name + ' in Cursor + app → Chrome', 'info');
            fetch('/open-both?path=' + encodeURIComponent(path) + '&new=' + newWindow)
                .then(r => r.json())
                .then(data => {{
                    if (data.url) {{
                        showNotification('Cursor opened, app running ' + data.url + ' → Chrome', 'success');
                    }} else {{
                        showNotification('Opened in Cursor (no server to run)', 'info');
                    }}
                }})
                .catch(() => showNotification('Server error', 'error'));
        }}
        
        function togglePin(path, event) {{
            event.preventDefault();
            event.stopPropagation();
            if (isLocalServer) {{
                fetch('/toggle-pin?path=' + encodeURIComponent(path))
                    .then(r => r.json())
                    .then(data => {{
                        showNotification(data.pinned ? 'Pinned!' : 'Unpinned', 'success');
                        setTimeout(() => location.reload(), 400);
                    }})
                    .catch(() => showNotification('Error', 'error'));
            }} else {{
                showNotification('Run server.py to pin projects', 'info');
            }}
        }}
        
        function toggleOsxFolders(show) {{
            document.querySelectorAll('#homeFoldersContent .project-card[data-osx="true"]').forEach(card => {{
                card.classList.toggle('visible', show);
            }});
            localStorage.setItem('showOsxFolders', show);
        }}
        
        // Restore toggle state from localStorage
        (function() {{
            const saved = localStorage.getItem('showOsxFolders') === 'true';
            const cb = document.getElementById('showOsxFolders');
            if (cb) {{
                cb.checked = saved;
                if (saved) toggleOsxFolders(true);
            }}
        }})();
        
        function showNotification(msg, type = 'info') {{
            const n = document.createElement('div');
            n.className = 'notification ' + type;
            n.textContent = msg;
            document.body.appendChild(n);
            setTimeout(() => {{ n.style.opacity = '0'; setTimeout(() => n.remove(), 300); }}, 2000);
        }}
        
        const statusEl = document.getElementById('serverStatus');
        if (isLocalServer) {{
            statusEl.textContent = '🟢 Server';
            statusEl.style.background = 'rgba(76,175,80,0.3)';
        }} else {{
            statusEl.textContent = '🟡 File mode';
            statusEl.style.background = 'rgba(255,193,7,0.3)';
        }}
        
        /* ---- Live servers bar ---- */
        function renderLiveBar(servers) {{
            const bar = document.getElementById('liveBar');
            const items = document.getElementById('liveBarItems');
            if (!servers.length) {{ bar.style.display = 'none'; return; }}
            bar.style.display = 'flex';
            items.textContent = '';
            servers.forEach(s => {{
                const name = (s.path || '').split('/').pop();
                const chip = document.createElement('div');
                chip.className = 'live-server-chip';
                const label = document.createElement('span');
                label.textContent = name + ' ';
                const type = document.createElement('span');
                type.style.cssText = 'color:var(--text-faint);font-size:11px;';
                type.textContent = s.type || '';
                label.appendChild(type);
                const link = document.createElement('a');
                link.href = s.url; link.target = '_blank';
                link.title = 'Open ' + s.url; link.textContent = s.url;
                const stop = document.createElement('button');
                stop.className = 'live-server-stop';
                stop.title = 'Stop this server';
                stop.textContent = '✕';
                stop.addEventListener('click', () => stopLiveServer(encodeURIComponent(s.path || '')));
                chip.appendChild(label);
                chip.appendChild(link);
                chip.appendChild(stop);
                items.appendChild(chip);
            }});
        }}
        
        function stopLiveServer(encodedPath) {{
            fetch('/stop-app?path=' + encodedPath).then(r => r.json()).then(() => {{
                showNotification('Stopped server', 'success');
                pollLiveServers();
                setTimeout(refreshPortStates, 600);
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function stopAllServers() {{
            fetch('/status').then(r => r.json()).then(d => {{
                const paths = (d.servers || []).map(s => s.path);
                Promise.all(paths.map(p => fetch('/stop-app?path=' + encodeURIComponent(p)))).then(() => {{
                    showNotification('All servers stopped', 'success');
                    pollLiveServers();
                    setTimeout(refreshPortStates, 600);
                }});
            }}).catch(() => showNotification('Error', 'error'));
        }}
        
        function pollLiveServers() {{
            if (!isLocalServer) return;
            fetch('/status').then(r => r.json()).then(d => {{
                renderLiveBar(d.servers || []);
                markRunningPorts(
                    (d.servers || []).map(s => ({{ port: s.port, listening: true }}))
                );
            }}).catch(() => {{}});
        }}
        
        setInterval(pollLiveServers, 5000);

        /* ---- Legend ---- */
        function toggleLegend() {{
            const p = document.getElementById('legendPanel');
            p.style.display = p.style.display === 'none' ? '' : 'none';
        }}

        /* ---- Shutdown dashboard server ---- */
        function shutdownDashboard() {{
            if (!isLocalServer) {{ showNotification('Not running as a server', 'info'); return; }}
            if (!confirm('Stop the Project Launcher server?')) return;
            fetch('/shutdown').then(() => {{
                document.body.innerHTML = '<div style="font-family:-apple-system,sans-serif;background:#0a0a0b;color:#f5f5f6;height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:16px"><h2>Server stopped</h2><p style="color:#7c7c87">Run <code>python3 server.py</code> in the cursor-launcher folder to restart.</p></div>';
            }}).catch(() => {{}});
        }}

        if (isLocalServer) {{ pollLiveServers(); refreshPortStates(); }}
    </script>
</body>
</html>
'''
    
    return page


def _sanitize_public_html(page: str) -> str:
    """Strip absolute home paths from public output ("/Users/<name>/x" -> "~/x")."""
    home = str(Path.home())
    page = page.replace(home, '~')
    # Catch any other user's absolute macOS home path too.
    page = re.sub(r'/Users/[A-Za-z0-9._-]+', '~', page)
    return page


def _check_public_leaks(page: str):
    """Safety net for --public output. Returns (blocking, warnings).

    Blocking leaks: absolute /Users/ paths, or an exact "owner/name" slug of a
    private repo. Bare private repo names are only warnings, because they can
    coincide with public descriptions/titles (e.g. "magic gems")."""
    blocking, warnings = [], []
    if '/Users/' in page:
        blocking.append("absolute /Users/ path present")
    try:
        cache = github_repos.load_cache()
    except Exception:
        cache = {}
    for full, entry in cache.items():
        if not entry.get('private'):
            continue
        # Word boundary so e.g. private "owner/magicGem" doesn't match the
        # public "owner/magicGemWeb".
        if re.search(re.escape(full) + r'\b', page):
            blocking.append(f"private repo slug: {full}")
            continue
        name = entry.get('name') or ''
        if len(name) >= 4 and re.search(r'\b' + re.escape(name) + r'\b', page):
            warnings.append(f"private repo name appears (verify it's coincidental): {name}")
    return blocking, warnings


def main(argv=None):
    import argparse
    global PUBLIC_MODE

    parser = argparse.ArgumentParser(description="Generate the Cursor project dashboard.")
    parser.add_argument('--public', action='store_true',
                        help="Sanitized shareable dashboard: public GitHub repos only, "
                             "no home-folder scan, no absolute paths. "
                             f"Writes {PUBLIC_OUTPUT_FILE.name} by default. "
                             "Also rewrites repos.json / repo_groups.json as public-only.")
    parser.add_argument('--publish-json', action='store_true',
                        help="Write public-only repos.json and repo_groups.json from "
                             "the gitignored *.local.json files, then exit.")
    parser.add_argument('--output', type=Path, default=None,
                        help="Override the output file path.")
    args = parser.parse_args(argv)

    if args.publish_json and not args.public:
        written = write_public_identity_files()
        print(f"🪪 Wrote public repos.json ({written['public_repos']} repos) "
              f"and repo_groups.json ({written['public_groups']} groups)")
        for path in (REPOS_FILE, GROUPS_FILE):
            blocking, warnings = _check_public_leaks(path.read_text(encoding="utf-8"))
            for w in warnings:
                print(f"⚠️  {path.name}: {w}")
            if blocking:
                print(f"❌ {path.name} still has private data:")
                for leak in blocking:
                    print(f"   - {leak}")
                return
        return

    PUBLIC_MODE = args.public
    out_file = args.output or (PUBLIC_OUTPUT_FILE if PUBLIC_MODE else OUTPUT_FILE)
    if PUBLIC_MODE:
        print("🌐 PUBLIC mode: only repos public on GitHub, no home scan, no local paths")
        projects = []
    else:
        print("🔍 Scanning CODING folder for all projects...")
        projects = find_all_projects()

        if not projects:
            print("❌ No projects found!")
            return

        print(f"✅ Found {len(projects)} projects")

        # Stats
        pinned = [p for p in projects if p['is_pinned']]
        with_catalogue = [p for p in projects if p['has_catalogue']]
        cursor_recent = [p for p in projects if p['cursor_recent_idx'] is not None]

        print(f"📌 {len(pinned)} pinned")
        print(f"📋 {len(with_catalogue)} with catalogue.json")
        print(f"🕐 {len(cursor_recent)} in Cursor's recent")

    print("📝 Generating HTML dashboard...")
    html = generate_html(projects)

    if PUBLIC_MODE:
        written = write_public_identity_files()
        print(f"🪪 Wrote public repos.json ({written['public_repos']} repos) "
              f"and repo_groups.json ({written['public_groups']} groups)")
        html = _sanitize_public_html(html)
        blocking, warnings = _check_public_leaks(html)
        for path in (REPOS_FILE, GROUPS_FILE):
            extra_b, extra_w = _check_public_leaks(path.read_text(encoding="utf-8"))
            blocking.extend(f"{path.name}: {x}" for x in extra_b)
            warnings.extend(f"{path.name}: {x}" for x in extra_w)
        for w in warnings:
            print(f"⚠️  {w}")
        if blocking:
            print("❌ Public dashboard NOT written — private data detected:")
            for leak in blocking:
                print(f"   - {leak}")
            return
    
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ Dashboard generated: {out_file}")
    
    # Category summary
    print(f"\n📊 Projects by category:")
    by_cat = {}
    for p in projects:
        cat = p['category']
        by_cat[cat] = by_cat.get(cat, 0) + 1
    
    for cat in MAIN_CATEGORIES + ["OTHER"]:
        if cat in by_cat:
            print(f"   {cat}: {by_cat[cat]}")


if __name__ == '__main__':
    main()
