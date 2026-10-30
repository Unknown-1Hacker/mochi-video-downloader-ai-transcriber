#!/usr/bin/env python3
"""Mochi local-only browser studio. All downloads and AI work stay on this computer."""
from __future__ import annotations
import html
import importlib
import json
import os
import secrets
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from core import FriendlyError, UserCancelled, check_url, choices, info_for, process
from doctor import RepairError, is_extractor_problem, repair, remember_fix, recently_failed

APP_VERSION = '1.3.0'
from mochi_paths import root_dir, app_dir, output_dir
ROOT = root_dir(__file__)
STATE_DIR = ROOT / '.mochi'
OUTPUT_DIR = output_dir(ROOT)


class JobState:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.data = {'state': 'ready', 'message': 'Ready for your link ✨', 'percent': 0, 'files': [], 'folder': ''}
        self.active = False

    def read(self):
        with self.lock:
            return self.data.copy()

    def update(self, message, percent=None, **kwargs):
        with self.lock:
            self.data.update(message=message, **kwargs)
            if percent is not None:
                self.data['percent'] = percent

    def begin(self, url, options):
        with self.lock:
            if self.active:
                raise FriendlyError('Mochi is finishing a video. Please wait or cancel it first.')
            self.active = True
            self.cancel.clear()
            self.data = {'state': 'working', 'message': 'Getting everything ready…', 'percent': 0, 'files': [], 'folder': ''}
        threading.Thread(target=self._work, args=(url, options), daemon=True).start()

    def repair_tools(self):
        with self.lock:
            if self.active:
                raise FriendlyError('Mochi is busy. Finish or cancel this job first.')
            self.active = True
            self.cancel.clear()
            self.data = {'state': 'repairing', 'message': 'Checking your tools…', 'percent': 0, 'files': [], 'folder': ''}
        threading.Thread(target=self._repair_worker, daemon=True).start()

    def _repair_worker(self):
        try:
            repair(ROOT, self.update, cancelled=self.cancel)
            remember_fix(ROOT, 'tools', 'repair_dependencies', True)
            self.update('All fixed! Paste a link and try again ✨', 100, state='repaired')
        except (RepairError, FriendlyError, OSError) as e:
            remember_fix(ROOT, 'tools', 'repair_dependencies', False)
            self.update(str(e), 0, state='error')
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            self.update('Could not repair everything automatically. Click Fix my tools or double-click Run Mochi Now again.', 0, state='error')
        finally:
            with self.lock:
                self.active = False

    def _work(self, url, options):
        try:
            try:
                files = process(url, ROOT, OUTPUT_DIR, options, self.update, self.cancel)
            except Exception as first:
                # Self-repair ONCE for recognized downloader drift; all other
                # failures remain visible, with no repeated blind installs.
                if (self.cancel.is_set() or not is_extractor_problem(first)
                        or recently_failed(ROOT, 'extractor', 'update_downloader')):
                    raise
                self.update('YouTube changed something. Checking the downloader once…', 10)
                try:
                    repair(ROOT, self.update, only_downloader=True, cancelled=self.cancel)
                except (RepairError, OSError) as repair_error:
                    remember_fix(ROOT, 'extractor', 'update_downloader', False)
                    raise FriendlyError(f'Could not update downloader: {repair_error}') from first
                # Reload just upgraded extractor code in this running process.
                # Otherwise a retry would silently reuse the old imported version.
                for module_name in list(sys.modules):
                    if module_name == 'yt_dlp' or module_name.startswith('yt_dlp.'):
                        del sys.modules[module_name]
                importlib.invalidate_caches()
                self.update('Downloader updated. Retrying your video…', 12)
                try:
                    files = process(url, ROOT, OUTPUT_DIR, options, self.update, self.cancel)
                except Exception:
                    remember_fix(ROOT, 'extractor', 'update_downloader', False)
                    raise
                remember_fix(ROOT, 'extractor', 'update_downloader', True)
            folder = str(files[0].parent)
            self.update('All done! Your files are ready 💜', 100, state='done', files=[p.name for p in files], folder=folder)
        except UserCancelled:
            self.update('Cancelled. You can start another video.', 0, state='cancelled')
        except FriendlyError as e:
            self.update(str(e), 0, state='error')
        except Exception as e:
            msg = str(e).strip() or type(e).__name__
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            hint = ('Tap Fix my tools at the top, or check .mochi/studio.log for details.'
                    if any(x in msg.lower() for x in ('metadata_errors', 'missing', 'nsig', 'javascript', 'deno'))
                    else 'See .mochi/studio.log for details, or retry.')
            self.update(f'Something went wrong: {msg[:230]}. {hint}', 0, state='error')
        finally:
            with self.lock:
                self.active = False


