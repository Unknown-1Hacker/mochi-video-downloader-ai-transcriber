"""Transactional, minimal first-run layout and portable OS launchers."""
from __future__ import annotations
import os
import shutil
import sys
import subprocess
import plistlib
import json
import urllib.request
from pathlib import Path
from mochi_paths import root_dir

ROOT = root_dir(__file__)
STATE = ROOT / '.mochi'
STAGED = ROOT / 'app'
LIVE = STATE / 'app'
BACKUP = STATE / 'app.previous'
NEXT = STATE / 'app.next'
README_NAME = '📖 READ ME.txt'
README = """✦ MOCHI VIDEO STUDIO ✦
======================

▶ Double-click  Run Mochi Now
🔗 Paste a YouTube link
🎬 Pick video / audio / subtitles / text
✨ Press Make it happen
📂 Saved files: tap Open my saved files after completion.

🛠 Stuck? Tap Fix my tools (top right).
💾 Your downloads stay on this computer.
💜 Made with love by 1Hack — OneHack.st
"""

# Exact files shipped by the installer or older Mochi versions; never glob-delete.
OLD_FILES = (
    '1 INSTALL & OPEN - Linux.sh', '1 INSTALL & OPEN - Mac.command',
    '1 INSTALL & OPEN - Windows.cmd', 'README - START HERE.txt',
    'LOOK - PREVIEW.png', 'UPDATE - READ ME.txt',
    'Run Me.command', 'Run Me.sh', 'Run Me.desktop', 'Run Me.cmd',
)


def _copy_our_icon():
    dst = STATE / 'icons'
    dst.mkdir(parents=True, exist_ok=True)
    for name in ('mochi.png', 'favicon.ico', 'mochi.icns'):
        source = LIVE / 'assets' / name
        if source.exists():
            shutil.copy2(source, dst / name)


def _write_run_sh():
    script = STATE / 'run.sh'
    script.write_text('''#!/bin/sh
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE="$ROOT/.mochi"
PY="$STATE/venv/bin/python"
APP="$STATE/app"
if [ ! -x "$PY" ] || ! "$PY" -c 'import importlib.util as u; assert u.find_spec("yt_dlp") and u.find_spec("faster_whisper")' >/dev/null 2>&1; then
  /bin/sh "$APP/bootstrap.sh" || exit $?
  exit 0
fi
if [ ! -x "$STATE/deno/bin/deno" ] && ! command -v deno >/dev/null 2>&1; then
  /bin/sh "$APP/bootstrap.sh" || exit $?
  exit 0
fi
export PATH="$STATE/deno/bin:$PATH"
"$PY" "$APP/launcher.py" >> "$STATE/launch.log" 2>&1
CODE=$?
if [ "$CODE" -ne 0 ]; then
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title='Mochi needs help' --text='Could not open Mochi. Check .mochi/launch.log or try setup again.' 2>/dev/null || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send 'Mochi needs help' 'Open .mochi/launch.log for details' || true
  elif command -v osascript >/dev/null 2>&1; then
    osascript -e 'display alert "Mochi needs help" message "See .mochi/launch.log"' >/dev/null 2>&1 || true
  fi
fi
exit "$CODE"
''', encoding='utf-8')
    script.chmod(0o755)


def _write_run_ps1():
    (STATE / 'run.ps1').write_text(r'''$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$State = Join-Path $Root '.mochi'
$Py = Join-Path $State 'venv\Scripts\python.exe'
$App = Join-Path $State 'app'
try {
    $NeedSetup = -not (Test-Path $Py)
    if (-not $NeedSetup) {
        & $Py -c 'import importlib.util as u; assert u.find_spec("yt_dlp") and u.find_spec("faster_whisper")'
        if ($LASTEXITCODE -ne 0) { $NeedSetup = $true }
    }
    if (-not (Test-Path (Join-Path $State 'deno\bin\deno.exe')) -and -not (Get-Command deno.exe -ErrorAction SilentlyContinue)) { $NeedSetup = $true }
    if ($NeedSetup) {
        & (Join-Path $App 'bootstrap.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Setup could not finish.' }
    } else {
        $env:PATH = (Join-Path $State 'deno\bin') + ';' + $env:PATH
        & $Py (Join-Path $App 'launcher.py') *> (Join-Path $State 'launch.log')
        if ($LASTEXITCODE -ne 0) { throw 'Could not open Mochi.' }
    }
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('Mochi needs help. Open .mochi\launch.log in this folder, or run setup again.', 'Mochi') | Out-Null
    exit 1
}
''',encoding='utf-8')


