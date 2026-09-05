#!/usr/bin/env python3
"""
Non-interactive publish flow, ported from kylemath/gitBash (`gir`).

Creates (or updates) a local git repo, catalogue.json, screenshot hook-in,
GitHub remote, visibility, and optional GitHub Pages — no prompts, no AI.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional


DEFAULT_GITIGNORE = """# OS generated files
.DS_Store
.DS_Store?
._*
.Spotlight-V100
.Trashes
ehthumbs.db
Thumbs.db

# Editor files
.vscode/
.idea/
*.swp
*.swo
*~

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
.venv
pip-log.txt
pip-delete-this-directory.txt

# Node
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*

# Logs
*.log
logs/
"""

SECRET_NAME_RE = re.compile(
    r'(secret|password|credentials|\.pem$|\.key$|(^|/)\.env(\.|$))',
    re.IGNORECASE,
)
SKIP_IGNORE_NAMES = {
    'catalogue.json', 'package.json', 'package-lock.json', 'tsconfig.json',
    'composer.json', 'pyproject.toml',
}
SCREENSHOT_CANDIDATES = (
    'screenshot.png', 'screenshot.jpg', 'screenshot.jpeg',
    'Screenshot.png', 'Screenshot.jpg', 'Screenshot.jpeg',
)
BACKEND_PY_RE = re.compile(r'(flask|fastapi|gradio|streamlit|django|uvicorn)', re.I)
BACKEND_NODE_RE = re.compile(r'(express|koa|fastify|nest|"start".*node|server\.js)', re.I)
COMMON_OSX_FOLDERS = {
    'Applications', 'Desktop', 'Documents', 'Downloads', 'Library',
    'Movies', 'Music', 'Pictures', 'Public', 'Dropbox',
    'OneDrive', 'Google Drive', 'GoogleDrive', 'Creative Cloud Files',
    'Sites', 'iCloud Drive', 'Parallels', 'VirtualBox VMs',
}
LARGE_FILE_BYTES = 10 * 1024 * 1024


def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _git(path: str, args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return _run(['git', '-C', path, *args], timeout=timeout)


def is_allowed_project_path(path: str) -> bool:
    """Only first-class project folders under ~ (not ~ itself or system dirs)."""
    if not path:
        return False
    try:
        home = Path.home().resolve()
        p = Path(path).expanduser().resolve()
    except Exception:
        return False
    if not p.is_dir():
        return False
    if p == home:
        return False
    try:
        p.relative_to(home)
    except ValueError:
        return False
    if p.name in COMMON_OSX_FOLDERS or p.name.startswith('.'):
        return False
    return True


def detect_kind(path: str) -> Dict:
    p = Path(path)
    backend = False
    backend_type = ''
    suggestions = ''

    req = p / 'requirements.txt'
    if req.is_file():
        try:
            text = req.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            text = ''
        if BACKEND_PY_RE.search(text):
            backend = True
            backend_type = 'Python backend app'
            suggestions = 'Render.com, Railway.app, or Hugging Face Spaces'

    if not backend:
        try:
            for py in p.glob('*.py'):
                try:
                    if BACKEND_PY_RE.search(py.read_text(encoding='utf-8', errors='ignore')):
                        backend = True
                        backend_type = 'Python backend app'
                        suggestions = 'Render.com, Railway.app, or Hugging Face Spaces'
                        break
                except Exception:
                    continue
        except Exception:
            pass

    pkg = p / 'package.json'
    if pkg.is_file() and not backend:
        try:
            text = pkg.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            text = ''
        if BACKEND_NODE_RE.search(text):
            backend = True
            backend_type = 'Node.js backend app'
            suggestions = 'Render.com, Railway.app, Heroku, or Vercel'

    static = (p / 'index.html').is_file() or (p / 'index.htm').is_file()
    return {
        'backend': backend,
        'backend_type': backend_type,
        'static': static,
        'hosting_suggestions': suggestions,
    }


def find_screenshot(path: str) -> Optional[str]:
    for name in SCREENSHOT_CANDIDATES:
        if (Path(path) / name).is_file():
            return name
    return None


def gh_status() -> Dict:
    if not shutil.which('gh'):
        return {'ok': False, 'message': 'GitHub CLI (gh) is not installed'}
    try:
        r = _run(['gh', 'auth', 'status'], timeout=10)
    except Exception as e:
        return {'ok': False, 'message': str(e)}
    if r.returncode != 0:
        return {'ok': False, 'message': 'GitHub CLI not authenticated — run gh auth login'}
    return {'ok': True, 'message': 'gh ready'}


def current_remote(path: str) -> Optional[str]:
    if not (Path(path) / '.git').exists():
        return None
    r = _git(path, ['remote', 'get-url', 'origin'])
    url = (r.stdout or '').strip()
    return url or None


def parse_github_remote(url: str):
    if not url:
        return None, None
    m = re.search(r'github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$', url.strip())
    if m:
        return m.group(1), m.group(2)
    return None, None


def sanitize_repo_name(name: str) -> str:
    """GitHub repo name: letters, digits, dot, underscore, hyphen."""
    raw = (name or '').strip()
    raw = raw.replace(' ', '-')
    cleaned = re.sub(r'[^A-Za-z0-9._-]', '', raw)
    cleaned = re.sub(r'[-_.]{2,}', '-', cleaned).strip('.-_')
    return cleaned[:100]


def suggested_repo_name(path: str) -> str:
    """Folder name, or catalogue id if it sanitizes to something usable."""
    folder = Path(path).name
    cat = Path(path) / 'catalogue.json'
    if cat.is_file():
        try:
            data = json.loads(cat.read_text(encoding='utf-8')) or {}
            for key in ('id', 'title'):
                candidate = sanitize_repo_name(str(data.get(key) or ''))
                if candidate:
                    return candidate
        except Exception:
            pass
    return sanitize_repo_name(folder) or folder


def recommended_defaults(path: str) -> Dict:
    kind = detect_kind(path)
    pages = bool(kind['static'] and not kind['backend'])
    visibility = 'public' if pages else 'private'
    is_repo = (Path(path) / '.git').exists()
    remote = current_remote(path)
    _, remote_repo = parse_github_remote(remote or '')
    return {
        'visibility': visibility,
        'pages': pages,
        'is_repo': is_repo,
        'has_remote': bool(remote),
        'remote_url': remote,
        'kind': kind,
        'repo_name': remote_repo or suggested_repo_name(path),
        'folder_name': Path(path).name,
        'has_catalogue': (Path(path) / 'catalogue.json').is_file(),
        'has_screenshot': bool(find_screenshot(path)),
        'has_readme': (Path(path) / 'README.md').is_file(),
    }


def preview(path: str) -> Dict:
    if not is_allowed_project_path(path):
        return {'status': 'error', 'message': 'Invalid project path'}
    defaults = recommended_defaults(path)
    gh = gh_status()
    owner, repo = parse_github_remote(defaults.get('remote_url') or '')
    action = 'update' if defaults['has_remote'] else 'create'
    return {
        'status': 'ok',
        'action': action,
        'defaults': defaults,
        'gh': gh,
        'owner': owner,
        'repo': repo,
        'summary': _preview_summary(defaults, action),
    }


def _preview_summary(defaults: Dict, action: str) -> str:
    vis = defaults['visibility']
    pages = 'with GitHub Pages' if defaults['pages'] else 'no Pages'
    repo = defaults.get('repo_name') or defaults.get('folder_name') or 'this folder'
    if action == 'create':
        return f"Create GitHub repo “{repo}” as {vis}, {pages}"
    return f"Update existing remote “{repo}”, keep/set {vis}, {pages}"


def ensure_gitignore(path: str) -> bool:
    dest = Path(path) / '.gitignore'
    if dest.is_file():
        return False
    dest.write_text(DEFAULT_GITIGNORE, encoding='utf-8')
    return True


def ensure_cursor_dir(path: str) -> bool:
    cursor = Path(path) / '.cursor'
    keep = cursor / '.gitkeep'
    created = False
    if not cursor.is_dir():
        cursor.mkdir(exist_ok=True)
        created = True
    if not keep.is_file():
        keep.write_text('', encoding='utf-8')
        created = True
    return created


def _gitignore_lines(path: str) -> List[str]:
    gi = Path(path) / '.gitignore'
    if not gi.is_file():
        return []
    return gi.read_text(encoding='utf-8', errors='ignore').splitlines()


def _already_ignored(path: str, rel: str) -> bool:
    lines = _gitignore_lines(path)
    name = Path(rel).name
    return any(line.strip() in {rel, f'./{rel}', name, f'/{rel}'} for line in lines)


def auto_ignore_secrets(path: str) -> List[str]:
    """Ignore obvious secrets and files >10MB. Does not prompt about yaml/json."""
    added: List[str] = []
    root = Path(path)
    candidates: List[Path] = []
    for depth_glob in ('*', '*/*', '*/*/*'):
        for hit in root.glob(depth_glob):
            if not hit.is_file():
                continue
            rel = str(hit.relative_to(root))
            if rel.startswith('.git/') or '/.git/' in rel:
                continue
            if hit.name in SKIP_IGNORE_NAMES:
                continue
            try:
                size = hit.stat().st_size
            except OSError:
                continue
            if SECRET_NAME_RE.search(rel) or size > LARGE_FILE_BYTES:
                candidates.append(hit)

    if not candidates:
        return added

    gi = Path(path) / '.gitignore'
    extra: List[str] = []
    for hit in candidates:
        rel = str(hit.relative_to(root))
        if _already_ignored(path, rel):
            continue
        extra.append(rel)
        added.append(rel)

    if extra:
        existing = gi.read_text(encoding='utf-8', errors='ignore') if gi.is_file() else ''
        block = '\n# Files added by launcher publish\n' + '\n'.join(extra) + '\n'
        gi.write_text(existing.rstrip() + '\n' + block, encoding='utf-8')
    return added


def pretty_title(name: str) -> str:
    pretty = re.sub(r'[-_]+', ' ', name)
    pretty = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', pretty).strip()
    return pretty.title() if pretty else name


def ensure_readme(path: str, name: Optional[str] = None, description: str = '') -> bool:
    dest = Path(path) / 'README.md'
    if dest.is_file():
        return False
    title = pretty_title(name or Path(path).name)
    desc = description.strip() or f'{title} project.'
    dest.write_text(
        f"# {title}\n\n{desc}\n\n## Getting Started\n\n"
        "Open this folder in Cursor and run the project from there.\n",
        encoding='utf-8',
    )
    return True


def embed_screenshot_in_readme(path: str) -> bool:
    shot = find_screenshot(path)
    readme = Path(path) / 'README.md'
    if not shot or not readme.is_file():
        return False
    text = readme.read_text(encoding='utf-8', errors='ignore')
    if shot in text:
        return False
    block = (
        f"\n## Preview\n\n"
        f'<p align="center">\n'
        f'  <img src="{shot}" alt="Project screenshot" width="720" />\n'
        f"</p>\n"
    )
    readme.write_text(text.rstrip() + '\n' + block, encoding='utf-8')
    return True


def add_pages_link_to_readme(path: str, pages_url: str) -> bool:
    readme = Path(path) / 'README.md'
    if not readme.is_file() or not pages_url:
        return False
    text = readme.read_text(encoding='utf-8', errors='ignore')
    if 'Live Demo' in text or pages_url in text:
        return False
    lines = text.splitlines()
    insert_at = 1 if lines else 0
    if insert_at < len(lines) and lines[insert_at].strip() == '':
        insert_at += 1
    demo = f"\n🚀 **[Live Demo]({pages_url})** 🚀\n"
    lines[insert_at:insert_at] = demo.splitlines()
    readme.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return True


def ensure_git(path: str) -> Dict:
    if (Path(path) / '.git').exists():
        return {'created': False}
    r = _git(path, ['init', '-b', 'main'])
    if r.returncode != 0:
        r = _git(path, ['init'])
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or 'git init failed').strip()[:300])
        _git(path, ['branch', '-M', 'main'])
    return {'created': True}


def commit_staged(path: str, message: str) -> bool:
    """Commit the index only — does not `git add -A`."""
    staged = _git(path, ['diff', '--cached', '--quiet'])
    if staged.returncode == 0:
        return False
    r = _git(path, ['commit', '-m', message])
    if r.returncode != 0:
        err = (r.stderr or r.stdout or 'git commit failed').strip()
        raise RuntimeError(err[:400])
    return True


def commit_if_needed(path: str, message: str) -> bool:
    _git(path, ['add', '-A'])
    return commit_staged(path, message)


def _step(steps: List[Dict], name: str, status: str, detail: str = ''):
    steps.append({'name': name, 'status': status, 'detail': detail})


def _gh_repo_view(path: str) -> Dict:
    r = _run(
        ['gh', 'repo', 'view', '--json', 'url,name,owner,visibility,defaultBranchRef'],
        cwd=path, timeout=20,
    )
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout or '{}')
    except json.JSONDecodeError:
        return {}
    owner = (data.get('owner') or {}).get('login')
    branch = ((data.get('defaultBranchRef') or {}).get('name')) or 'main'
    return {
        'url': data.get('url'),
        'name': data.get('name'),
        'owner': owner,
        'visibility': (data.get('visibility') or '').lower(),
        'branch': branch,
    }


def _create_github_repo(path: str, name: str, visibility: str) -> Dict:
    flag = '--public' if visibility == 'public' else '--private'
    r = _run(
        ['gh', 'repo', 'create', name, flag, '--source=.', '--remote=origin', '--push'],
        cwd=path, timeout=180,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or 'gh repo create failed').strip()[:400])
    return _gh_repo_view(path)


def _push(path: str) -> None:
    branch = (_git(path, ['branch', '--show-current']).stdout or 'main').strip() or 'main'
    r = _git(path, ['push', '-u', 'origin', branch], timeout=120)
    if r.returncode != 0:
        r = _git(path, ['push'], timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or 'git push failed').strip()[:400])


def _set_visibility(path: str, visibility: str) -> Optional[str]:
    r = _run(['gh', 'repo', 'edit', f'--visibility={visibility}', '--accept-visibility-change-consequences'],
             cwd=path, timeout=30)
    if r.returncode != 0:
        return (r.stderr or r.stdout or 'could not change visibility').strip()[:200]
    return None


def enable_pages(path: str, owner: str, repo: str, branch: str = 'main') -> Dict:
    pages_url = f'https://{owner}.github.io/{repo}'
    r = _run(
        ['gh', 'api', '-X', 'POST', f'repos/{owner}/{repo}/pages',
         '-f', f'source[branch]={branch}', '-f', 'source[path]=/'],
        cwd=path, timeout=30,
    )
    already = r.returncode != 0 and (
        'already exists' in (r.stderr or '').lower()
        or '409' in (r.stderr or '')
        or '"status":"already' in (r.stdout or '').lower()
    )
    if r.returncode != 0 and not already:
        # PATCH in case Pages exists with a different source
        r2 = _run(
            ['gh', 'api', '-X', 'PUT', f'repos/{owner}/{repo}/pages',
             '-f', f'source[branch]={branch}', '-f', 'source[path]=/'],
            cwd=path, timeout=30,
        )
        if r2.returncode != 0 and not already:
            return {
                'ok': False,
                'url': pages_url,
                'message': (r.stderr or r.stdout or r2.stderr or 'Pages API failed').strip()[:300],
            }
    _run(['gh', 'repo', 'edit', f'--homepage={pages_url}'], cwd=path, timeout=20)
    return {'ok': True, 'url': pages_url, 'message': 'GitHub Pages enabled'}


def _patch_catalogue_after_publish(path: str, pages_url: Optional[str]):
    cat_path = Path(path) / 'catalogue.json'
    data = {}
    if cat_path.is_file():
        try:
            data = json.loads(cat_path.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    shot = find_screenshot(path)
    if shot and not data.get('screenshot'):
        data['screenshot'] = f'./{shot}'
    if pages_url and not data.get('demoUrl'):
        data['demoUrl'] = pages_url
    if data.get('status') in (None, '', 'active'):
        data['status'] = 'published'
    if data:
        cat_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def publish(
    path: str,
    visibility: str = 'private',
    pages: bool = False,
    repo_name: Optional[str] = None,
    commit_message: Optional[str] = None,
    capture_screenshot: Optional[Callable[[str], Dict]] = None,
    autogen_catalogue: Optional[Callable[[str], Dict]] = None,
) -> Dict:
    """Run the full publish pipeline. Returns {status, steps, url, pages_url, message}."""
    steps: List[Dict] = []
    path = str(Path(path).expanduser())
    if not is_allowed_project_path(path):
        return {'status': 'error', 'message': 'Invalid project path', 'steps': steps}

    visibility = 'public' if str(visibility).lower() == 'public' else 'private'
    name = sanitize_repo_name(repo_name or '') or suggested_repo_name(path)
    if not name:
        return {'status': 'error', 'message': 'Invalid GitHub repo name', 'steps': steps}
    has_remote = bool(current_remote(path))
    message = commit_message or ('chore: publish from launcher' if has_remote else 'init commit')

    gh = gh_status()
    if not gh['ok']:
        return {'status': 'error', 'message': gh['message'], 'steps': steps}

    try:
        created = ensure_git(path)
        _step(steps, 'git', 'ok', 'initialized' if created['created'] else 'already a repo')

        if ensure_gitignore(path):
            _step(steps, 'gitignore', 'ok', 'created default .gitignore')
        else:
            _step(steps, 'gitignore', 'skip', 'already present')

        if ensure_cursor_dir(path):
            _step(steps, 'cursor', 'ok', 'added .cursor/.gitkeep')
        else:
            _step(steps, 'cursor', 'skip', 'already present')

        ignored = auto_ignore_secrets(path)
        if ignored:
            _step(steps, 'secrets', 'ok', f'ignored {len(ignored)} file(s): ' + ', '.join(ignored[:8]))
        else:
            _step(steps, 'secrets', 'skip', 'nothing to ignore')

        one_liner = ''
        cat_file = Path(path) / 'catalogue.json'
        if cat_file.is_file():
            try:
                one_liner = (json.loads(cat_file.read_text(encoding='utf-8')) or {}).get('oneLiner') or ''
            except Exception:
                one_liner = ''
        if ensure_readme(path, name, one_liner):
            _step(steps, 'readme', 'ok', 'created README.md')
        else:
            _step(steps, 'readme', 'skip', 'already present')

        if capture_screenshot and not find_screenshot(path):
            shot = capture_screenshot(path) or {}
            if shot.get('status') == 'ok':
                _step(steps, 'screenshot', 'ok', shot.get('file') or 'screenshot.png')
            else:
                _step(steps, 'screenshot', 'skip', shot.get('message') or 'no page to capture')
        elif find_screenshot(path):
            _step(steps, 'screenshot', 'skip', 'already present')
        else:
            _step(steps, 'screenshot', 'skip', 'no capture function / not runnable')

        if autogen_catalogue:
            cat = autogen_catalogue(path) or {}
            if cat.get('status') == 'ok':
                _step(steps, 'catalogue', 'ok', 'catalogue.json written')
            else:
                _step(steps, 'catalogue', 'skip', cat.get('message') or 'autogen failed')
        else:
            _step(steps, 'catalogue', 'skip', 'no autogen function')

        if embed_screenshot_in_readme(path):
            _step(steps, 'readme-shot', 'ok', 'embedded screenshot in README')
        else:
            _step(steps, 'readme-shot', 'skip', 'no new screenshot to embed')

        if commit_if_needed(path, message):
            _step(steps, 'commit', 'ok', message)
        else:
            _step(steps, 'commit', 'skip', 'nothing to commit')

        repo_info: Dict = {}
        if not current_remote(path):
            repo_info = _create_github_repo(path, name, visibility)
            _step(steps, 'github', 'ok', repo_info.get('url') or f'created {visibility} repo')
        else:
            vis_err = _set_visibility(path, visibility)
            if vis_err:
                _step(steps, 'visibility', 'skip', vis_err)
            else:
                _step(steps, 'visibility', 'ok', visibility)
            _push(path)
            repo_info = _gh_repo_view(path)
            _step(steps, 'push', 'ok', repo_info.get('url') or 'pushed to origin')

        pages_url = None
        if pages:
            owner = repo_info.get('owner')
            repo = repo_info.get('name') or name
            branch = repo_info.get('branch') or 'main'
            if not owner:
                owner, repo_from_remote = parse_github_remote(current_remote(path) or '')
                repo = repo_from_remote or repo
            if owner and repo:
                result = enable_pages(path, owner, repo, branch)
                if result.get('ok'):
                    pages_url = result['url']
                    _step(steps, 'pages', 'ok', pages_url)
                    if add_pages_link_to_readme(path, pages_url):
                        commit_if_needed(path, 'Add GitHub Pages link to README')
                        try:
                            _push(path)
                        except Exception:
                            pass
                        _step(steps, 'pages-readme', 'ok', 'Live Demo link added')
                else:
                    _step(steps, 'pages', 'error', result.get('message') or 'failed')
            else:
                _step(steps, 'pages', 'error', 'could not determine owner/repo')

        _patch_catalogue_after_publish(path, pages_url)
        if commit_if_needed(path, 'Update catalogue after publish'):
            try:
                _push(path)
            except Exception:
                pass

        url = repo_info.get('url') or current_remote(path)
        return {
            'status': 'ok',
            'steps': steps,
            'url': url,
            'pages_url': pages_url,
            'visibility': visibility,
            'message': f"Published {name}" + (f" — {url}" if url else ''),
        }
    except Exception as e:
        _step(steps, 'error', 'error', str(e))
        return {'status': 'error', 'message': str(e), 'steps': steps}
