# Installation Guide for Cursor Project Launcher

## Quick Access Options

### Option 1: Shell Alias (Recommended)

Add this to your `~/.zshrc` file:

```bash
# Cursor Project Dashboard
alias projects='cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher && ./launch.sh'
```

Then reload your shell:
```bash
source ~/.zshrc
```

Now you can type `projects` from anywhere to regenerate and open your dashboard!

### Option 2: Dock Shortcut (macOS)

1. Open the dashboard in Safari or Chrome:
   ```
   file:///Users/kylemathewson/Coding/TOOLS/cursor-launcher/dashboard.html
   ```

2. In Safari: `File > Add to Dock`
   In Chrome: `More Tools > Create Shortcut` (check "Open as window")

### Option 3: Browser Homepage

Set your browser's homepage to:
```
file:///Users/kylemathewson/Coding/TOOLS/cursor-launcher/dashboard.html
```

**Chrome:** Settings > Appearance > Show home button > Enter custom web address
**Safari:** Preferences > General > Homepage
**Firefox:** Preferences > Home > Custom URLs

### Option 4: Spotlight/Alfred

Make the script searchable by Spotlight:

1. Rename `launch.sh` to `CursorProjects.command`
2. Now you can type "CursorProjects" in Spotlight to launch it

### Option 5: Keyboard Shortcut (macOS)

Create an Automator Quick Action:

1. Open Automator > New Document > Quick Action
2. Add "Run Shell Script" action
3. Paste:
   ```bash
   /Users/kylemathewson/Coding/TOOLS/cursor-launcher/launch.sh
   ```
4. Save as "Open Cursor Dashboard"
5. Go to System Preferences > Keyboard > Shortcuts > Services
6. Find "Open Cursor Dashboard" and assign a keyboard shortcut (e.g., ⌘⇧P)

## Automatic Updates

### Option A: Daily Cron Job

Edit your crontab:
```bash
crontab -e
```

Add this line to regenerate every morning at 9 AM:
```bash
0 9 * * * cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher && python3 generate_dashboard.py
```

### Option B: Git Hook

Add to your git workflow - regenerate when you commit projects:

Create `.git/hooks/post-commit` in your main coding directory:
```bash
#!/bin/bash
cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher
python3 generate_dashboard.py
```

Make it executable:
```bash
chmod +x .git/hooks/post-commit
```

### Option C: Launch Agent (macOS)

Create `~/Library/LaunchAgents/com.cursor.dashboard.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cursor.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/kylemathewson/Coding/TOOLS/cursor-launcher/generate_dashboard.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
```

Load it:
```bash
launchctl load ~/Library/LaunchAgents/com.cursor.dashboard.plist
```

## GitHub Actions Integration

If you want to sync with your public homepage workflow, you can add the dashboard generation to your existing GitHub Actions:

Add to `.github/workflows/update-all-and-deploy.yml`:

```yaml
- name: Generate Local Dashboard
  run: |
    cd /Users/kylemathewson/Coding/TOOLS/cursor-launcher
    python3 generate_dashboard.py
```

## Tips

- **Bookmark it**: Press ⌘D when the dashboard is open
- **Pin tab**: Right-click the tab > Pin Tab (keeps it always available)
- **Second monitor**: Keep it open on a second screen for quick access
- **Mobile access**: You can also view it on your phone if you set up local network access

## Troubleshooting

**"Command not found: projects"**
- Make sure you added the alias to `.zshrc` and ran `source ~/.zshrc`

**Dashboard not updating**
- Run `python3 generate_dashboard.py` manually to see any errors
- Check that your projects have valid `catalogue.json` files

**Cursor not opening on click**
- Verify Cursor is installed
- Check that the `cursor://` protocol handler is registered
- Try running `cursor .` in a terminal to test

**Permission denied**
- Run `chmod +x launch.sh` in the cursor-launcher directory
