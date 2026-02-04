#!/usr/bin/env python3
"""
Generate a local Cursor project launcher dashboard.
Scans the entire CODING folder and creates an HTML page
with clickable cards that open projects in Cursor.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Set
import base64

# Configuration
CODING_ROOT = Path("/Users/kylemathewson/Coding")
OUTPUT_FILE = Path(__file__).parent / "dashboard.html"
PINNED_FILE = Path(__file__).parent / "pinned.json"
CURSOR_STORAGE = Path.home() / "Library/Application Support/Cursor/User/globalStorage/storage.json"
CATALOGUE_FILE = "catalogue.json"
SCREENSHOT_FILE = "screenshot.png"

# Main categories (subdirectories to scan recursively)
MAIN_CATEGORIES = ["RESEARCH", "TEACHING", "TOOLS", "PUZZLES", "HARDWARE"]

# Folders to ignore
IGNORE_FOLDERS = {'.git', 'node_modules', 'venv', '__pycache__', '.vscode', '.cursor', 
                  'build', 'dist', '.DS_Store', 'env', '.env'}

# How many recent projects to show
MAX_RECENT = 10


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
    
    # Scan root CODING folder for "OTHER" projects (first level only)
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
            rel_path = project_dir
        
        # Get modification time
        mtime = get_folder_mtime(project_dir)
        
        # Check if in Cursor's recent
        cursor_recent_idx = None
        for idx, rpath in enumerate(cursor_recent):
            if rpath == path_str:
                cursor_recent_idx = idx
                break
        
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
            'category': category,
            'mtime': mtime,
            'has_catalogue': catalogue_path.exists(),
            'is_pinned': path_str in pinned_paths,
            'cursor_recent_idx': cursor_recent_idx,  # None if not in Cursor recent
            'cursor_url': f"cursor://file/{project_dir}",
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


def generate_card_html(project: Dict, compact: bool = False, show_category: bool = False) -> str:
    """Generate HTML for a single project card."""
    # Get screenshot
    img_tag = '<div class="no-screenshot">📁</div>'
    if project['screenshot_path']:
        screenshot_data = encode_image_to_base64(project['screenshot_path'])
        if screenshot_data:
            img_tag = f'<img src="{screenshot_data}" alt="{project["title"]}" class="screenshot">'
    
    # Build tags HTML
    tags_html = ""
    if project['tags'] and not compact:
        tags_html = '<div class="tags">' + ''.join([f'<span class="tag">{tag}</span>' for tag in project['tags'][:3]]) + '</div>'
    
    # Pin button
    pin_icon = "📌" if project['is_pinned'] else "📍"
    pin_class = "pinned" if project['is_pinned'] else ""
    
    # Catalogue indicator
    catalogue_badge = '<span class="badge catalogue">📋</span>' if project['has_catalogue'] else ''
    
    # Category badge for recent view (color-coded)
    cat_class = f'cat-{project["category"].lower()}'
    category_badge = f'<span class="badge {cat_class}">{project["category"]}</span>' if show_category else ''
    
    # Escape quotes in path for JavaScript
    escaped_path = project['path'].replace("'", "\\'").replace('"', '\\"')
    
    card_class = "project-card compact" if compact else "project-card"
    
    # One-liner or fallback
    one_liner = project['oneLiner'] or 'No description'
    
    return f'''
    <div class="{card_class} {pin_class}" data-path="{project['path']}" data-id="{project['id']}">
        <div class="screenshot-container" onclick="openProject('{escaped_path}', event)">
            {img_tag}
            <div class="badges">{catalogue_badge}{category_badge}</div>
        </div>
        <div class="project-info" onclick="openProject('{escaped_path}', event)">
            <h3>{project['title']}</h3>
            <p class="one-liner">{one_liner}</p>
            {f'<p class="project-path">{project["rel_path"]}</p>' if not compact else ''}
            {tags_html}
        </div>
        <button class="pin-btn {pin_class}" onclick="togglePin('{escaped_path}', event)" title="{'Unpin' if project['is_pinned'] else 'Pin'} this project">
            {pin_icon}
        </button>
    </div>
    '''


def generate_html(projects: List[Dict]) -> str:
    """Generate HTML dashboard."""
    
    # Separate pinned
    pinned_projects = [p for p in projects if p['is_pinned']]
    
    # Get recent projects - combine Cursor recent with mtime
    # First: projects from Cursor's recent (in order)
    cursor_recent_projects = sorted(
        [p for p in projects if p['cursor_recent_idx'] is not None],
        key=lambda p: p['cursor_recent_idx']
    )
    
    # Then: projects sorted by mtime (not already in cursor recent)
    cursor_recent_paths = {p['path'] for p in cursor_recent_projects}
    mtime_recent_projects = sorted(
        [p for p in projects if p['path'] not in cursor_recent_paths],
        key=lambda p: p['mtime'],
        reverse=True
    )
    
    # Combine: Cursor recent first, then mtime recent
    recent_projects = (cursor_recent_projects + mtime_recent_projects)[:MAX_RECENT]
    
    # Group all projects by category (including OTHER)
    all_categories = MAIN_CATEGORIES + ["OTHER"]
    by_category = {cat: [] for cat in all_categories}
    for project in projects:
        cat = project['category']
        if cat in by_category:
            by_category[cat].append(project)
    
    # Sort each category's projects by mtime
    for cat in by_category:
        by_category[cat].sort(key=lambda p: p['mtime'], reverse=True)
    
    # Sort categories by most recent project modification
    def get_category_mtime(cat):
        if by_category.get(cat):
            return max(p['mtime'] for p in by_category[cat])
        return 0
    
    sorted_categories = sorted(
        [cat for cat in all_categories if by_category.get(cat)],
        key=get_category_mtime,
        reverse=True
    )
    
    # Generate pinned row
    if pinned_projects:
        pinned_cards = ''.join([generate_card_html(p, show_category=True) for p in pinned_projects])
        pinned_row_html = f'''
        <div class="category-row row-pinned" id="category-pinned">
            <div class="row-header">
                <h2 class="cat-pinned">📌 Pinned</h2>
                <span class="count">{len(pinned_projects)} projects</span>
            </div>
            <div class="row-content">{pinned_cards}</div>
        </div>
        '''
    else:
        pinned_row_html = ''
    
    # Generate recent row
    if recent_projects:
        recent_cards = ''.join([generate_card_html(p, show_category=True) for p in recent_projects])
        recent_row_html = f'''
        <div class="category-row row-recent" id="category-recent">
            <div class="row-header">
                <h2 class="cat-recent">🕐 Recent</h2>
                <span class="count">{len(recent_projects)} projects</span>
            </div>
            <div class="row-content">{recent_cards}</div>
        </div>
        '''
    else:
        recent_row_html = ''
    
    # Generate category rows (Netflix-style, sorted by most recent modification)
    category_rows_html = []
    for idx, category in enumerate(sorted_categories):
        projects_in_cat = by_category[category]
        cards_html = ''.join([generate_card_html(p) for p in projects_in_cat])
        
        # Category emoji
        cat_emoji = {"RESEARCH": "🔬", "TEACHING": "📚", "TOOLS": "🛠️", 
                     "PUZZLES": "🧩", "HARDWARE": "🔧", "OTHER": "📂"}.get(category, "📁")
        
        # Alternating background
        bg_class = "row-even" if idx % 2 == 0 else "row-odd"
        
        row_html = f'''
        <div class="category-row {bg_class}" id="category-{category}">
            <div class="row-header">
                <h2 class="cat-{category.lower()}">{cat_emoji} {category}</h2>
                <span class="count">{len(projects_in_cat)} projects</span>
            </div>
            <div class="row-content">{cards_html}</div>
        </div>
        '''
        category_rows_html.append(row_html)
    
    # Stats
    total = len(projects)
    with_catalogue = len([p for p in projects if p['has_catalogue']])
    
    # Full HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cursor Project Launcher</title>
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
        
        /* Category colors */
        .cat-pinned {{ background: linear-gradient(135deg, #f6e05e 0%, #d69e2e 100%); color: #744210; }}
        .cat-recent {{ background: linear-gradient(135deg, #4fd1c5 0%, #319795 100%); }}
        .cat-research {{ background: linear-gradient(135deg, #667eea 0%, #5a67d8 100%); }}
        .cat-teaching {{ background: linear-gradient(135deg, #48bb78 0%, #38a169 100%); }}
        .cat-tools {{ background: linear-gradient(135deg, #ed8936 0%, #dd6b20 100%); }}
        .cat-puzzles {{ background: linear-gradient(135deg, #9f7aea 0%, #805ad5 100%); }}
        .cat-hardware {{ background: linear-gradient(135deg, #e53e3e 0%, #c53030 100%); }}
        .cat-other {{ background: linear-gradient(135deg, #718096 0%, #4a5568 100%); }}
        
        .row-pinned {{ background: rgba(246,224,94,0.08) !important; }}
        .row-recent {{ background: rgba(79,209,197,0.08) !important; }}
        
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
        
        @keyframes slideIn {{
            from {{ transform: translateX(100px); opacity: 0; }}
            to {{ transform: translateX(0); opacity: 1; }}
        }}
    </style>
</head>
<body>
    <div class="main-layout">
        <main class="main-content">
            <header>
                <h1>Cursor Project Launcher</h1>
                <p>Click to open • ⌘+Click for new window • 📍 to pin</p>
                <div class="stats">
                    <div class="stat">📁 {total} Projects</div>
                    <div class="stat">📋 {with_catalogue} with catalogue</div>
                    <div class="stat">📌 {len(pinned_projects)} Pinned</div>
                    <div class="stat" id="serverStatus">⏳</div>
                </div>
            </header>
            
            <div class="search-box">
                <input type="text" id="searchInput" placeholder="Search projects..." onkeyup="filterProjects()">
            </div>
            
            <div class="categories-container">
                {pinned_row_html}
                {recent_row_html}
                {''.join(category_rows_html)}
            </div>
            
            <footer>
                <p>Generated {datetime.now().strftime('%B %d, %Y at %H:%M')}</p>
            </footer>
        </main>
    </div>
    
    <script>
        const isLocalServer = window.location.protocol === 'http:' && window.location.hostname === 'localhost';
        
        function filterProjects() {{
            const term = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.main-content .project-card').forEach(card => {{
                const title = card.querySelector('h3').textContent.toLowerCase();
                const desc = card.querySelector('.one-liner')?.textContent.toLowerCase() || '';
                const path = card.querySelector('.project-path')?.textContent.toLowerCase() || '';
                card.style.display = (title.includes(term) || desc.includes(term) || path.includes(term)) ? 'flex' : 'none';
            }});
        }}
        
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
    </script>
</body>
</html>
'''
    
    return html


def main():
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
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ Dashboard generated: {OUTPUT_FILE}")
    
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
