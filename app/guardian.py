"""Private, crash-safe job checkpoint and safe diagnostic text for Mochi.

An interrupted job is offered for manual retry, never run without permission.
No diagnostic is sent over the network.
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from core import FriendlyError, check_url

JOB_FILE = "pending-job.json"
MODES = {"video", "audio", "subtitles", "transcript"}


def _path(root):
    return Path(root) / ".mochi" / JOB_FILE


def save_pending(root, url, options):
    """Atomic private checkpoint. Failure must not prevent a download."""
    if not isinstance(url, str) or not isinstance(options, dict):
        return
    if options.get("mode", "video") not in MODES:
        return
    target = _path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Only retain known UI settings; never arbitrary request or browser data.
    fields = ("mode", "height", "audio_format", "speech_quality", "language")
    clean = {k: options[k] for k in fields if k in options and isinstance(options[k], (str, int))}
    payload = json.dumps({"url": url, "options": clean}, ensure_ascii=False).encode("utf-8")
    if len(payload) > 4096:
        return
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".pending-", delete=False) as file:
            name = file.name
            os.chmod(name, 0o600)
            file.write(payload)
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_pending(root):
    """Accept only a small, valid local checkpoint; never follow a symlink."""
    target = _path(root)
    try:
        if target.is_symlink() or target.stat().st_size > 4096:
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("options"), dict):
            return None
        check_url(data.get("url"))
        if data["options"].get("mode", "video") not in MODES:
            return None
        return {"url": data["url"], "options": data["options"]}
    except (OSError, ValueError, TypeError, KeyError, FriendlyError):
        return None


def clear_pending(root):
    """Delete only Mochi's known checkpoint, never user downloads."""
    try:
        _path(root).unlink(missing_ok=True)
    except OSError:
        pass


def redact(message):
    """Remove personal links, tokens and paths from user-facing errors."""
    s = str(message)
    s = re.sub(r"https?://[^\s<>'\"\\]+", "[link]", s, flags=re.I)
    s = re.sub(r"(?i)(?:/home/|/Users/)[^/\s]+", "[home]", s)
    s = re.sub(r"(?i)[a-z]:\\Users\\[^\\\s]+", "[home]", s)
    s = re.sub(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "[email]", s)
    s = re.sub(r"(?i)\b(key|token|secret|password)=([^\s&]+)", r"\1=[hidden]", s)
    return s
