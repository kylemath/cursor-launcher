#!/usr/bin/env python3
"""
GitHub repo integration for the Cursor Project Launcher.

Uses the authenticated GitHub CLI (`gh`) to list ALL of your repos (including
private ones), and pulls each repo's catalogue.json + screenshot.png so they can
appear in the dashboard alongside local projects — without cloning them.

Everything is cached in github_cache.json (keyed by each repo's pushedAt) and
screenshots in gh_assets/, so only changed repos are re-fetched.

CLI:
    python3 github_repos.py refresh     # rebuild the cache (the slow part)
    python3 github_repos.py list        # print cached remote projects
    python3 github_repos.py export-repos  # write repos.local.json (all) + public repos.json
    python3 github_repos.py public      # list public repos (API; no private cache write)
"""

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import publish_repo as pr

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "github_cache.json"
ASSETS_DIR = BASE_DIR / "gh_assets"
GH_USER = "kylemath"
REPOS_FILE = BASE_DIR / "repos.json"
REPOS_LOCAL_FILE = BASE_DIR / "repos.local.json"


def _run(args: List[str], timeout: int = 60) -> Optional[str]:
    if args and args[0] == "gh":
        exe = pr.find_gh()
        if not exe:
            return None
        args = [exe, *args[1:]]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return None


def gh_available() -> bool:
    return bool(pr.find_gh()) and _run(["gh", "auth", "token"], timeout=10) is not None


def _rel_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        for unit, div in (("year", 31536000), ("month", 2592000), ("week", 604800),
                          ("day", 86400), ("hour", 3600), ("minute", 60)):
            v = int(secs // div)
            if v >= 1:
                return f"{v} {unit}{'s' if v > 1 else ''} ago"
        return "just now"
    except Exception:
        return ""


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def load_cache() -> Dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: Dict):
    try:
        CACHE_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _gh_contents_text(full: str, path: str) -> Optional[str]:
    """Fetch a text file from a repo via the contents API (works for private)."""
    raw = _run(["gh", "api", f"repos/{full}/contents/{path}", "--jq", ".content"], timeout=20)
    if not raw or not raw.strip():
        return None
    try:
        return base64.b64decode(raw.strip()).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _gh_download(full: str, path: str, dest: Path) -> Optional[Path]:
    """Download a binary file (e.g. screenshot.png) and resize small."""
    raw = _run(["gh", "api", f"repos/{full}/contents/{path}", "--jq", ".content"], timeout=30)
    if not raw or not raw.strip():
        return None
    try:
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(base64.b64decode(raw.strip()))
        # Resize to max 900px to keep the dashboard light
        subprocess.run(["sips", "-Z", "900", str(dest), "--out", str(dest)],
                       capture_output=True, timeout=15)
        return dest
    except Exception:
        return None


def fetch_and_cache(progress=None) -> Dict:
    """Rebuild the GitHub cache. Returns the cache dict."""
    if not gh_available():
        if progress:
            progress("gh CLI not authenticated — run `gh auth login`")
        return load_cache()

    listing = _run([
        "gh", "repo", "list", GH_USER, "--limit", "500", "--json",
        "name,isPrivate,url,description,pushedAt,updatedAt,defaultBranchRef,"
        "homepageUrl,isFork,repositoryTopics,primaryLanguage",
    ], timeout=120)
    if not listing:
        if progress:
            progress("Could not list repos")
        return load_cache()

    repos = json.loads(listing)
    old = load_cache()
    new: Dict = {}
    total = len(repos)
    fetched = 0
    for i, r in enumerate(repos):
        name = r["name"]
        full = f"{GH_USER}/{name}"
        pushed = r.get("pushedAt") or ""
        prev = old.get(full)
        # Reuse cache if the repo hasn't been pushed to since last time
        if prev and prev.get("pushedAt") == pushed and "catalogue" in prev:
            new[full] = prev
            continue

        fetched += 1
        entry = {
            "name": name,
            "full": full,
            "private": bool(r.get("isPrivate")),
            "url": r.get("url"),
            "clone_url": (r.get("url") or "") + ".git",
            "description": r.get("description") or "",
            "pushedAt": pushed,
            "updatedAt": r.get("updatedAt"),
            "default_branch": (r.get("defaultBranchRef") or {}).get("name") or "main",
            "homepage": r.get("homepageUrl") or "",
            "fork": bool(r.get("isFork")),
            "language": (r.get("primaryLanguage") or {}).get("name"),
            "topics": [t.get("name") for t in (r.get("repositoryTopics") or []) if t.get("name")],
            "catalogue": None,
            "screenshot": None,
        }
        # Pull catalogue.json (only showcase repos have one)
        cat_text = _gh_contents_text(full, "catalogue.json")
        if cat_text:
            try:
                entry["catalogue"] = json.loads(cat_text)
            except Exception:
                entry["catalogue"] = None
            # Only bother with a screenshot when there's a catalogue
            shot = _gh_download(full, "screenshot.png", ASSETS_DIR / f"{name}.png")
            entry["screenshot"] = str(shot) if shot else None
        new[full] = entry
        if progress and fetched % 10 == 0:
            progress(f"Fetched {i + 1}/{total} repos…")

    _save_cache(new)
    if progress:
        progress(f"Done — {total} repos ({fetched} refreshed).")
    return new


