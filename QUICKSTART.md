# 🚀 Quick Start Guide - Cursor Project Launcher

## You're All Set! 🎉

Your Cursor Project Dashboard is ready to use. The dashboard should be open in your browser right now!

## What You Can Do Now

### 1. Use the Dashboard
- **Click any project card** to open it in Cursor
- **Search** for projects by typing in the search box
- **Browse** by category: RESEARCH, TEACHING, TOOLS
- **Bookmark it** (⌘D) for quick access

### 2. Quick Launch from Anywhere

Open a new terminal and type:
```bash
projects
```

This will:
1. Regenerate the dashboard with any new projects
2. Open it in your browser automatically

*Note: You may need to open a new terminal window or run `source ~/.zshrc` for the alias to work.*

### 3. Manual Update

If you add new projects or screenshots:
```bash
cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher
python3 generate_dashboard.py
```

## How It Works

The dashboard automatically finds all your projects that have:
- ✅ `catalogue.json` file (project metadata)
- ✅ `screenshot.png` file (project thumbnail)

It scans these directories:
- `/Users/kylemathewson/Coding/RESEARCH`
- `/Users/kylemathewson/Coding/TEACHING`
- `/Users/kylemathewson/Coding/TOOLS`
- `/Users/kylemathewson/Coding/PUZZLES`

## Adding New Projects to Dashboard

To add a new project to the dashboard:

1. **Create `catalogue.json`** in your project root:
   ```json
   {
     "id": "my-project",
     "title": "My Awesome Project",
     "oneLiner": "What this project does in one line",
     "kind": "project",
     "categories": ["category1", "category2"],
     "tags": ["tag1", "tag2", "tag3"],
     "status": "active"
   }
   ```

2. **Add `screenshot.png`** to your project root:
   - Take a screenshot of your project
   - Save as `screenshot.png` in the project folder
   - Recommended size: 800x600 or similar

3. **Regenerate dashboard:**
   ```bash
   projects
   ```

## Current Projects

Your dashboard currently has:
- **10 total projects**
- 5 in RESEARCH
- 4 in TEACHING
- 1 in TOOLS

## Next Steps

### Make It Your Browser Homepage (Optional)

**Chrome:**
1. Settings > Appearance > Show home button ✓
2. Enter custom web address:
   ```
   file:///Users/kylemathewson/Coding/TOOLS/cursor-launcher/dashboard.html
   ```

**Safari:**
1. Preferences > General > Homepage
2. Paste:
   ```
   file:///Users/kylemathewson/Coding/TOOLS/cursor-launcher/dashboard.html
   ```

### Add More Projects

Look for your other projects that don't have `catalogue.json` yet and add them! The format is super simple (see example above).

### Customize

Want to change colors, layout, or add features? Edit:
- `generate_dashboard.py` - Main script
- CSS section in the HTML template

## Files Created

```
/Users/kylemathewson/Coding/TOOLS/cursor-launcher/
├── dashboard.html          # Your beautiful dashboard (12 MB with embedded images)
├── generate_dashboard.py   # Generator script
├── launch.sh              # Quick launcher script
├── README.md              # Full documentation
├── INSTALLATION.md        # Installation options
├── QUICKSTART.md         # This file
└── .github/
    └── workflows/
        └── update-dashboard.yml  # Optional GitHub Actions automation
```

## Troubleshooting

**Projects not showing?**
- Make sure they have `catalogue.json`
- Check the project is in RESEARCH, TEACHING, TOOLS, or PUZZLES

**Cursor not opening?**
- Make sure Cursor is installed
- The dashboard will show a notification when you click

**Dashboard looks outdated?**
- Run `projects` to regenerate

**Alias not working?**
- Open a new terminal window
- Or run: `source ~/.zshrc`

## Getting Help

- See `README.md` for full documentation
- See `INSTALLATION.md` for more setup options
- Check the script output for errors when running `generate_dashboard.py`

---

Enjoy your new visual project launcher! 🎨✨