JOB = JobState()


class WebHandler(BaseHTTPRequestHandler):
    server_version = 'Mochi/1.0'

    def log_message(self, fmt, *args):
        # Quiet, but retain unexpected HTTP errors in local log.
        if args and str(args[1] if len(args) > 1 else '').startswith(('4', '5')):
            super().log_message(fmt, *args)

    def _json(self, code, data):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _file(self, name, mime):
        data = (app_dir(ROOT) / 'assets' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        key = self.headers.get('X-Mochi-Key', '')
        if not secrets.compare_digest(key, self.server.secret):
            self._json(403, {'error': 'This local session is not authorized. Open the app through Run Mochi Now.'})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == '/':
            provided = parse_qs(path.query).get('key', [''])[0]
            if not secrets.compare_digest(provided, self.server.secret):
                self._json(403, {'error': 'Open with Run Mochi Now to start your private local session.'})
                return
            content = (app_dir(ROOT) / 'assets' / 'index.html').read_text(encoding='utf-8').replace('__MOCHI_KEY__', self.server.secret)
            data = content.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path.path == '/assets/app.js':
            self._file('app.js', 'text/javascript; charset=utf-8')
        elif path.path == '/assets/style.css':
            self._file('style.css', 'text/css; charset=utf-8')
        elif path.path == '/api/status':
            if self._authorized():
                self._json(200, JOB.read())
        elif path.path == '/api/health':
            if self._authorized():
                self._json(200, {'ok': True, 'version': APP_VERSION})
        elif path.path == '/favicon.ico':
            self._file('favicon.ico', 'image/x-icon')
        elif path.path == '/assets/mochi.svg':
            self._file('mochi.svg', 'image/svg+xml')
        elif path.path == '/assets/mochi.png':
            self._file('mochi.png', 'image/png')
        else:
            self._json(404, {'error': 'Not found.'})

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed_origin = f'http://127.0.0.1:{self.server.server_address[1]}'
        if origin is not None and origin != allowed_origin:
            self._json(403, {'error': 'Access denied.'})
            return
        if not self._authorized():
            return
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n < 0 or n > 8192:
                raise FriendlyError('Request is too large.')
            data = json.loads(self.rfile.read(n)) if n else {}
            if not isinstance(data, dict):
                raise FriendlyError('Please send a valid request.')
            if self.path == '/api/start':
                url = check_url(data.get('url', ''))
                opts = data.get('options', {})
                if not isinstance(opts, dict):
                    raise FriendlyError('Please choose a valid output.')
                JOB.begin(url, opts)
                self._json(200, {'ok': True})
            elif self.path == '/api/qualities':
                url = check_url(data.get('url', ''))
                if JOB.active:
                    raise FriendlyError('Finish or cancel the current video before checking qualities.')
                info = info_for(url, ROOT)
                self._json(200, {'title': info.get('title', 'YouTube video'), 'heights': choices(info)})
            elif self.path == '/api/cancel':
                JOB.cancel.set()
                self._json(200, {'ok': True})
            elif self.path == '/api/repair':
                JOB.repair_tools()
                self._json(200, {'ok': True})
            elif self.path == '/api/open':
                if JOB.read().get('state') != 'done':
                    raise FriendlyError('No completed files to open yet.')
                target = Path(JOB.read()['folder']).resolve()
                if not target.is_dir() or not target.is_relative_to(OUTPUT_DIR.resolve()):
                    raise FriendlyError('Saved folder could not be found.')
                if os.name == 'nt':
                    os.startfile(str(target))
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', str(target)])
                else:
                    subprocess.Popen(['xdg-open', str(target)])
                self._json(200, {'ok': True})
            elif self.path == '/api/shutdown':
                if JOB.active:
                    JOB.cancel.set()
                    raise FriendlyError('Please let the current job stop first.')
                self._json(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json(404, {'error': 'Unknown action.'})
        except (FriendlyError, ValueError, TypeError, json.JSONDecodeError) as e:
            self._json(400, {'error': str(e)})
        except (OSError, RuntimeError) as e:
            self._json(500, {'error': f'Could not complete that action: {e}'})


def serve():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), WebHandler)
    server.daemon_threads = True
    server.secret = secrets.token_urlsafe(32)
    port = server.server_address[1]
    path = STATE_DIR / 'server.json'
    path.write_text(json.dumps({'port': port, 'key': server.secret, 'pid': os.getpid()}), encoding='utf-8')
    if os.name != 'nt':
        path.chmod(0o600)
    print(f'Mochi ready on loopback port {port}', flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        try:
            if json.loads(path.read_text()).get('key') == server.secret:
                path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == '__main__':
    serve()