def _github_token() -> str:
    return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()


def _http_get(url: str, timeout: int = 20) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "cursor-launcher",
    })
    token = _github_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def list_public_repos() -> List[Dict]:
    """Public repos for GH_USER via the REST API (no private names)."""
    repos: List[Dict] = []
    page = 1
    while page <= 10:
        raw = _http_get(
            f"https://api.github.com/users/{GH_USER}/repos"
            f"?per_page=100&type=owner&sort=pushed&page={page}"
        )
        if not raw:
            break
        try:
            batch = json.loads(raw.decode("utf-8"))
        except Exception:
            break
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return repos


def _raw_json(full: str, branch: str, path: str) -> Optional[Dict]:
    raw = _http_get(
        f"https://raw.githubusercontent.com/{full}/{branch}/{path}", timeout=15)
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_public_cache(progress=None) -> Dict:
    """Public-only cache. Does not write github_cache.json (may contain private repos)."""
    listing = list_public_repos()
    if progress:
        progress(f"Listed {len(listing)} public repos")
    new: Dict = {}
    pending = []
    for r in listing:
        if r.get("private"):
            continue
        name = r.get("name") or ""
        if not name:
            continue
        full = f"{GH_USER}/{name}"
        branch = r.get("default_branch") or "main"
        pushed = r.get("pushed_at") or ""
        entry = {
            "name": name,
            "full": full,
            "private": False,
            "url": r.get("html_url") or f"https://github.com/{full}",
            "clone_url": r.get("clone_url") or f"https://github.com/{full}.git",
            "description": r.get("description") or "",
            "pushedAt": pushed,
            "updatedAt": r.get("updated_at"),
            "default_branch": branch,
            "homepage": r.get("homepage") or "",
            "fork": bool(r.get("fork")),
            "language": r.get("language") if isinstance(r.get("language"), str) else None,
            "topics": r.get("topics") or [],
            "catalogue": None,
            "screenshot": None,
        }
        new[full] = entry
        pending.append((full, branch))

    def _load(item):
        full, branch = item
        return full, _raw_json(full, branch, "catalogue.json")

    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_load, item) for item in pending]
        for fut in as_completed(futures):
            full, cat = fut.result()
            if cat:
                new[full]["catalogue"] = cat
            done += 1
            if progress and done % 20 == 0:
                progress(f"Fetched catalogues {done}/{len(pending)}…")
    if progress:
        progress(f"Done — {len(new)} public repos.")
    return new


def cache_from_repos_json() -> Dict:
    """Minimal public cache from the committed repos.json (names + descriptions)."""
    if not REPOS_FILE.exists():
        return {}
    try:
        data = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    new: Dict = {}
    for repo in data.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        if str(repo.get("visibility") or "").lower() == "private":
            continue
        name = repo.get("name") or ""
        if not name:
            continue
        full = f"{GH_USER}/{name}"
        new[full] = {
            "name": name,
            "full": full,
            "private": False,
            "url": f"https://github.com/{full}",
            "clone_url": f"https://github.com/{full}.git",
            "description": repo.get("description") or "",
            "pushedAt": "",
            "updatedAt": None,
            "default_branch": "main",
            "homepage": "",
            "fork": False,
            "language": None,
            "topics": [],
            "catalogue": None,
            "screenshot": None,
        }
    return new


