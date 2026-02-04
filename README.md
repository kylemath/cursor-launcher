# Cursor Project Launcher Dashboard

A beautiful, visual dashboard to quickly open your coding projects in Cursor. Automatically generated from your project `catalogue.json` files and screenshots.

## Features

- 🎨 Beautiful card-based interface with project screenshots
- 🔍 Real-time search to filter projects
- 📁 Organized by category (RESEARCH, TEACHING, TOOLS, PUZZLES)
- 🚀 One-click to open projects in Cursor
- 📊 Automatic sorting by last modified date
- 🏷️ Shows project tags and descriptions

## Quick Start

1. **Generate the dashboard:**
   ```bash
   cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher
   python generate_dashboard.py
   ```

2. **Open the dashboard:**
   - Open `dashboard.html` in any web browser
   - Or run: `open dashboard.html`
   - Bookmark it for quick access!

3. **Click any project card** to open it in Cursor

## How It Works

The script scans your `/Users/kylemathewson/Coding/` directory for:
- `catalogue.json` - Project metadata
- `screenshot.png` - Project screenshot

It then generates a beautiful HTML dashboard with clickable cards that use the `cursor://file/` protocol to open projects directly in Cursor.

## Refreshing the Dashboard

To update the dashboard with new projects or changes:

```bash
python generate_dashboard.py
```

The dashboard will automatically:
- Find new projects with `catalogue.json` files
- Update screenshots
- Sort by last modified date
- Regenerate the HTML

## Automating Updates

### Option 1: Manual Refresh
Just run the script whenever you want to update.

### Option 2: Add to Your Workflow
Add this to your project setup workflow:
```bash
# After creating a new project with catalogue.json
cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher
python generate_dashboard.py
```

### Option 3: Git Hook (Future)
You could create a git hook to regenerate after commits to projects with `catalogue.json`.

### Option 4: Cron Job
Run daily at 9 AM:
```bash
crontab -e
# Add this line:
0 9 * * * cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher && python generate_dashboard.py
```

## Customization

Edit `generate_dashboard.py` to customize:

- **Search directories**: Change `SEARCH_DIRS` list
- **Styling**: Modify the CSS in the `generate_html()` function
- **Card layout**: Adjust `grid-template-columns` in CSS
- **Categories**: Add/remove directories to scan

## Requirements

- Python 3.6+
- No external dependencies (uses only stdlib)

## catalogue.json Format

Your projects should have a `catalogue.json` file in their root:

```json
{
  "id": "ProjectName",
  "title": "My Awesome Project",
  "oneLiner": "A brief description of what this project does",
  "kind": "project",
  "categories": ["research", "eeg"],
  "tags": ["python", "data", "analysis"],
  "status": "active"
}
```

## Tips

1. **Bookmark the dashboard** in your browser for instant access
2. **Set as browser homepage** to see your projects every time you open a new window
3. **Use the search** to quickly find projects by name, description, or path
4. **Add screenshots** to all projects for better visual navigation

## Troubleshooting

**Projects not showing up?**
- Ensure the project has a `catalogue.json` file
- Check that the project is in one of the scanned directories
- Run the script with verbose output to see what's being found

**Cursor not opening?**
- Make sure Cursor is installed and the `cursor://` protocol is registered
- Try opening Cursor manually first
- Check that the project path is correct

**Screenshots not displaying?**
- Ensure `screenshot.png` exists in the project root
- Check file permissions
- Try regenerating the dashboard

## Future Enhancements

- [ ] Add filter by tags/categories
- [ ] Recent projects section
- [ ] Favorites/pinned projects
- [ ] Dark mode toggle
- [ ] GitHub Actions integration
- [ ] VS Code support alongside Cursor
- [ ] Project statistics (files, size, etc.)
