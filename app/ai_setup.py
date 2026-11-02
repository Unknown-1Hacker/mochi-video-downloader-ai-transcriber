"""Prepare local speech recognition only after captions are unavailable."""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import subprocess
import sys
import time
from pathlib import Path

from core import FriendlyError, UserCancelled


def _ready() -> bool:
    """Check compatible installed versions without loading the AI engine."""
    try:
        whisper = importlib.metadata.version('faster-whisper').split('.')
        av = importlib.metadata.version('av').split('.')
        importlib.metadata.version('ctranslate2')
        return (1, 1) <= (int(whisper[0]), int(whisper[1])) < (1, 3) and 16 <= int(av[0]) < 19
    except (importlib.metadata.PackageNotFoundError, ValueError, IndexError, TypeError):
        return False


def ensure_ai(root: Path, update, cancel) -> None:
    if cancel.is_set():
        raise UserCancelled('Cancelled.')
    if _ready():
        return

    # Never install packages in a system-wide Python interpreter.
    root = Path(root)
    private_python = root / '.mochi' / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not private_python.is_file() or Path(sys.executable).resolve() != private_python.resolve():
        raise FriendlyError("Local AI needs Mochi's private setup. Reopen with Run Mochi Now.")

    from doctor import RepairError, _uv
    try:
        uv = _uv(root)
    except RepairError as exc:
        raise FriendlyError('Local AI needs the setup helper. Reopen Mochi with its installer.') from exc

    req = root / '.mochi' / 'app' / 'requirements-ai.lock'
    if not req.is_file():
        req = root / '.mochi' / 'app' / 'requirements-ai.txt'
    if not req.is_file():
        raise FriendlyError('AI setup files are missing. Reinstall Mochi without deleting the .mochi folder.')

    log = root / '.mochi' / 'ai-setup.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['UV_NO_CACHE'] = '1'
    env['UV_CACHE_DIR'] = str(root / '.mochi' / 'cache')
    update('Preparing local AI for the first time…', 66)
    with log.open('a', encoding='utf-8') as output:
        output.write('\n--- Local AI setup ---\n')
        output.flush()
        try:
            proc = subprocess.Popen(
                [uv, 'pip', 'install', '--python', sys.executable, '-r', str(req)],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, env=env,
            )
        except OSError as exc:
            raise FriendlyError('Could not start local AI setup. Check internet and retry.') from exc
        deadline = time.monotonic() + 1800
        try:
            while proc.poll() is None:
                if cancel.is_set():
                    raise UserCancelled('Cancelled.')
                if time.monotonic() > deadline:
                    raise FriendlyError('AI setup took too long. Check internet and retry.')
                time.sleep(0.2)
            if cancel.is_set():
                raise UserCancelled('Cancelled.')
            if proc.returncode != 0:
                raise FriendlyError('AI setup failed. Check internet and free space, then try again.')
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    importlib.invalidate_caches()
    if not _ready():
        raise FriendlyError('Local AI setup is incomplete. Check free space and try again.')
    update('Local AI is ready. Listening to the audio…', 67)