def _projects_from_entries(cache: Dict,
                           local_remotes: Optional[Set[str]] = None,
                           include_forks: bool = False,
                           only_public: bool = False) -> List[Dict]:
    """Turn a github_cache-shaped dict into dashboard project dicts."""
    local_remotes = {r.lower() for r in (local_remotes or set())}
    projects = []
    for full, e in cache.items():
        if not isinstance(e, dict):
            continue
        if only_public and e.get("private"):
            continue
        if not include_forks and e.get("fork"):
            continue
        if full.lower() in local_remotes:
            continue
        cat = e.get("catalogue") or {}
        pushed = e.get("pushedAt") or ""
        private = e.get("private")
        branch = e.get("default_branch") or "main"
        raw_base = f"https://raw.githubusercontent.com/{full}/{branch}/"
        projects.append({
            "source": "github",
            "id": e["name"],
            "title": cat.get("title") or e["name"],
            "oneLiner": cat.get("oneLiner") or cat.get("description") or e.get("description") or "",
            "description": cat.get("description") or e.get("description") or "",
            "categories": cat.get("categories", []),
            "tags": cat.get("tags", []),
            "kind": cat.get("kind", "project"),
            "status": cat.get("status", ""),
            "path": "",
            "rel_path": full,
            "screenshot_path": e.get("screenshot"),
            "screenshot_url": cat.get("screenshot"),
            "raw_base": raw_base,
            "category": "GITHUB",
            "mtime": _ts(pushed),
            "has_catalogue": bool(e.get("catalogue")),
            "is_pinned": False,
            "cursor_recent_idx": None,
            "cursor_url": "",
            "runnable": False,
            "server_type": None,
            "server_url": None,
            "server_port": None,
            "port_designated": False,
            "port_conflict": False,
            "has_server_block": bool(cat.get("server")),
            "git": {
                "is_repo": True,
                "has_remote": True,
                "visibility": "private" if private else "public",
                "last_commit_rel": _rel_time(pushed),
                "last_commit_iso": pushed,
                "last_commit_ts": _ts(pushed),
                "uncommitted": 0,
                "branches": [],
                "current_branch": e.get("default_branch"),
                "file_count": 0,
            },
            "last_commit_ts": _ts(pushed),
            "last_commit_rel": _rel_time(pushed),
            "last_commit_subject": None,
            "recent_subjects": [],
            "private": private,
            "clone_url": e.get("clone_url"),
            "html_url": e.get("url"),
            "language": e.get("language"),
            "homepage": cat.get("demoUrl") or e.get("homepage") or "",
        })
    return projects


def load_remote_projects(local_remotes: Optional[Set[str]] = None,
                         include_forks: bool = False) -> List[Dict]:
    """Return remote-only repos (not cloned locally) as dashboard project dicts."""
    return _projects_from_entries(load_cache(), local_remotes=local_remotes,
                                  include_forks=include_forks)


def load_public_projects(progress=None) -> List[Dict]:
    """All public GitHub repos as dashboard projects. Never includes private names.

    Prefers the local github_cache.json (already fetched) so a laptop build is
    fast. In CI the cache is absent, so this hits the public GitHub API.
    Does not write github_cache.json.
    """
    cache = {k: v for k, v in load_cache().items()
             if isinstance(v, dict) and not v.get("private")}
    if not cache:
        cache = fetch_public_cache(progress=progress)
    if not cache:
        cache = cache_from_repos_json()
        if progress and cache:
            progress(f"Fell back to repos.json ({len(cache)} public names)")
    return _projects_from_entries(
        cache, local_remotes=set(), include_forks=False, only_public=True)


def export_repos_list() -> Dict:
    """Write repos.local.json (all visibilities) and public-only repos.json."""
    raw = _run([
        "gh", "repo", "list", "--limit", "1000",
        "--json", "name,description,visibility",
    ], timeout=120)
    if not raw:
        raise SystemExit("gh repo list failed — is `gh auth login` done?")
    listed = json.loads(raw)
    repos = []
    for item in listed:
        repos.append({
            "name": item.get("name") or "",
            "description": item.get("description") or "",
            "visibility": str(item.get("visibility") or "").lower(),
        })
    public_repos = [r for r in repos if r["visibility"] == "public"]
    private_repos = [r for r in repos if r["visibility"] == "private"]
    local = {
        "count": len(repos),
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "owner": GH_USER,
        "private_count": len(private_repos),
        "public_count": len(public_repos),
        "repos": repos,
    }
    REPOS_LOCAL_FILE.write_text(json.dumps(local, ensure_ascii=False) + "\n", encoding="utf-8")
    public = {
        "count": len(public_repos),
        "generated": datetime.now().strftime("%Y-%m-%d"),
        "owner": GH_USER,
        "public_count": len(public_repos),
        "repos": public_repos,
    }
    REPOS_FILE.write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    return {
        "all": len(repos),
        "public": len(public_repos),
        "private": len(private_repos),
        "local": str(REPOS_LOCAL_FILE),
        "public_file": str(REPOS_FILE),
    }


def _main(argv):
    if not argv or argv[0] == "refresh":
        fetch_and_cache(progress=lambda m: print(m, flush=True))
    elif argv[0] == "list":
        for p in load_remote_projects():
            print(f"  {'🔒' if p['private'] else '🌐'} {p['title']:<30} {p['last_commit_rel']}")
    elif argv[0] == "export-repos":
        info = export_repos_list()
        print(f"Wrote {info['all']} repos ({info['public']} public, "
              f"{info['private']} private) to {info['local']}")
        print(f"Wrote public-only list ({info['public']}) to {info['public_file']}")
    elif argv[0] == "public":
        for p in load_public_projects(progress=lambda m: print(m, flush=True)):
            print(f"  🌐 {p['title']:<30} {p['last_commit_rel']}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