def _write_mac_app():
    app = ROOT / 'Run Mochi Now.app'
    macos = app / 'Contents' / 'MacOS'
    resources = app / 'Contents' / 'Resources'
    macos.mkdir(parents=True,exist_ok=True)
    resources.mkdir(parents=True,exist_ok=True)
    plist = {'CFBundleIdentifier':'st.onehack.mochi', 'CFBundleName':'Mochi Video Studio',
             'CFBundleDisplayName':'Run Mochi Now', 'CFBundleExecutable':'Mochi',
             'CFBundleIconFile':'mochi.icns', 'CFBundlePackageType':'APPL',
             'CFBundleVersion':'1.3.0', 'CFBundleShortVersionString':'1.3.0',
             'NSHighResolutionCapable':True}
    with (app/'Contents'/'Info.plist').open('wb') as f:plistlib.dump(plist,f)
    shutil.copy2(STATE/'icons'/'mochi.icns', resources/'mochi.icns')
    entry = macos/'Mochi'
    entry.write_text('''#!/bin/sh
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
exec /bin/sh "$ROOT/.mochi/run.sh"
''',encoding='utf-8')
    entry.chmod(0o755)


def _write_linux_desktop():
    # Desktop Exec escapes unsafe path characters; Path is absolute by design.
    p = str(STATE / 'run.sh').replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')
    desktop = ROOT/'Run Mochi Now.desktop'
    desktop.write_text('[Desktop Entry]\nType=Application\nVersion=1.0\nName=Run Mochi Now\nComment=Your cozy video studio\n'
                       'Exec=/bin/sh "'+p+'"\nIcon='+str(STATE/'icons'/'mochi.png')+'\nTerminal=false\nCategories=AudioVideo;\nStartupNotify=true\n',encoding='utf-8')
    desktop.chmod(0o755)
    # Trust hint for GNOME; certain setups may still request Allow Launching.
    if shutil.which('gio'):
        subprocess.run(['gio','set',str(desktop),'metadata::trusted','true'],capture_output=True,check=False,timeout=5)


def _write_windows_link():
    # Windows shortcut, real embedded ICO; its target remains under hidden .mochi.
    temp = STATE/'create-shortcut.ps1'
    temp.write_text(r'''$Root = Split-Path -Parent $PSScriptRoot
$Wsh = New-Object -ComObject WScript.Shell
$Lnk = $Wsh.CreateShortcut((Join-Path $Root 'Run Mochi Now.lnk'))
$Lnk.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
$Lnk.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $Root '.mochi\run.ps1') + '"'
$Lnk.WorkingDirectory = $Root
$Lnk.IconLocation = (Join-Path $Root '.mochi\icons\favicon.ico') + ',0'
$Lnk.Description = 'Run Mochi Video Studio'
$Lnk.Save()
''',encoding='utf-8')
    try:
        subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(temp)],check=True,timeout=30)
    finally:
        temp.unlink(missing_ok=True)


