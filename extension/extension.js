// Project Server Launcher
//
// Adds a status-bar "Run server" button (plus commands + hotkeys) that launches
// the current project's dev server. How to start it comes from the optional
// `server` block in the project's catalogue.json, or is auto-detected. This is
// the in-editor companion to the cursor-launcher dashboard and uses the same
// catalogue schema.

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

let statusBarItem;
let runTerminal = null;
let runningInfo = null;

// --------------------------------------------------------------------------- //
// catalogue.json + auto-detection (JS port of server_launcher.py)
// --------------------------------------------------------------------------- //
function readCatalogue(folderPath) {
  try {
    const p = path.join(folderPath, 'catalogue.json');
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch (e) {
    /* ignore malformed catalogue */
  }
  return {};
}

function autodetectType(folderPath) {
  const pkgPath = path.join(folderPath, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
      const s = data.scripts || {};
      if (s.dev || s.start) return 'node';
    } catch (e) {
      /* ignore */
    }
  }
  if (fs.existsSync(path.join(folderPath, 'index.html'))) return 'static';
  for (const f of ['manage.py', 'app.py', 'main.py']) {
    if (fs.existsSync(path.join(folderPath, f))) return 'python';
  }
  return null;
}

// Shell snippet that frees a TCP port before (re)starting a server.
function freePort(port) {
  return `pids=$(lsof -ti:${port} 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; `;
}

function resolveNode(folderPath, port) {
  let isVite = ['vite.config.ts', 'vite.config.js', 'vite.config.mjs'].some((f) =>
    fs.existsSync(path.join(folderPath, f))
  );
  let scripts = {};
  let deps = {};
  try {
    const data = JSON.parse(fs.readFileSync(path.join(folderPath, 'package.json'), 'utf8'));
    scripts = data.scripts || {};
    deps = Object.assign({}, data.dependencies, data.devDependencies);
  } catch (e) {
    /* ignore */
  }
  if (deps.vite) isVite = true;
  const hasNext = !!deps.next;
  const script = scripts.dev ? 'dev' : scripts.start ? 'start' : 'dev';

  let cmd;
  if (isVite) {
    port = port || 5173;
    cmd = `npm run ${script} -- --port ${port} --strictPort`;
  } else if (hasNext) {
    port = port || 3000;
    cmd = `npm run ${script} -- -p ${port}`;
  } else {
    port = port || 3000;
    cmd = `npm run ${script}`;
  }
  return { port, cmd };
}

function resolvePython(folderPath, port) {
  if (fs.existsSync(path.join(folderPath, 'manage.py'))) return `python3 manage.py runserver ${port}`;
  if (fs.existsSync(path.join(folderPath, 'app.py'))) return 'python3 app.py';
  if (fs.existsSync(path.join(folderPath, 'main.py'))) return 'python3 main.py';
  return `python3 -m http.server ${port}`;
}

function resolveServer(folderPath) {
  const meta = readCatalogue(folderPath);
  const srv = (meta && meta.server) || {};
  let type = srv.type;
  const command = srv.command;
  let port = srv.port;
  let openPath = srv.openPath;
  const host = srv.host || 'localhost';
  const autoStart = !!srv.autoStart;

  if (!type && !command) type = autodetectType(folderPath);
  if (!type && !command) return { available: false };

  let cmd;
  if (command) {
    type = type || 'custom';
    port = port || 8080;
    cmd = command;
  } else if (type === 'static') {
    port = port || 8080;
    // Prefer live-server (hot reload) when installed, else Python http.server.
    cmd = `command -v live-server >/dev/null 2>&1 && live-server --port=${port} --no-browser --quiet . || python3 -m http.server ${port}`;
  } else if (type === 'liveserver') {
    port = port || 8080;
    cmd = `npx --yes live-server --port=${port} --no-browser --quiet .`;
  } else if (type === 'node') {
    const r = resolveNode(folderPath, port);
    port = r.port;
    cmd = r.cmd;
  } else if (type === 'python') {
    port = port || 8000;
    cmd = resolvePython(folderPath, port);
  } else {
    return { available: false };
  }

  if (!openPath) openPath = '/';
  if (!openPath.startsWith('/')) openPath = '/' + openPath;

  return {
    available: true,
    type,
    cmd: freePort(port) + cmd,
    port,
    host,
    openPath,
    url: `http://${host}:${port}${openPath}`,
    autoStart,
  };
}

