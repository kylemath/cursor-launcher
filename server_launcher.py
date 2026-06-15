#!/usr/bin/env python3
"""
Shared server resolver + launcher for the Cursor Project Launcher.

Given a project folder, figures out how to start its dev server -- either from
the optional ``server`` block in that project's ``catalogue.json`` or by
auto-detecting the project type -- then starts/stops it and tracks the running
process in ``running.json``.

catalogue.json ``server`` block (all fields optional):

    "server": {
        "type": "static" | "node" | "liveserver" | "python" | "custom",
        "command": "npm run dev",   # overrides the type default
        "port": 5173,
        "openPath": "/",            # appended to the preview URL
        "host": "localhost",
        "autoStart": true            # let "Open both" auto-launch
    }

Can also be used from the command line for testing:

    python3 server_launcher.py resolve  /path/to/project
    python3 server_launcher.py start    /path/to/project
    python3 server_launcher.py status   /path/to/project
    python3 server_launcher.py stop     /path/to/project
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNNING_FILE = BASE_DIR / "running.json"
LOG_DIR = BASE_DIR / "logs"
CATALOGUE_FILE = "catalogue.json"

# Port defaults per server type
DEFAULT_STATIC_PORT = 8080
DEFAULT_VITE_PORT = 5173
DEFAULT_NODE_PORT = 3000
DEFAULT_PYTHON_PORT = 8000

PY = sys.executable or "python3"

_NODE_BIN_CACHE = None  # memoised modern-node bin dir (or False if none)


# --------------------------------------------------------------------------- #
# Environment: make sure a modern Node is on PATH
# --------------------------------------------------------------------------- #
def _modern_node_bin():
    """Return a bin dir containing Node >= 18, or None.

    The dashboard may be launched from a context where the default ``node`` is
    ancient (e.g. /usr/local/bin/node v10) or where a login shell re-shadows
    nvm. We locate the newest nvm install >= 18 and, failing that, Homebrew.
    """
    global _NODE_BIN_CACHE
    if _NODE_BIN_CACHE is not None:
        return _NODE_BIN_CACHE or None

    candidates = []
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.exists():
        for d in nvm_root.iterdir():
            name = d.name.lstrip("v")
            parts = name.split(".")
            if not parts or not parts[0].isdigit():
                continue
            major = int(parts[0])
            if major >= 18 and (d / "bin" / "node").exists():
                key = tuple(int(x) if x.isdigit() else 0 for x in parts)
                candidates.append((key, str(d / "bin")))
    if candidates:
        candidates.sort()
        _NODE_BIN_CACHE = candidates[-1][1]
        return _NODE_BIN_CACHE

    for c in ("/opt/homebrew/bin", "/usr/local/bin"):
        node = Path(c) / "node"
        if node.exists():
            try:
                out = subprocess.check_output([str(node), "-v"], text=True).strip()
                if int(out.lstrip("v").split(".")[0]) >= 18:
                    _NODE_BIN_CACHE = c
                    return c
            except Exception:
                pass

    _NODE_BIN_CACHE = False
    return None


def _build_env():
    """Return an environment with a modern Node prepended to PATH."""
    env = os.environ.copy()
    node_bin = _modern_node_bin()
    if node_bin:
        env["PATH"] = node_bin + os.pathsep + env.get("PATH", "")
    return env


def _have_node(env=None):
    return _modern_node_bin() is not None


# --------------------------------------------------------------------------- #
# catalogue.json reading
# --------------------------------------------------------------------------- #
def _load_catalogue(project_dir: Path) -> dict:
    cat = project_dir / CATALOGUE_FILE
    if cat.exists():
        try:
            return json.loads(cat.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# --------------------------------------------------------------------------- #
# Resolution (no side effects)
# --------------------------------------------------------------------------- #
def _autodetect_type(p: Path):
    pkg = p / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if "dev" in scripts or "start" in scripts:
                return "node"
        except Exception:
            pass
    if (p / "index.html").exists():
        return "static"
    for f in ("manage.py", "app.py", "main.py"):
        if (p / f).exists():
            return "python"
    return None


def _resolve_static(port: int, env: dict) -> str:
    """Prefer live-server (hot reload) when available, else Python http.server."""
    live = shutil.which("live-server", path=env.get("PATH"))
    if live:
        return f'"{live}" --port={port} --no-browser --quiet .'
    return f'"{PY}" -m http.server {port}'


def _resolve_node(p: Path, port):
    is_vite = any(
        (p / f).exists()
        for f in ("vite.config.ts", "vite.config.js", "vite.config.mjs")
    )
    scripts, deps = {}, {}
    try:
        data = json.loads((p / "package.json").read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    except Exception:
        pass
    if "vite" in deps:
        is_vite = True
    has_next = "next" in deps

    script = "dev" if "dev" in scripts else ("start" if "start" in scripts else "dev")

    if is_vite:
        port = port or DEFAULT_VITE_PORT
        cmd = f"npm run {script} -- --port {port} --strictPort"
    elif has_next:
        port = port or DEFAULT_NODE_PORT
        cmd = f"npm run {script} -- -p {port}"
    else:
        port = port or DEFAULT_NODE_PORT
        cmd = f"npm run {script}"
    return port, cmd


def _resolve_python(p: Path, port: int) -> str:
    if (p / "manage.py").exists():
        return f'"{PY}" manage.py runserver {port}'
    if (p / "app.py").exists():
        return f'"{PY}" app.py'
    if (p / "main.py").exists():
        return f'"{PY}" main.py'
    return f'"{PY}" -m http.server {port}'


def resolve_server(project_path) -> dict:
    """Work out how to start the project's server. Pure: no process spawned.

    Returns a dict with ``available`` plus (when available) ``type``, ``cmd``,
    ``port``, ``url``, ``openPath``, ``autoStart``.
    """
    p = Path(project_path)
    if not p.exists():
        return {"available": False, "reason": "Path does not exist", "path": str(p)}

    env = _build_env()
    meta = _load_catalogue(p)
    srv = (meta.get("server") or {}) if isinstance(meta, dict) else {}

    stype = srv.get("type")
    command = srv.get("command")
    port = srv.get("port")
    open_path = srv.get("openPath")
    host = srv.get("host", "localhost")
    auto_start = bool(srv.get("autoStart", False))

    if not stype and not command:
        stype = _autodetect_type(p)

    if not stype and not command:
        return {
            "available": False,
            "reason": "No server config and could not auto-detect",
            "path": str(p),
        }

    if command:
        stype = stype or "custom"
        port = port or DEFAULT_STATIC_PORT
        cmd = command
    elif stype == "static":
        port = port or DEFAULT_STATIC_PORT
        cmd = _resolve_static(port, env)
    elif stype == "liveserver":
        port = port or DEFAULT_STATIC_PORT
        cmd = f"npx --yes live-server --port={port} --no-browser --quiet ."
    elif stype == "node":
        if not _have_node():
            return {
                "available": False,
                "reason": "Node project but no Node >= 18 found",
                "path": str(p),
            }
        port, cmd = _resolve_node(p, port)
    elif stype == "python":
        port = port or DEFAULT_PYTHON_PORT
        cmd = _resolve_python(p, port)
    else:
        return {"available": False, "reason": f"Unknown server type: {stype}", "path": str(p)}

    if not open_path:
        open_path = "/"
    if not open_path.startswith("/"):
        open_path = "/" + open_path

    return {
        "available": True,
        "type": stype,
        "cmd": cmd,
        "port": port,
        "host": host,
        "openPath": open_path,
        "url": f"http://{host}:{port}{open_path}",
        "autoStart": auto_start,
        "path": str(p),
    }


def is_runnable(project_path) -> bool:
    return bool(resolve_server(project_path).get("available"))


# --------------------------------------------------------------------------- #
# running.json bookkeeping
# --------------------------------------------------------------------------- #
def _load_running() -> dict:
    if RUNNING_FILE.exists():
        try:
            return json.loads(RUNNING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_running(data: dict):
    try:
        RUNNING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _kill_port(port):
    if not port:
        return
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"], capture_output=True, text=True
        )
        for pid in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (OSError, ValueError):
                pass
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Start / stop / status
# --------------------------------------------------------------------------- #
def start_server(project_path) -> dict:
    """Resolve and start the project's server (idempotent per path)."""
    info = resolve_server(project_path)
    if not info.get("available"):
        return info

    path = info["path"]
    running = _load_running()
    existing = running.get(path)
    if existing and _is_alive(existing.get("pid")):
        result = dict(existing)
        result["available"] = True
        result["already"] = True
        return result

    # Free the target port from any stale/untracked process so a fresh launch
    # isn't blocked (matches "kill stale servers" best practice).
    _kill_port(info.get("port"))

    LOG_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", path.strip("/")) or "root"
    log_path = LOG_DIR / f"{safe}.log"

    env = _build_env()
    log_f = open(log_path, "ab")
    log_f.write(
        f"\n=== {info['type']} server for {path} at {datetime.now().isoformat()} ===\n"
        f"$ {info['cmd']}\n".encode()
    )
    log_f.flush()

    # bash -c (NOT -lc): a login shell would re-source profiles and can shadow
    # the nvm node we just put on PATH with an old /usr/local/bin/node.
    proc = subprocess.Popen(
        ["bash", "-c", info["cmd"]],
        cwd=path,
        env=env,
        stdout=log_f,
        stderr=log_f,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid

    entry = {
        "path": path,
        "pid": proc.pid,
        "pgid": pgid,
        "port": info["port"],
        "url": info["url"],
        "type": info["type"],
        "cmd": info["cmd"],
        "log": str(log_path),
        "started_at": datetime.now().isoformat(),
        "available": True,
        "already": False,
    }
    running[path] = entry
    _save_running(running)
    return entry


def stop_server(project_path) -> dict:
    path = str(Path(project_path))
    running = _load_running()
    entry = running.get(path)

    killed = False
    pgid = entry.get("pgid") if entry else None
    pid = entry.get("pid") if entry else None
    port = entry.get("port") if entry else None

    if pgid:
        try:
            os.killpg(int(pgid), signal.SIGTERM)
            killed = True
        except (OSError, ValueError):
            pass
    if not killed and pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
            killed = True
        except (OSError, ValueError):
            pass

    _kill_port(port)

    if entry:
        running.pop(path, None)
        _save_running(running)

    return {"stopped": True, "killed": killed, "path": path}


def server_status(project_path) -> dict:
    path = str(Path(project_path))
    running = _load_running()
    entry = running.get(path)
    if entry and _is_alive(entry.get("pid")):
        result = dict(entry)
        result["running"] = True
        return result
    if entry:
        running.pop(path, None)
        _save_running(running)
    return {"running": False, "path": path}


# --------------------------------------------------------------------------- #
# CLI for manual testing
# --------------------------------------------------------------------------- #
def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[0]
    target = argv[1]
    if cmd == "resolve":
        print(json.dumps(resolve_server(target), indent=2))
    elif cmd == "start":
        print(json.dumps(start_server(target), indent=2))
    elif cmd == "stop":
        print(json.dumps(stop_server(target), indent=2))
    elif cmd == "status":
        print(json.dumps(server_status(target), indent=2))
    else:
        print(f"Unknown command: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