def prepare():
    STATE.mkdir(parents=True,exist_ok=True)
    if not STAGED.is_dir():
        if LIVE.is_dir():
            _copy_our_icon()
            return
        raise RuntimeError('Mochi installation files are missing.')
    if NEXT.exists():
        shutil.rmtree(NEXT)
    # Heal an interrupted prior upgrade before attempting another one.
    if BACKUP.exists():
        rollback()
    shutil.copytree(STAGED,NEXT,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if LIVE.exists():
        # Interrupted previous upgrade? Don't destroy the original backup.
        if BACKUP.exists():
            raise RuntimeError('Previous update backup exists. Do not overwrite until recovery.')
        LIVE.rename(BACKUP)
    NEXT.rename(LIVE)
    _copy_our_icon()
    _write_run_sh()
    _write_run_ps1()
    if os.name=='nt':
        try:
            _write_windows_link()
        except (OSError, subprocess.SubprocessError):
            # Native shortcuts may be disabled by policy; retain one plain launcher.
            (ROOT/'Run Mochi Now.cmd').write_text(
                '@echo off\r\ncd /d "%~dp0"\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0.mochi\\run.ps1"\r\n',
                encoding='ascii')
    elif sys.platform=='darwin':
        _write_mac_app()
    else:
        _write_linux_desktop()


def _older_app_is_busy():
    # Protect a live download during an in-place upgrade from an older Mochi.
    try:
        session=json.loads((STATE/'server.json').read_text(encoding='utf-8'))
        base=f"http://127.0.0.1:{int(session['port'])}"
        head={'X-Mochi-Key':session['key']}
        def get(path):
            with urllib.request.urlopen(urllib.request.Request(base+path,headers=head),timeout=1) as r:
                return json.load(r)
        health=get('/api/health')
        if health.get('version')=='1.3.0':
            return False
        return get('/api/status').get('state') in ('working','repairing')
    except (OSError,ValueError,KeyError,TypeError):
        return False


def _migrate_old_downloads():
    # Non-destructive move of original user media into the app's hidden data home.
    old=ROOT/'My Downloads'
    dst=STATE/'Downloads'
    if not old.is_dir():
        return
    if not dst.exists():
        try:
            old.rename(dst)
            return
        except OSError:
            pass  # Locked or restricted folders must never abort safe setup.
    dst.mkdir(parents=True, exist_ok=True)
    # Never overwrite a name conflict or delete a user's file. Leave conflicts in place.
    for item in old.iterdir():
        if not (dst/item.name).exists():
            try:
                shutil.move(str(item),str(dst/item.name))
            except OSError:
                pass  # Leave an inaccessible user file untouched.
    try:
        if not any(old.iterdir()):
            old.rmdir()
    except OSError:
        pass



def _organize_repository_extras():
    """Hide known GitHub source extras after ZIP install, preserving every byte.

    Never touch checked-out git repositories or unrelated existing files.
    """
    if (ROOT / '.git').exists():
        return
    owned = {
        'README.md': '# 🐰 Mochi — Video Downloader & AI Transcriber',
        'pytest.ini': '[pytest]\npythonpath = app',
        '.gitignore': '# Mochi generated files and private user data',
    }
    extras = []
    for name, marker in owned.items():
        src = ROOT / name
        try:
            if src.is_file() and src.read_text(encoding='utf-8').startswith(marker):
                extras.append(src)
        except (OSError, UnicodeError):
            pass
    docs = ROOT / 'docs'
    if docs.is_dir() and {p.name for p in docs.iterdir()} == {'mochi-interface.png'}:
        extras.append(docs)
    workflows = ROOT / '.github'
    if workflows.is_dir() and (workflows/'workflows'/'tests.yml').is_file():
        extras.append(workflows)
    if not extras:
        return
    store = STATE / 'source-extras'
    store.mkdir(parents=True, exist_ok=True)
    for src in extras:
        dst = store / src.name
        if dst.exists():
            # Preserve both copies, even when a source file changed between upgrades.
            index = 2
            while (store / f'{src.name}.{index}').exists():
                index += 1
            dst = store / f'{src.name}.{index}'
        try:
            shutil.move(str(src), str(dst))
        except OSError:
            pass  # A locked or protected source file is left untouched.


def finish():
    # Only after the browser was opened and the service health check succeeded.
    if _older_app_is_busy():
        raise RuntimeError('An older Mochi is still working. Your files are safe; run setup again after it finishes.')
    if not LIVE.is_dir():
        raise RuntimeError('Installed app is missing; keeping setup files for recovery.')
    _migrate_old_downloads()
    (ROOT/README_NAME).write_text(README,encoding='utf-8')
    # Retire only the exact old Mochi README, never unrelated personal notes.
    legacy=ROOT/'README.txt'
    if legacy.is_file():
        try:
            old=legacy.read_text(encoding='utf-8')
            if old.startswith('✦ MOCHI') and 'Made with love by 1Hack' in old:
                legacy.unlink()
        except (OSError,UnicodeError):
            pass
    # Never touch arbitrary files, non-Mochi folders, or user downloads.
    if STAGED.is_dir():
        shutil.rmtree(STAGED)
    if BACKUP.is_dir():
        shutil.rmtree(BACKUP)
    for name in OLD_FILES:
        f=ROOT/name
        if f.is_file() or f.is_symlink():f.unlink(missing_ok=True)
    _organize_repository_extras()
    if os.name=='nt':
        subprocess.run(['attrib','+h',str(STATE)],capture_output=True,check=False)


def rollback():
    # Keep setup files visible if startup fails. Revert upgrade when safe.
    if BACKUP.is_dir():
        if LIVE.is_dir():shutil.rmtree(LIVE)
        BACKUP.rename(LIVE)


if __name__=='__main__':
    option=sys.argv[1] if len(sys.argv)>1 else ''
    {'prepare':prepare,'finish':finish,'rollback':rollback}[option]()