// --------------------------------------------------------------------------- //
// UI + commands
// --------------------------------------------------------------------------- //
function getFolder() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) return null;
  return folders[0].uri.fsPath;
}

function updateStatusBar() {
  const folder = getFolder();
  if (!folder) {
    statusBarItem.hide();
    return;
  }
  if (runningInfo) {
    statusBarItem.text = `$(debug-stop) Stop :${runningInfo.port}`;
    statusBarItem.tooltip = `Stop ${runningInfo.type} server (${runningInfo.url})  ·  Cmd+Alt+Shift+R`;
    statusBarItem.command = 'projectLauncher.stopServer';
    statusBarItem.show();
    return;
  }
  const info = resolveServer(folder);
  if (info.available) {
    statusBarItem.text = `$(play) Run :${info.port}`;
    statusBarItem.tooltip = `Launch ${info.type} dev server on port ${info.port} → ${info.url}  ·  Cmd+Alt+R`;
    statusBarItem.command = 'projectLauncher.runServer';
    statusBarItem.show();
  } else {
    statusBarItem.hide();
  }
}

function openInChrome(url) {
  // macOS: open in Google Chrome; fall back to the default browser.
  if (process.platform === 'darwin') {
    cp.exec(`open -a "Google Chrome" "${url}"`, (err) => {
      if (err) vscode.env.openExternal(vscode.Uri.parse(url));
    });
  } else {
    vscode.env.openExternal(vscode.Uri.parse(url));
  }
}

function openPreview(info) {
  const cfg = vscode.workspace.getConfiguration('projectLauncher');
  if (!cfg.get('openPreview', true)) return;
  const target = cfg.get('previewTarget', 'chrome');
  const delay = info.type === 'static' ? 800 : 3000;
  setTimeout(() => {
    if (target === 'simpleBrowser') {
      vscode.commands.executeCommand('simpleBrowser.show', info.url);
    } else if (target === 'default') {
      vscode.env.openExternal(vscode.Uri.parse(info.url));
    } else {
      openInChrome(info.url);
    }
  }, delay);
}

function runServer() {
  const folder = getFolder();
  if (!folder) {
    vscode.window.showWarningMessage('Project Launcher: open a project folder first.');
    return;
  }
  const info = resolveServer(folder);
  if (!info.available) {
    vscode.window.showWarningMessage(
      'Project Launcher: no dev server configured (add a "server" block to catalogue.json) or auto-detected for this project.'
    );
    return;
  }

  if (runningInfo && runTerminal) {
    runTerminal.show();
  } else {
    runTerminal = vscode.window.createTerminal({ name: 'Dev Server', cwd: folder });
    runTerminal.show(true);
    runTerminal.sendText(info.cmd);
    runningInfo = info;
  }
  updateStatusBar();
  openPreview(info);
  vscode.window.showInformationMessage(`Project Launcher: starting ${info.type} server at ${info.url}`);
}

function stopServer() {
  const port = runningInfo && runningInfo.port;
  if (runTerminal) {
    runTerminal.dispose();
    runTerminal = null;
  }
  // Free the port in case dev-server children outlive the shell.
  if (port) {
    const t = vscode.window.createTerminal({ name: 'stop-server', hideFromUser: true });
    t.sendText(`pids=$(lsof -ti:${port} 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; exit`);
    setTimeout(() => t.dispose(), 1500);
  }
  runningInfo = null;
  updateStatusBar();
  vscode.window.showInformationMessage('Project Launcher: stopped dev server.');
}

function activate(context) {
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  context.subscriptions.push(statusBarItem);
  context.subscriptions.push(
    vscode.commands.registerCommand('projectLauncher.runServer', runServer),
    vscode.commands.registerCommand('projectLauncher.stopServer', stopServer),
    vscode.workspace.onDidChangeWorkspaceFolders(updateStatusBar),
    vscode.window.onDidCloseTerminal((t) => {
      if (t === runTerminal) {
        runTerminal = null;
        runningInfo = null;
        updateStatusBar();
      }
    })
  );
  updateStatusBar();
}

function deactivate() {
  if (runTerminal) runTerminal.dispose();
}

module.exports = { activate, deactivate };
