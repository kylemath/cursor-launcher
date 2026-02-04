#!/usr/bin/env python3
"""
Local server for Cursor Project Launcher.
Serves the dashboard and handles opening projects in new Cursor windows.
"""

import http.server
import socketserver
import subprocess
import urllib.parse
import os
import sys
import json
from pathlib import Path
from datetime import datetime

PORT = 8847  # "CURS" on phone keypad :)
DASHBOARD_DIR = Path(__file__).parent
PINNED_FILE = DASHBOARD_DIR / "pinned.json"
RECENT_FILE = DASHBOARD_DIR / "recent.json"
MAX_RECENT = 20

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
        
        # Serve dashboard.html as default
        if parsed.path == '/':
            self.path = '/dashboard.html'
        
        return super().do_GET()
    
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
                # -n flag opens in new window
                subprocess.Popen(['cursor', '-n', path], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            else:
                # Default: opens in current window or new if none open
                subprocess.Popen(['cursor', path],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            print(f"✅ Opened in Cursor{' (new window)' if new_window else ''}: {path}")
        except FileNotFoundError:
            print(f"❌ Error: 'cursor' command not found. Make sure Cursor CLI is installed.")
            print("   Run: Cursor > Command Palette > 'Shell Command: Install cursor command'")
        except Exception as e:
            print(f"❌ Error opening Cursor: {e}")
    
    def log_message(self, format, *args):
        """Custom logging."""
        try:
            message = format % args if args else format
            if '/open-in-cursor' in str(message):
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
    
    # Allow socket reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), CursorLauncherHandler) as httpd:
        url = f"http://localhost:{PORT}"
        print(f"✅ Server running at: {url}")
        print(f"\n📋 Opening dashboard in browser...")
        
        # Open in default browser
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
