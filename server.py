#!/usr/bin/env python3
"""
Local server for Cursor Project Launcher.
Serves the dashboard and handles opening projects in new Cursor windows.
"""

import http.server
import socketserver
import subprocess
import threading
import urllib.parse
import os
import sys
import json
from pathlib import Path
from datetime import datetime

import server_launcher
import github_repos
import publish_repo
import git_sync

# Dock .app PATH is /usr/bin:/bin — put Homebrew gh on PATH before any request.
publish_repo.ensure_login_path()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded server so long operations (clone, screenshot, GitHub refresh)
    don't block the dashboard."""
    daemon_threads = True
    allow_reuse_address = True

PORT = 8847  # "CURS" on phone keypad :)
DASHBOARD_DIR = Path(__file__).parent
PINNED_FILE = DASHBOARD_DIR / "pinned.json"
RECENT_FILE = DASHBOARD_DIR / "recent.json"
MAX_RECENT = 20
CURSOR_CMD = "/usr/local/bin/cursor"  # Full path for Dock app compatibility

class CursorLauncherHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler that can open Cursor in new windows."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        
        # Handle open-in-cursor requests
        if parsed.path == '/open-in-cursor':
            path = query.get('path', [''])[0]
            new_window = query.get('new', ['false'])[0] == 'true'
            
            if path and os.path.exists(path):
                self.open_cursor(path, new_window)
                self.add_to_recent(path)
                self.send_json_response(200, {"status": "ok"})
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return
        
        # Handle toggle-pin requests
        if parsed.path == '/toggle-pin':
            path = query.get('path', [''])[0]
            if path:
                is_pinned = self.toggle_pin(path)
                self.send_json_response(200, {"status": "ok", "pinned": is_pinned})
            else:
                self.send_json_response(400, {"status": "error", "message": "No path provided"})
            return

        # Launch a project's dev server (HTML / Python / Node)
        if parsed.path == '/launch-app':
            path = query.get('path', [''])[0]
            if path and os.path.exists(path):
                info = server_launcher.start_server(path)
                if info.get('available'):
                    print(f"▶️  Launched {info.get('type')} server: {info.get('url')}")
                    self.open_in_chrome(info.get('url'), info.get('port'))
                    self.send_json_response(200, {"status": "ok", **info})
                else:
                    print(f"⚠️  Could not launch server for {path}: {info.get('reason')}")
                    self.send_json_response(200, {"status": "error", **info})
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return

        # Stop a project's dev server
        if parsed.path == '/stop-app':
            path = query.get('path', [''])[0]
            if path:
                result = server_launcher.stop_server(path)
                print(f"⏹️  Stopped server: {path}")
                self.send_json_response(200, {"status": "ok", **result})
            else:
                self.send_json_response(400, {"status": "error", "message": "No path provided"})
            return

        # Open the Cursor window AND launch the app together
        if parsed.path == '/open-both':
            path = query.get('path', [''])[0]
            new_window = query.get('new', ['false'])[0] == 'true'
            if path and os.path.exists(path):
                self.open_cursor(path, new_window)
                self.add_to_recent(path)
                info = server_launcher.start_server(path)
                if info.get('available'):
                    print(f"🚀 Opened Cursor + launched app: {info.get('url')}")
                    self.open_in_chrome(info.get('url'), info.get('port'))
                    self.send_json_response(200, {"status": "ok", **info})
                else:
                    # Cursor still opened; just no server to run
                    self.send_json_response(200, {"status": "ok", "cursor_only": True, **info})
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return

        # Report whether a project's server is currently running
        if parsed.path == '/app-status':
            path = query.get('path', [''])[0]
            if path:
                self.send_json_response(200, {"status": "ok", **server_launcher.server_status(path)})
            else:
                self.send_json_response(400, {"status": "error", "message": "No path provided"})
            return

        # Project metadata for the Manage modal
        if parsed.path == '/project-info':
            path = query.get('path', [''])[0]
            if path and os.path.isdir(path):
                self.send_json_response(200, {"status": "ok", **self.project_info(path)})
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return

        # Open a file inside a project in Cursor (README / .md / source)
        if parsed.path == '/open-file':
            path = query.get('path', [''])[0]
            fname = query.get('file', [''])[0]
            target = self.resolve_project_file(path, fname)
            if target:
                self.open_cursor(target, new_window=False)
                self.send_json_response(200, {"status": "ok", "file": target})
            else:
                self.send_json_response(404, {"status": "error", "message": f"Not found: {fname}"})
            return

        # Auto-generate a sensible catalogue.json from folder/git/server info
        if parsed.path == '/autogen-catalogue':
            path = query.get('path', [''])[0]
            if path and os.path.isdir(path):
                self.send_json_response(200, self.autogen_catalogue(path))
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return

        # Capture a small screenshot into the project's screenshot.png
        if parsed.path == '/capture-screenshot':
            path = query.get('path', [''])[0]
            if path and os.path.isdir(path):
                result = self.capture_screenshot(path)
                code = 200 if result.get('status') == 'ok' else 200
                self.send_json_response(code, result)
            else:
                self.send_json_response(400, {"status": "error", "message": "Invalid path"})
            return

        # Serve a project's screenshot.png (cards + modal preview)
        if parsed.path == '/screenshot-file':
            file_path = query.get('file', [''])[0]
            if not file_path:
                path = query.get('path', [''])[0]
                file_path = os.path.join(path, 'screenshot.png') if path else ''
            if self.allowed_screenshot_file(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header('Content-type', 'image/png')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(data)
                except BrokenPipeError:
                    pass
            else:
                self.send_json_response(404, {"status": "error", "message": "No screenshot"})
            return

        # Clone a GitHub repo into ~/<name> and open it in a new Cursor window
        if parsed.path == '/clone-repo':
            url = query.get('url', [''])[0]
            name = query.get('name', [''])[0]
            setup = query.get('setup', ['0'])[0] == '1'
            self.send_json_response(200, self.clone_repo(url, name, setup=setup))
            return

        # Create a new empty project folder in ~ and open it in Cursor
        if parsed.path == '/new-project':
            name = query.get('name', [''])[0]
            self.send_json_response(200, self.new_project(name))
            return

        # Preview recommended publish defaults (gir-style, no AI)
        if parsed.path == '/publish-preview':
            path = query.get('path', [''])[0]
            self.send_json_response(200, publish_repo.preview(path))
            return

        if parsed.path == '/git-status':
            path = query.get('path', [''])[0]
            if not publish_repo.is_allowed_project_path(path):
                self.send_json_response(400, {"status": "error", "message": "Invalid project path"})
                return
            self.send_json_response(200, git_sync.working_tree(path))
            return

        # Re-fetch GitHub repos (rebuild the cache), then regenerate the dashboard
        if parsed.path == '/refresh-github':
            def _refresh():
                try:
                    github_repos.fetch_and_cache(progress=lambda m: print(f"  gh: {m}"))
                    subprocess.run([sys.executable, str(DASHBOARD_DIR / 'generate_dashboard.py')],
                                   cwd=DASHBOARD_DIR)
                except Exception as e:
                    print(f"GitHub refresh error: {e}")
            threading.Thread(target=_refresh, daemon=True).start()
            self.send_json_response(200, {"status": "ok",
                "message": "GitHub refresh started — reload the page in a minute"})
            return

        # Rebuild dashboard.html in place (re-bakes cards from current
        # catalogue.json / screenshot.png files) without restarting the server.
        # Synchronous so the client can reload as soon as it returns.
        if parsed.path == '/regenerate-dashboard':
            ok = self.regenerate_dashboard()
            self.send_json_response(200 if ok else 500, {
                "status": "ok" if ok else "error",
                "message": "Dashboard regenerated" if ok else "Regeneration failed"})
            return

        # All currently managed running servers
        if parsed.path == '/status':
            running = server_launcher._load_running()
            live = [
                {**v, 'running': server_launcher._is_alive(v.get('pid'))}
                for v in running.values()
            ]
            # clean out dead entries while we're here
            dead = [v['path'] for v in live if not v['running']]
            for p in dead:
                running.pop(p, None)
            if dead:
                server_launcher._save_running(running)
            live = [v for v in live if v['running']]
            self.send_json_response(200, {'status': 'ok', 'servers': live})
            return

        # Gracefully shut down the dashboard server itself
        if parsed.path == '/shutdown':
            self.send_json_response(200, {'status': 'ok', 'message': 'Shutting down'})
            def _stop():
                import time; time.sleep(0.4)
                os.kill(os.getpid(), 15)   # SIGTERM
            threading.Thread(target=_stop, daemon=True).start()
            return

        # Ports registry + live status
        if parsed.path == '/ports':
            self.send_json_response(200, {"status": "ok", "ports": self.ports_overview()})
            return

        # Suggest a free, non-conflicting port
        if parsed.path == '/suggest-port':
            try:
                base = int(query.get('base', ['5173'])[0])
            except ValueError:
                base = 5173
            self.send_json_response(200, {"status": "ok", "port": self.suggest_port(base)})
            return

        # Serve dashboard.html as default
        if parsed.path == '/':
            self.path = '/dashboard.html'
        
        return super().do_GET()

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/':
            self.path = '/dashboard.html'
        return super().do_HEAD()

    def guess_type(self, path):
        if str(path).endswith('.webmanifest'):
            return 'application/manifest+json'
        return super().guess_type(path)

    def allowed_screenshot_file(self, file_path):
        """Only serve screenshot.png files or images stored in gh_assets/."""
        if not file_path or not os.path.isfile(file_path):
            return False
        real = os.path.realpath(file_path)
        assets = str((DASHBOARD_DIR / 'gh_assets').resolve())
        if real.startswith(assets + os.sep):
            return real.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif'))
        return os.path.basename(real) == 'screenshot.png'
    
    def send_json_response(self, code, data):
        """Send a JSON response."""
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def toggle_pin(self, path):
        """Toggle pin status for a project."""
        pinned = []
        if PINNED_FILE.exists():
            try:
                with open(PINNED_FILE, 'r') as f:
                    pinned = json.load(f)
            except:
                pass
        
        if path in pinned:
            pinned.remove(path)
            is_pinned = False
            print(f"📍 Unpinned: {path}")
        else:
            pinned.append(path)
            is_pinned = True
            print(f"📌 Pinned: {path}")
        
        with open(PINNED_FILE, 'w') as f:
            json.dump(pinned, f, indent=2)
        
        return is_pinned
    
    def add_to_recent(self, path):
        """Add project to recent list."""
        recent = []
        if RECENT_FILE.exists():
            try:
                with open(RECENT_FILE, 'r') as f:
                    recent = json.load(f)
            except:
                pass
        
        # Remove if already exists
        recent = [r for r in recent if r.get('path') != path]
        
        # Add to front
        recent.insert(0, {
            'path': path,
            'opened_at': datetime.now().isoformat()
        })
        
        # Limit size
        recent = recent[:MAX_RECENT]
        
        with open(RECENT_FILE, 'w') as f:
            json.dump(recent, f, indent=2)
    
    def open_cursor(self, path, new_window=False):
        """Open a project in Cursor."""
        try:
            if new_window:
                # -n forces a brand-new window
                subprocess.Popen([CURSOR_CMD, '-n', path],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            else:
                # Default: -r reuses the last active editor window instead of
                # spawning a new one.
                subprocess.Popen([CURSOR_CMD, '-r', path],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            print(f"✅ Opened in Cursor{' (new window)' if new_window else ''}: {path}")
        except FileNotFoundError:
            print(f"❌ Error: 'cursor' command not found at {CURSOR_CMD}.")
            print("   Run: Cursor > Command Palette > 'Shell Command: Install cursor command'")
        except Exception as e:
            print(f"❌ Error opening Cursor: {e}")
    
    def regenerate_dashboard(self):
        """Re-run generate_dashboard.py synchronously so dashboard.html reflects
        the latest catalogue.json / screenshot.png files. Returns True on success."""
        try:
            result = subprocess.run(
                [sys.executable, str(DASHBOARD_DIR / 'generate_dashboard.py')],
                cwd=DASHBOARD_DIR, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print("🔄 Regenerated dashboard.html (cards refreshed)")
                return True
            print(f"⚠️  Dashboard regeneration failed: {result.stderr[-300:]}")
            return False
        except Exception as e:
            print(f"⚠️  Dashboard regeneration error: {e}")
            return False

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/save-catalogue':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b'{}'
                payload = json.loads(body.decode('utf-8'))
                path = payload.get('path', '')
                catalogue = payload.get('catalogue', {})
                if not path or not os.path.isdir(path):
                    self.send_json_response(400, {"status": "error", "message": "Invalid path"})
                    return
                out = os.path.join(path, 'catalogue.json')
                # Merge into any existing catalogue so homepage-only fields
                # (e.g. demoUrl, screenshot) are preserved when not edited here.
                existing = {}
                if os.path.isfile(out):
                    try:
                        with open(out, 'r', encoding='utf-8') as f:
                            existing = json.load(f)
                    except Exception:
                        existing = {}
                cleaned = {k: v for k, v in catalogue.items()
                           if v not in ('', None, [], {})}
                existing.update(cleaned)
                with open(out, 'w', encoding='utf-8') as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)
                    f.write('\n')
                print(f"💾 Saved catalogue.json: {out}")
                self.send_json_response(200, {"status": "ok", "file": out})
            except Exception as e:
                self.send_json_response(500, {"status": "error", "message": str(e)})
            return
        if parsed.path == '/git-commit-push':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b'{}'
                payload = json.loads(body.decode('utf-8'))
            except Exception as e:
                self.send_json_response(400, {"status": "error", "message": f"Bad JSON: {e}"})
                return
            path = payload.get('path', '')
            if not publish_repo.is_allowed_project_path(path):
                self.send_json_response(400, {"status": "error", "message": "Invalid project path"})
                return
            files = payload.get('files', None)
            if files is not None and not isinstance(files, list):
                self.send_json_response(400, {"status": "error", "message": "files must be a list"})
                return
            include = payload.get('include_untracked', True)
            if isinstance(include, str):
                include = include.lower() in ('1', 'true', 'yes')
            do_push = payload.get('push', True)
            if isinstance(do_push, str):
                do_push = do_push.lower() in ('1', 'true', 'yes')
            print(f"⬆ Commit/push {path}")
            result = git_sync.commit_and_push(
                path,
                message=payload.get('message'),
                files=files,
                include_untracked=bool(include),
                push=bool(do_push),
            )
            if result.get('status') == 'ok':
                self.regenerate_dashboard()
            print(f"⬆ {result.get('status')}: {result.get('message')}")
            self.send_json_response(200, result)
            return
        if parsed.path == '/publish-repo':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b'{}'
                payload = json.loads(body.decode('utf-8'))
            except Exception as e:
                self.send_json_response(400, {"status": "error", "message": f"Bad JSON: {e}"})
                return
            path = payload.get('path', '')
            if not publish_repo.is_allowed_project_path(path):
                self.send_json_response(400, {"status": "error", "message": "Invalid project path"})
                return
            use_defaults = bool(payload.get('defaults'))
            preview = publish_repo.preview(path)
            if preview.get('status') != 'ok':
                self.send_json_response(400, preview)
                return
            rec = preview.get('defaults') or {}
            visibility = rec.get('visibility', 'private') if use_defaults else (
                payload.get('visibility') or rec.get('visibility') or 'private')
            pages = rec.get('pages', False) if use_defaults else payload.get('pages', rec.get('pages', False))
            if isinstance(pages, str):
                pages = pages.lower() in ('1', 'true', 'yes')
            repo_name = rec.get('repo_name') if use_defaults else (
                payload.get('repo_name') or rec.get('repo_name'))
            print(f"🐙 Publishing {path} as {repo_name} ({visibility}, pages={bool(pages)})")
            result = publish_repo.publish(
                path,
                visibility=visibility,
                pages=bool(pages),
                repo_name=repo_name,
                commit_message=payload.get('commit_message'),
                capture_screenshot=self.capture_screenshot,
                autogen_catalogue=self.autogen_catalogue,
            )
            if result.get('status') == 'ok':
                self.regenerate_dashboard()
            print(f"🐙 Publish {result.get('status')}: {result.get('message')}")
            self.send_json_response(200, result)
            return
        if parsed.path == '/save-repo-groups':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length) if length else b'{}'
                payload = json.loads(body.decode('utf-8'))
                columns = payload.get('columns')
                if not isinstance(columns, list):
                    self.send_json_response(400, {"status": "error", "message": "columns must be a list"})
                    return
                cleaned = []
                seen = set()
                for col in columns:
                    if not isinstance(col, dict):
                        continue
                    names = []
                    for n in col.get('names') or []:
                        if isinstance(n, str) and n and n not in seen:
                            seen.add(n)
                            names.append(n)
                    cleaned.append({
                        'id': str(col.get('id') or '') or 'untitled',
                        'title': (str(col.get('title') or 'Untitled').strip() or 'Untitled'),
                        'names': names,
                    })
                out = DASHBOARD_DIR / 'repo_groups.local.json'
                data = {
                    'saved': datetime.now().isoformat(),
                    'colsPerRow': str(payload.get('colsPerRow') or 'auto'),
                    'columns': cleaned,
                }
                out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
                print(f"💾 Saved repo_groups.local.json ({len(cleaned)} groups)")
                regenerated = False
                if payload.get('regenerate', True):
                    regenerated = self.regenerate_dashboard()
                self.send_json_response(200, {
                    "status": "ok",
                    "file": str(out),
                    "group_count": len(cleaned),
                    "regenerated": regenerated,
                })
            except Exception as e:
                self.send_json_response(500, {"status": "error", "message": str(e)})
            return
        self.send_json_response(404, {"status": "error", "message": "Unknown endpoint"})

    def _port_pids(self, port):
        """PIDs listening on a TCP port (empty if free)."""
        try:
            result = subprocess.run(['lsof', '-ti', f'TCP:{port}', '-sTCP:LISTEN'],
                                    capture_output=True, text=True, timeout=4)
            return [int(p) for p in result.stdout.strip().splitlines() if p.strip()]
        except Exception:
            return []

    def _load_registry(self):
        reg_file = DASHBOARD_DIR / 'ports.json'
        if reg_file.exists():
            try:
                return json.loads(reg_file.read_text())
            except Exception:
                pass
        return {"projects": []}

    def ports_overview(self):
        """Build [{port, projects[], conflict, listening, pids, managed_path}]."""
        registry = self._load_registry()
        running = server_launcher._load_running()
        managed_by_port = {}
        for path, entry in running.items():
            if entry.get('port') and server_launcher._is_alive(entry.get('pid')):
                managed_by_port[entry['port']] = path

        by_port = {}
        for proj in registry.get('projects', []):
            port = proj.get('port')
            if not port:
                continue
            by_port.setdefault(port, []).append(proj)

        # Include managed ports that aren't in the registry
        for port, path in managed_by_port.items():
            if port not in by_port:
                by_port[port] = [{"title": os.path.basename(path.rstrip('/')),
                                  "path": path, "port": port, "designated": False}]

        overview = []
        for port in sorted(by_port.keys()):
            pids = self._port_pids(port)
            overview.append({
                "port": port,
                "projects": by_port[port],
                "conflict": len(by_port[port]) > 1,
                "listening": bool(pids),
                "pids": pids,
                "managed_path": managed_by_port.get(port),
            })
        return overview

    def suggest_port(self, base=5173):
        """First port >= base not in the registry and not currently listening."""
        registry = self._load_registry()
        used = {p.get('port') for p in registry.get('projects', []) if p.get('port')}
        port = max(base, 1024)
        for _ in range(2000):
            if port not in used and not self._port_pids(port):
                return port
            port += 1
        return base

    def project_info(self, path):
        """Gather catalogue + md files + server info for the Manage modal."""
        info = {"name": os.path.basename(path.rstrip('/')), "catalogue": {},
                "md_files": [], "readme": False, "runnable": False, "server_url": None}
        cat_path = os.path.join(path, 'catalogue.json')
        if os.path.isfile(cat_path):
            try:
                with open(cat_path, 'r', encoding='utf-8') as f:
                    info["catalogue"] = json.load(f)
            except Exception:
                pass
        try:
            entries = sorted(os.listdir(path))
            info["md_files"] = [e for e in entries if e.lower().endswith('.md')][:20]
            info["readme"] = any(e.lower() == 'readme.md' for e in entries)
        except Exception:
            pass
        try:
            resolved = server_launcher.resolve_server(path)
            if resolved.get('available'):
                info["runnable"] = True
                info["server_url"] = resolved.get('url')
        except Exception:
            pass
        info["publish"] = publish_repo.preview(path)
        if publish_repo.is_allowed_project_path(path) and (Path(path) / '.git').exists():
            info["git"] = git_sync.working_tree(path)
        else:
            info["git"] = {"status": "ok", "is_repo": False, "dirty": False}
        return info

    def resolve_project_file(self, path, fname):
        """Safely resolve a file within a project dir; case-insensitive fallback."""
        if not path or not fname or not os.path.isdir(path):
            return None
        candidate = os.path.normpath(os.path.join(path, fname))
        # Prevent path traversal outside the project
        if not candidate.startswith(os.path.abspath(path)):
            return None
        if os.path.isfile(candidate):
            return candidate
        # Case-insensitive fallback (e.g. README.md vs readme.md)
        try:
            for e in os.listdir(path):
                if e.lower() == fname.lower():
                    return os.path.join(path, e)
        except Exception:
            pass
        return None

    def _safe_home_target(self, name):
        """Validate a project name and return its absolute path in ~ (or None)."""
        import re as _re
        name = (name or '').strip().strip('/')
        if not name or '/' in name or '..' in name or name.startswith('.'):
            return None
        if not _re.match(r'^[A-Za-z0-9 ._-]+$', name):
            return None
        return os.path.join(os.path.expanduser('~'), name)

    def clone_repo(self, url, name, setup=False):
        """git clone a repo into ~/<name> and open it in a new Cursor window.

        If setup=True, also auto-generate catalogue.json + screenshot.png in the
        fresh local clone (not committed/pushed — that's left to the user)."""
        if not url:
            return {"status": "error", "message": "No clone URL"}
        target = self._safe_home_target(name)
        if not target:
            return {"status": "error", "message": "Invalid project name"}
        existed = os.path.exists(target)
        if not existed:
            try:
                result = subprocess.run(['git', 'clone', url, target],
                                        capture_output=True, text=True, timeout=600)
                if result.returncode != 0:
                    return {"status": "error", "message": (result.stderr or 'git clone failed')[:300]}
                print(f"⬇️  Cloned {url} -> {target}")
            except subprocess.TimeoutExpired:
                return {"status": "error", "message": "Clone timed out"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        setup_result = None
        if setup:
            try:
                self.autogen_catalogue(target)
                shot = self.capture_screenshot(target)
                setup_result = "catalogue + screenshot" if shot.get('status') == 'ok' else "catalogue (no screenshot)"
                print(f"✨ Set up {target}: {setup_result}")
            except Exception as e:
                setup_result = f"setup error: {e}"

        self.add_to_recent(target)
        self.open_cursor(target, new_window=True)
        msg = "Folder already existed; opened in Cursor" if existed else "Cloned and opened in Cursor"
        if setup_result:
            msg += f" — generated {setup_result}"
        return {"status": "ok", "path": target, "message": msg}

    def new_project(self, name):
        """Create an empty folder in ~ and open it in a new Cursor window."""
        target = self._safe_home_target(name)
        if not target:
            return {"status": "error", "message": "Invalid project name"}
        if os.path.exists(target):
            self.open_cursor(target, new_window=True)
            return {"status": "ok", "path": target, "message": "Folder already exists; opened in Cursor"}
        try:
            os.makedirs(target)
            self.add_to_recent(target)
            self.open_cursor(target, new_window=True)
            print(f"🆕 Created project {target}")
            return {"status": "ok", "path": target}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def autogen_catalogue(self, path):
        """Build a sensible catalogue.json from folder name, git remote, README,
        and the detected server. Merges with any existing catalogue."""
        import re as _re
        name = os.path.basename(path.rstrip('/'))
        out = os.path.join(path, 'catalogue.json')
        existing = {}
        if os.path.isfile(out):
            try:
                with open(out, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        # Title: prettify folder name (split camelCase / separators)
        pretty = _re.sub(r'[-_]+', ' ', name)
        pretty = _re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', pretty).strip().title()

        # One-liner: first non-heading line of README, if any
        one_liner = ''
        for readme in ('README.md', 'readme.md', 'Readme.md', 'README'):
            rp = os.path.join(path, readme)
            if os.path.isfile(rp):
                try:
                    with open(rp, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            raw = line.strip()
                            # Skip markdown headings, images, links, badges, code fences
                            if (not raw or raw.startswith('#') or raw.startswith('!')
                                    or raw.startswith('[') or raw.startswith('```')
                                    or raw.startswith('<') or raw.startswith('---')):
                                continue
                            one_liner = raw[:160]
                            break
                except Exception:
                    pass
                break

        # Git remote -> demoUrl guess (GitHub Pages) + githubUrl
        demo_url = ''
        try:
            remote = subprocess.run(['git', '-C', path, 'remote', 'get-url', 'origin'],
                                    capture_output=True, text=True, timeout=4).stdout.strip()
            m = _re.search(r'github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$', remote)
            if m:
                owner, repo = m.group(1), m.group(2)
                demo_url = f'https://{owner}.github.io/{repo}'
        except Exception:
            pass

        # Detected server -> server block
        server_block = None
        try:
            resolved = server_launcher.resolve_server(path)
            if resolved.get('available'):
                server_block = {
                    'type': resolved.get('type'),
                    'port': resolved.get('port'),
                    'openPath': resolved.get('openPath', '/'),
                    'autoStart': False,
                }
        except Exception:
            pass

        generated = {
            'id': name,
            'title': existing.get('title') or pretty,
            'oneLiner': existing.get('oneLiner') or one_liner,
            'kind': existing.get('kind') or 'project',
            'status': existing.get('status') or 'active',
        }
        if demo_url and not existing.get('demoUrl'):
            generated['demoUrl'] = demo_url
        shot = os.path.join(path, 'screenshot.png')
        if os.path.isfile(shot) and not existing.get('screenshot'):
            generated['screenshot'] = './screenshot.png'
        if server_block and not existing.get('server'):
            generated['server'] = server_block

        merged = {**existing, **{k: v for k, v in generated.items() if v not in ('', None)}}
        try:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
                f.write('\n')
            print(f"✨ Auto-generated catalogue.json: {out}")
            return {"status": "ok", "file": out, "catalogue": merged}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def capture_screenshot(self, path):
        """Start the project's server, screenshot it with headless Chrome,
        resize small, and save as screenshot.png in the project."""
        resolved = server_launcher.resolve_server(path)
        if not resolved.get('available'):
            return {"status": "error", "message": "No server/page to screenshot for this project"}

        status = server_launcher.server_status(path)
        started_here = not status.get('running')
        entry = server_launcher.start_server(path)
        url = entry.get('url')
        port = entry.get('port')

        chrome = None
        for c in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]:
            if os.path.isfile(c):
                chrome = c
                break
        if not chrome:
            return {"status": "error", "message": "Google Chrome not found"}

        tmp = f"/tmp/cl_shot_{port}.png"
        out = os.path.join(path, 'screenshot.png')
        try:
            # Wait for the server to accept connections (~12s max)
            wait = (
                f'for i in $(seq 1 24); do '
                f'if curl -s -o /dev/null --max-time 1 "http://localhost:{port}/"; then break; fi; '
                f'sleep 0.5; done'
            )
            subprocess.run(['bash', '-c', wait], timeout=15)
            subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                            '--window-size=1280,800', f'--screenshot={tmp}', url],
                           capture_output=True, timeout=30)
            if not os.path.isfile(tmp):
                return {"status": "error", "message": "Screenshot capture failed"}
            # Resize small (max dimension 900) into the project
            subprocess.run(['sips', '-Z', '900', tmp, '--out', out], capture_output=True, timeout=15)
            if not os.path.isfile(out):
                # Fallback: copy full-size if sips failed
                subprocess.run(['cp', tmp, out], capture_output=True)
            print(f"📸 Screenshot saved: {out}")
            return {"status": "ok", "file": out, "url": url}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
            if started_here:
                server_launcher.stop_server(path)

    def open_in_chrome(self, url, port):
        """Wait until the dev server accepts connections, then open it in Chrome.

        Runs detached so the HTTP response returns immediately. Falls back to the
        default browser if Google Chrome isn't installed.
        """
        if not url:
            return
        try:
            script = (
                f'for i in $(seq 1 40); do '
                f'if curl -s -o /dev/null --max-time 1 "http://localhost:{port}/"; then break; fi; '
                f'sleep 0.5; done; '
                f'open -a "Google Chrome" "{url}" 2>/dev/null || open "{url}"'
            )
            subprocess.Popen(['bash', '-c', script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"🌐 Opening in Chrome when ready: {url}")
        except Exception as e:
            print(f"❌ Error opening Chrome: {e}")

    def log_message(self, format, *args):
        """Custom logging."""
        try:
            message = format % args if args else format
            if any(ep in str(message) for ep in
                   ('/open-in-cursor', '/launch-app', '/stop-app', '/open-both',
                    '/app-status', '/status', '/ports', '/suggest-port',
                    '/project-info', '/open-file', '/capture-screenshot',
                    '/screenshot-file', '/save-catalogue', '/save-repo-groups', '/shutdown',
                    '/autogen-catalogue', '/clone-repo', '/new-project',
                    '/publish-preview', '/publish-repo',
                    '/git-status', '/git-commit-push',
                    '/refresh-github', '/regenerate-dashboard')):
                return  # Don't log API calls
            # Only log actual page requests
            if '200' in str(message) or '304' in str(message):
                print(f"📄 {message}")
        except:
            pass  # Suppress logging errors


def kill_existing_server():
    """Kill any existing server on our port."""
    try:
        # Find and kill process using our port
        result = subprocess.run(
            ['lsof', '-ti', f':{PORT}'],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid in pids:
                try:
                    subprocess.run(['kill', '-9', pid], capture_output=True)
                    print(f"🔄 Killed existing server (PID {pid})")
                except:
                    pass
    except:
        pass


def main():
    publish_repo.ensure_login_path()
    # Kill any existing server on our port
    kill_existing_server()
    
    # Regenerate dashboard first
    print("🔄 Regenerating dashboard...")
    try:
        subprocess.run([sys.executable, str(DASHBOARD_DIR / 'generate_dashboard.py')], 
                      check=True, cwd=DASHBOARD_DIR)
    except subprocess.CalledProcessError:
        print("⚠️  Warning: Could not regenerate dashboard")
    
    print(f"\n🚀 Starting Cursor Project Launcher server on port {PORT}...")
    
    with ThreadingHTTPServer(("", PORT), CursorLauncherHandler) as httpd:
        url = f"http://localhost:{PORT}"
        print(f"✅ Server running at: {url}")
        # Open in default browser, unless the caller (e.g. the dock app, which
        # opens Chrome itself) asked us not to via CL_NO_BROWSER=1.
        if os.environ.get('CL_NO_BROWSER') == '1':
            print(f"\n📋 Dashboard ready (browser open skipped): {url}")
        else:
            print(f"\n📋 Opening dashboard in browser...")
            try:
                subprocess.Popen(['open', url])
            except:
                print(f"   Open manually: {url}")
        
        print(f"\n💡 Tips:")
        print(f"   • Click a project to open in Cursor")
        print(f"   • ⌘/Ctrl+Click to open in NEW Cursor window")
        print(f"   • Press Ctrl+C to stop the server")
        print()
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Server stopped. Goodbye!")
        except BrokenPipeError:
            pass  # Client disconnected, ignore


if __name__ == '__main__':
    main()
