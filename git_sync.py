#!/usr/bin/env python3
"""Commit and push working-tree changes for a launcher project."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import publish_repo as pr

SKIP_NAMES = {'.DS_Store', 'Thumbs.db'}


def _safe_rel(path: str, rel: str) -> Optional[str]:
    if not rel or rel.startswith('/') or rel.startswith('\\'):
        return None
    parts = Path(rel).parts
    if '..' in parts or (parts and parts[0] == '.git'):
        return None
    try:
        root = Path(path).resolve()
        full = (root / rel).resolve()
        full.relative_to(root)
    except Exception:
        return None
    return rel.replace('\\', '/')


def parse_porcelain_line(line: str) -> Optional[Dict]:
    if not line or len(line) < 4:
        return None
    xy, rest = line[:2], line[3:]
    if ' -> ' in rest:
        rest = rest.split(' -> ', 1)[1]
    if rest.startswith('"') and rest.endswith('"'):
        rest = rest[1:-1].replace('\\n', '\n').replace('\\"', '"')
    kind = 'untracked' if xy == '??' else ('unmerged' if 'U' in xy else 'changed')
    return {'xy': xy, 'path': rest, 'kind': kind}


def suggest_commit_message(paths: List[str]) -> str:
    names = [Path(p).name for p in paths]
    has_cat = 'catalogue.json' in names
    has_shot = any(n.lower().startswith('screenshot.') for n in names)
    if has_cat and has_shot and len(names) <= 3:
        return 'Add catalogue and screenshot'
    if has_cat and len(names) == 1:
        return 'Update catalogue.json'
    if has_shot and len(names) == 1:
        return 'Add screenshot'
    if len(names) == 1:
        return f'Update {names[0]}'
    if names:
        return f'Update {len(names)} files'
    return 'Update project'


def working_tree(path: str) -> Dict:
    path = str(Path(path).expanduser())
    if not Path(path).is_dir():
        return {'status': 'error', 'message': 'Invalid project path'}
    if not (Path(path) / '.git').exists():
        return {'status': 'error', 'message': 'Not a git repository', 'is_repo': False}

    files: List[Dict] = []
    r = pr._git(path, ['status', '--porcelain'])
    if r.returncode == 0:
        for line in (r.stdout or '').splitlines():
            parsed = parse_porcelain_line(line)
            if not parsed:
                continue
            rel = _safe_rel(path, parsed['path'])
            if not rel or Path(rel).name in SKIP_NAMES:
                continue
            parsed['path'] = rel
            files.append(parsed)

    changed = [f for f in files if f['kind'] == 'changed']
    untracked = [f for f in files if f['kind'] == 'untracked']
    unmerged = [f for f in files if f['kind'] == 'unmerged']
    default_files = [f['path'] for f in files if f['kind'] != 'unmerged']

    branch = (pr._git(path, ['branch', '--show-current']).stdout or '').strip() or 'main'
    remote = pr.current_remote(path)
    ahead = behind = 0
    if remote:
        ab = pr._git(path, ['rev-list', '--left-right', '--count', '@{u}...HEAD'])
        if ab.returncode == 0 and ab.stdout.strip():
            parts = ab.stdout.strip().split()
            if len(parts) >= 2:
                try:
                    behind, ahead = int(parts[0]), int(parts[1])
                except ValueError:
                    pass

    return {
        'status': 'ok',
        'is_repo': True,
        'branch': branch,
        'has_remote': bool(remote),
        'remote_url': remote,
        'ahead': ahead,
        'behind': behind,
        'files': files,
        'changed_count': len(changed),
        'untracked_count': len(untracked),
        'unmerged_count': len(unmerged),
        'dirty': bool(files),
        'suggested_message': suggest_commit_message(default_files),
        'default_files': default_files,
    }


def commit_and_push(
    path: str,
    message: Optional[str] = None,
    files: Optional[List[str]] = None,
    include_untracked: bool = True,
    push: bool = True,
) -> Dict:
    tree = working_tree(path)
    if tree.get('status') != 'ok':
        return tree
    path = str(Path(path).expanduser())
    steps: List[Dict] = []

    if tree.get('unmerged_count'):
        return {
            'status': 'error',
            'message': 'Unmerged files — resolve conflicts first',
            'steps': steps,
            **{k: tree[k] for k in ('branch', 'has_remote', 'ahead', 'behind')},
        }

    selected: List[str] = []
    if files is None:
        for item in tree['files']:
            if item['kind'] == 'unmerged':
                continue
            if item['kind'] == 'untracked' and not include_untracked:
                continue
            selected.append(item['path'])
    else:
        allowed = {f['path'] for f in tree['files']}
        for rel in files:
            safe = _safe_rel(path, str(rel))
            if safe and safe in allowed:
                if not include_untracked:
                    kind = next((f['kind'] for f in tree['files'] if f['path'] == safe), '')
                    if kind == 'untracked':
                        continue
                selected.append(safe)

    # de-dupe, keep order
    seen = set()
    selected = [p for p in selected if not (p in seen or seen.add(p))]

    committed = False
    if selected:
        add = pr._git(path, ['add', '--', *selected])
        if add.returncode != 0:
            return {
                'status': 'error',
                'message': (add.stderr or add.stdout or 'git add failed').strip()[:300],
                'steps': steps,
            }
        steps.append({'name': 'add', 'status': 'ok', 'detail': f'{len(selected)} file(s)'})
        msg = (message or '').strip() or suggest_commit_message(selected)
        try:
            committed = pr.commit_staged(path, msg)
        except RuntimeError as e:
            return {'status': 'error', 'message': str(e), 'steps': steps}
        if committed:
            steps.append({'name': 'commit', 'status': 'ok', 'detail': msg})
        else:
            steps.append({'name': 'commit', 'status': 'skip', 'detail': 'nothing to commit'})
    else:
        steps.append({'name': 'add', 'status': 'skip', 'detail': 'no files selected'})

    pushed = False
    if push:
        if not tree.get('has_remote'):
            steps.append({'name': 'push', 'status': 'skip', 'detail': 'no origin remote'})
        elif committed or tree.get('ahead', 0) > 0:
            try:
                pr._push(path)
                pushed = True
                steps.append({'name': 'push', 'status': 'ok', 'detail': tree.get('branch') or 'origin'})
            except RuntimeError as e:
                steps.append({'name': 'push', 'status': 'error', 'detail': str(e)})
                return {
                    'status': 'error',
                    'message': f"Committed but push failed: {e}" if committed else str(e),
                    'steps': steps,
                    'committed': committed,
                    'pushed': False,
                    'files': selected,
                }
        else:
            steps.append({'name': 'push', 'status': 'skip', 'detail': 'nothing to push'})

    if not committed and not pushed:
        return {
            'status': 'error',
            'message': 'Nothing to commit or push',
            'steps': steps,
            'committed': False,
            'pushed': False,
            'files': selected,
        }

    after = working_tree(path)
    action = []
    if committed:
        action.append('Committed')
    if pushed:
        action.append('pushed')
    return {
        'status': 'ok',
        'message': ' and '.join(action) or 'Done',
        'steps': steps,
        'committed': committed,
        'pushed': pushed,
        'files': selected,
        'branch': tree.get('branch'),
        'tree': after if after.get('status') == 'ok' else None,
    }
