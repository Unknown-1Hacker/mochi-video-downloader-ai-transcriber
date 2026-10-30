"""Paths are stable before and after first-run installation."""
from pathlib import Path


def root_dir(source=__file__):
    app = Path(source).resolve().parent
    if app.parent.name == '.mochi':
        return app.parent.parent
    return app.parent


def app_dir(root):
    root = Path(root)
    hidden = root / '.mochi' / 'app'
    return hidden if hidden.is_dir() else root / 'app'


def output_dir(root):
    root = Path(root)
    # Existing users' downloads remain visible and in place, never moved/deleted.
    old = root / 'My Downloads'
    if (root / '.mochi' / 'app').is_dir():
        return root / '.mochi' / 'Downloads'
    return old if old.is_dir() else root / '.mochi' / 'Downloads'
