#!/usr/bin/env python3
"""Open existing or start a detached local studio, then open the browser."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

from mochi_paths import root_dir, app_dir
ROOT = root_dir(__file__)
STATE_DIR = ROOT / '.mochi'
SESSION = STATE_DIR / 'server.json'
LOG = STATE_DIR / 'studio.log'
from version import APP_VERSION


def valid_session():
    try:
        data = json.loads(SESSION.read_text(encoding='utf-8'))
        port = int(data['port'])
        key = data['key']
        if not 1024 <= port <= 65535 or not isinstance(key, str) or len(key) < 20:
            return None
        req = urllib.request.Request(f'http://127.0.0.1:{port}/api/health', headers={'X-Mochi-Key': key})
        with urllib.request.urlopen(req, timeout=0.6) as r:
            health = json.loads(r.read())
        if health.get('ok') is True:
            base = f'http://127.0.0.1:{port}'
            open_url = f'{base}/?key={quote(key)}'
            if health.get('version') == APP_VERSION:
                # A running studio must serve the *real* UI assets, not just a
                # healthy JSON endpoint. Catch stale or partially updated installs.
                try:
                    asset = urllib.request.Request(base + '/assets/hero-bunny.png',
                                                   headers={'X-Mochi-Key': key})
                    with urllib.request.urlopen(asset, timeout=1.5) as reply:
                        if reply.read(8) == b'\x89PNG\r\n\x1a\n':
                            return open_url
                except (OSError, urllib.error.URLError):
                    pass
                print('Mochi found an outdated or incomplete studio. Restarting it safely…')
            # User has replaced Mochi files while an older server runs.
            # Never interrupt an active download/transcription for an upgrade.
            req = urllib.request.Request(base+'/api/status', headers={'X-Mochi-Key':key})
            with urllib.request.urlopen(req, timeout=0.6) as r:
                status = json.loads(r.read())
            if status.get('state') in ('working', 'repairing'):
                print('A video is still running. Mochi will load the upgrade on your next Run Mochi Now.')
                return open_url
            req = urllib.request.Request(base+'/api/shutdown', data=b'{}',
                                         headers={'X-Mochi-Key':key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req, timeout=2) as r:
                r.read()
            # Wait for prior server to release its listener before starting fresh.
            for _ in range(30):
                try:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/health',headers={'X-Mochi-Key':key}), timeout=.2)
                except (OSError, urllib.error.URLError):
                    break
                time.sleep(.1)
            return None
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        pass
    return None


def launch():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    current = valid_session()
    if not current:
        with LOG.open('a', encoding='utf-8') as logfile:
            kwargs = {'cwd': str(ROOT), 'stdin': subprocess.DEVNULL, 'stdout': logfile, 'stderr': logfile}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            else:
                kwargs['start_new_session'] = True
            subprocess.Popen([sys.executable, str(app_dir(ROOT) / 'studio.py')], **kwargs)
        for _ in range(150):
            time.sleep(0.1)
            current = valid_session()
            if current:
                break
    if not current:
        print('Mochi could not start. Open .mochi/studio.log to see why.')
        raise SystemExit(1)
    print('Opening Mochi in your browser…')
    if not webbrowser.open(current, new=2):
        print('Open this local link in your browser:', current)
    return current


if __name__ == '__main__':
    launch()
