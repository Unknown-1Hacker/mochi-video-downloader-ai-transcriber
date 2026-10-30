"""Conservative, local-only checks and bounded tool repair for Mochi.

Repairs only dependencies already listed in our local requirements; never downloads
or executes an arbitrary script on an error or overwrites the application itself.
"""
from __future__ import annotations
import importlib.metadata
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from mochi_paths import app_dir


class RepairError(Exception):
    pass


def _version(package):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _major(version):
    try:
        return int(version.split('.')[0])
    except (ValueError, TypeError, AttributeError):
        return None


def inspect(root: Path) -> dict:
    """Quick health report without downloading models or hitting the network."""
    state = Path(root) / '.mochi'
    exe = '.exe' if os.name == 'nt' else ''
    versions = {name: _version(name) for name in ('yt-dlp', 'faster-whisper', 'av', 'ctranslate2')}
    paired = versions['faster-whisper']
    incompatible = bool(paired and _major(versions['av']) and _major(versions['av']) >= 19
                        and paired.startswith(('1.1.', '1.2.')))
    bin_dir = state / 'ffmpeg'
    binaries = {name: (bin_dir / (name + exe)).exists() for name in ('ffmpeg','ffprobe')}
    return {'versions': versions, 'incompatible_audio_decoder': incompatible,
            'ffmpeg': binaries, 'known_issues': (['PyAV / faster-whisper decoding mismatch'] if incompatible else [])}


def _uv(root: Path) -> str:
    local = Path(root) / '.mochi' / 'tools' / ('uv.exe' if os.name == 'nt' else 'uv')
    if local.is_file():
        return str(local)
    system = shutil.which('uv')
    if system:
        return system
    raise RepairError('Installer helper is missing. Run Mochi Now again.')


def is_extractor_problem(error: BaseException) -> bool:
    """Only retry errors plausibly repaired by a newer yt-dlp extractor."""
    msg = str(error).lower()
    return any(x in msg for x in ('nsig extraction failed', 'signature extraction failed',
                                 'unable to extract', 'signature solving failed',
                                 'javascript runtime was not found'))


def repair(root: Path, update, *, only_downloader: bool = False, cancelled=None) -> dict:
    """At most one upgrade pass. Never auto-installs a new unreviewed app version.

    Called by one-click repair or a single specific extractor-failure retry.
    """
    root = Path(root)
    uv = _uv(root)
    if cancelled is not None and cancelled.is_set():
        raise RepairError('Repair cancelled.')
    update('Checking local tools…', 7)
    report_before = inspect(root)
    log = root / '.mochi' / 'repair.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [uv, 'pip', 'install', '--python', sys.executable,
               '--upgrade-package', 'yt-dlp', '-r', str(app_dir(root) / 'requirements.txt')]
    if only_downloader:
        command = [uv, 'pip', 'install', '--python', sys.executable, '--upgrade', 'yt-dlp[default]']
    update('Repairing known dependencies safely…', 35)
    start = time.monotonic()
    try:
        with log.open('a', encoding='utf-8') as handle:
            handle.write('\n--- Tool check ---\n')
            handle.flush()
            completed = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, check=False, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RepairError(f'Repair could not finish: {type(exc).__name__}. Check your internet connection.') from exc
    if completed.returncode != 0:
        raise RepairError('Tool repair was unsuccessful. Check internet, then double-click Run Mochi Now again. Details: .mochi/repair.log')
    if cancelled is not None and cancelled.is_set():
        raise RepairError('Repair cancelled after installing tools.')
    if not only_downloader:
        update('Checking audio and media tools…', 80)
        from core import ensure_ffmpeg
        ensure_ffmpeg(root)
    report_after = inspect(root)
    update('Tool check complete ✓', 100)
    return {'before': report_before, 'after': report_after, 'elapsed_seconds': round(time.monotonic() - start, 1)}


def remember_fix(root: Path, kind: str, method: str, successful: bool) -> None:
    """Keep small, private reliability history; no links, transcripts or user paths."""
    import json
    kinds = {'extractor', 'audio_decoder', 'tools'}
    methods = {'update_downloader', 'ffmpeg_fallback', 'repair_dependencies'}
    if kind not in kinds or method not in methods:
        return
    path = Path(root) / '.mochi' / 'fix-history.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            rows = []
    except (ValueError, OSError):
        rows = []
    rows.append({'kind': kind, 'method': method, 'success': bool(successful),
                 'time': int(time.time())})
    temp = path.with_suffix('.tmp')
    try:
        import json
        temp.write_text(json.dumps(rows[-64:], separators=(',', ':')), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass  # A history write must never break the user's current download.


def recently_failed(root: Path, kind: str, method: str, within_seconds: int = 3600) -> bool:
    """Avoid repeating the same failed background fix in a loop."""
    import json
    try:
        rows = json.loads((Path(root) / '.mochi' / 'fix-history.json').read_text(encoding='utf-8'))
        matching = [r for r in rows if isinstance(r, dict) and r.get('kind') == kind and r.get('method') == method]
        if not matching:
            return False
        last = matching[-1]
        return bool(last.get('success') is False and 0 <= time.time() - float(last.get('time', 0)) <= within_seconds)
    except (OSError, ValueError, TypeError):
        return False
