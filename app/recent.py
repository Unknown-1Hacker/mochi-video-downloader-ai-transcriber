"""Small, private pointer to last finished transcript; never store its text."""
import json
import os
from pathlib import Path


def restore(root, output):
    file = Path(root) / '.mochi' / 'last-transcript.json'
    try:
        if file.is_symlink() or file.stat().st_size > 4096:
            return None
        saved = json.loads(file.read_text(encoding='utf-8'))
        name = saved['folder']
        if not isinstance(name, str) or not name or name in ('.', '..') or len(name) > 230:
            return None
        if Path(name).name != name or '/' in name or '\\' in name:
            return None
        folder = (Path(output) / name).resolve(strict=True)
        txt = folder / 'Transcript.txt'
        if not folder.is_relative_to(Path(output).resolve()) or not txt.is_file() or txt.is_symlink():
            return None
        return {'state': 'done', 'message': 'Your saved transcript is ready 💜',
                'percent': 100, 'folder': str(folder), 'files': ['Transcript.txt']}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remember(root, output, files):
    try:
        if len(files) != 1 or files[0].name != 'Transcript.txt' or files[0].is_symlink():
            return
        saved = files[0].resolve(strict=True)
        base = Path(output).resolve()
        if not saved.is_file() or not saved.is_relative_to(base):
            return
        relative = saved.parent.relative_to(base)
        if len(relative.parts) != 1:
            return
        file = Path(root) / '.mochi' / 'last-transcript.json'
        file.parent.mkdir(parents=True, exist_ok=True)
        if file.is_symlink():
            return
        tmp = file.with_suffix('.tmp')
        tmp.write_text(json.dumps({'folder': relative.name}), encoding='utf-8')
        os.replace(tmp, file)
        if os.name != 'nt':
            file.chmod(0o600)
    except (OSError, ValueError):
        pass
