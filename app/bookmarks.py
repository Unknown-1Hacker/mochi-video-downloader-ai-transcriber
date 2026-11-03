"""Stable, private loopback address for bookmarks across local studio restarts."""
import hashlib
import os
import secrets
from pathlib import Path


def preferred_port(root):
    digest = hashlib.sha256(os.fsencode(str(Path(root).resolve()))).digest()
    return 39000 + int.from_bytes(digest[:2], "big") % 20000


def private_key(root):
    state = Path(root) / '.mochi'
    state.mkdir(parents=True, exist_ok=True)
    file = state / 'browser-key'
    if file.is_symlink():
        raise RuntimeError('Unsafe browser credential file.')
    if file.exists():
        if not file.is_file():
            raise RuntimeError('Unsafe browser credential file.')
        value = file.read_text(encoding='ascii').strip()
        if len(value) >= 40 and all(ch.isalnum() or ch in '-_' for ch in value):
            return value
        raise RuntimeError('Invalid private browser credential. Open Run Mochi Now for help.')
    value = secrets.token_urlsafe(32)
    try:
        fd = os.open(str(file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return private_key(root)
    with os.fdopen(fd, 'w', encoding='ascii') as handle:
        handle.write(value)
    if os.name != 'nt':
        file.chmod(0o600)
    return value
