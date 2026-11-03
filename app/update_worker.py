#!/usr/bin/env python3
"""Detached, stdlib-only update installer; never swaps a running Mochi server.

This file runs from .mochi/updates, outside the application being replaced.
Its fallback can restore the original application if an update was interrupted.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

REQUIRED = ("studio.py", "launcher.py", "version.py", "assets/index.html", "assets/app.js")


def _paths(root):
    state = root / ".mochi"
    return state, state / "app", state / "app.previous", state / "updates" / "app.next"


def _write_state(root, phase, message):
    file = root / ".mochi" / "updates" / "status.json"
    payload = json.dumps({"phase": phase, "message": message, "time": time.time()}, ensure_ascii=False)
    temp = file.with_suffix(".tmp")
    temp.write_text(payload, encoding="utf-8")
    os.replace(temp, file)


def _server_alive(state):
    file = state / "server.json"
    if not file.is_file():
        return False
    try:
        saved = json.loads(file.read_text(encoding="utf-8"))
        port = int(saved["port"])
        if not 1024 <= port <= 65535:
            return False
        with socket.create_connection(("127.0.0.1", port), timeout=.3):
            return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def recover(root):
    """Manual launcher recovery if power loss left a previous-app backup.

    Never tamper while the freshly launched installer is still working.
    """
    state, live, backup, _ = _paths(root)
    status_file = state / "updates" / "status.json"
    if not backup.is_dir() or backup.is_symlink():
        return True
    try:
        status = json.loads(status_file.read_text(encoding="utf-8"))
        if status.get("phase") == "applying" and time.time() - float(status.get("time", 0)) < 120:
            return False
        if status.get("phase") == "updated" and live.is_dir() and not live.is_symlink():
            # Successful update with interrupted *cleanup*: keep the verified
            # new app, never incorrectly roll it back merely due to a backup.
            if all((live / name).is_file() for name in REQUIRED):
                try:
                    shutil.rmtree(backup)
                except OSError:
                    pass
                return True
    except (OSError, ValueError, TypeError):
        pass
    if _server_alive(state):
        return False
    if live.exists():
        if not live.is_dir() or live.is_symlink():
            return False
        shutil.rmtree(live)
    backup.rename(live)
    _write_state(root, "rolled-back", "Previous Mochi restored after an interrupted update.")
    return True


def _run_launcher(root, live):
    """Restart the local studio WITHOUT opening a duplicate browser window."""
    import re
    import urllib.request
    py = root / ".mochi" / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.is_file():
        raise RuntimeError("Private Python environment is missing.")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([0-9.]+)["\']',
                      (live / "version.py").read_text(encoding="utf-8"), re.M)
    if not match:
        raise RuntimeError("Application version is missing.")
    expected = match.group(1)
    options = {"cwd": str(root), "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    with (root / ".mochi" / "studio.log").open("a", encoding="utf-8") as log:
        proc = subprocess.Popen([str(py), str(live / "studio.py")],
                                stdout=log, stderr=log, **options)
    try:
        for _ in range(150):
            if proc.poll() is not None:
                raise RuntimeError("New Mochi stopped unexpectedly.")
            session = root / ".mochi" / "server.json"
            try:
                data = json.loads(session.read_text(encoding="utf-8"))
                port = int(data["port"])
                key = data["key"]
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health",
                                             headers={"X-Mochi-Key": key})
                with urllib.request.urlopen(req, timeout=.4) as response:
                    health = json.loads(response.read())
                if health.get("ok") is True and health.get("version") == expected:
                    return
            except (OSError, ValueError, KeyError, TypeError):
                pass
            time.sleep(.15)
        raise RuntimeError("Mochi did not pass its restart health check.")
    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        raise


def install(root, version):
    state, live, backup, staged = _paths(root)
    if not staged.is_dir() or staged.is_symlink():
        raise RuntimeError("Verified update staging is missing.")
    if backup.exists():
        raise RuntimeError("A previous app backup needs recovery; refusing to overwrite it.")
    if any(not (staged / item).is_file() for item in REQUIRED):
        raise RuntimeError("Update is missing important files.")
    for _ in range(200):
        if not _server_alive(state):
            break
        time.sleep(.1)
    else:
        raise RuntimeError("Mochi is still running. Current installation was not replaced.")
    _write_state(root, "applying", "Switching to the verified version…")
    moved = False
    try:
        if not live.is_dir() or live.is_symlink():
            raise RuntimeError("Current Mochi application is missing or unsafe.")
        live.rename(backup)
        moved = True
        staged.rename(live)
        _run_launcher(root, live)
        _write_state(root, "updated", "Updated successfully to " + version + ".")
        try:
            shutil.rmtree(backup)
        except OSError:
            # Cleanup never turns a healthy verified update into a failure.
            pass
    except Exception:
        if moved:
            # Try to stop an incorrectly started replacement before rollback.
            if _server_alive(state):
                # If a new server is running, do not delete code underneath it.
                _write_state(root, "failed", "New Mochi started but failed verification. Reopen Run Mochi Now.")
                raise
            if live.is_dir() and not live.is_symlink():
                shutil.rmtree(live)
            backup.rename(live)
            _write_state(root, "rolled-back", "Update failed; your previous Mochi was restored.")
            try:
                _run_launcher(root, live)
            except Exception:
                _write_state(root, "rolled-back", "Previous Mochi restored. Open Run Mochi Now.")
        raise


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit(2)
    root = Path(sys.argv[1]).resolve()
    if Path(__file__).resolve() != (root / ".mochi" / "updates" / "update_worker.py").resolve():
        raise SystemExit("Updater is not in its private Mochi folder.")
    state, _, _, _ = _paths(root)
    if not state.is_dir():
        raise SystemExit("Mochi installation not found.")
    if sys.argv[2] == "--recover":
        raise SystemExit(0 if recover(root) else 1)
    version = sys.argv[2]
    if not version.startswith("v") or len(version) > 25:
        raise SystemExit("Invalid requested version.")
    try:
        install(root, version)
    except Exception as exc:
        status = root / ".mochi" / "updates" / "status.json"
        try:
            previous = json.loads(status.read_text(encoding="utf-8"))
            restored = previous.get("phase") == "rolled-back"
        except (OSError, ValueError, TypeError):
            restored = False
        if not restored:
            _write_state(root, "failed", "Update could not finish. Use Run Mochi Now to recover.")
        print("Update failed:", type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
