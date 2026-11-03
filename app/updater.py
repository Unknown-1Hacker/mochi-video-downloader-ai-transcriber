"""Conservative, user-approved updates from Mochi's official GitHub release.

The running server only downloads/verifies/stages. A detached stdlib-only worker
performs the app swap AFTER the server exits, preserving user data and rollback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from mochi_paths import app_dir
from version import APP_VERSION

API = "https://api.github.com/repos/Unknown-1Hacker/mochi-video-downloader-ai-transcriber/releases/latest"
REPO = "Unknown-1Hacker/mochi-video-downloader-ai-transcriber"
VERSION_RE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
HASH_RE = re.compile(r"sha256:([0-9a-f]{64})\Z")
MAX_ZIP = 64 * 1024 * 1024
MAX_UNPACKED = 160 * 1024 * 1024
MAX_ENTRIES = 500
REQUIRED = {
    "studio.py", "launcher.py", "version.py", "install_layout.py",
    "update_worker.py", "updater.py", "assets/index.html",
    "assets/app.js", "assets/style.css", "assets/hero-bunny.png",
}


class UpdateError(Exception):
    """One actionable update failure, not a reason to harm existing files."""


def version_tuple(value: str):
    match = VERSION_RE.fullmatch("v" + str(value).removeprefix("v"))
    return tuple(map(int, match.groups())) if match else None


class GitHubOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Never follow releases through unexpected domains or plaintext HTTP."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        host = (u.hostname or "").lower()
        if (u.scheme != "https" or u.username or u.password
                or not (host == "github.com" or host.endswith(".githubusercontent.com"))):
            raise UpdateError("GitHub redirected the download unexpectedly. Update cancelled.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _release_request(url: str):
    return urllib.request.Request(url, headers={
        "User-Agent": "Mochi-updater",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })


def fetch_latest():
    try:
        with urllib.request.urlopen(_release_request(API), timeout=8) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise UpdateError("GitHub sent an unexpectedly large release response.")
        release = json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise UpdateError("Could not check GitHub. Check your connection and retry.") from exc
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        raise UpdateError("No stable Mochi release was found.")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or version_tuple(tag) is None:
        raise UpdateError("The latest release has an unrecognized version.")
    assets = [a for a in release.get("assets", []) if isinstance(a, dict) and a.get("name") == "Mochi.zip"]
    if len(assets) != 1:
        raise UpdateError("This release has no single official Mochi.zip file.")
    asset = assets[0]
    url = asset.get("browser_download_url")
    digest = asset.get("digest")
    size = asset.get("size")
    expected_url = f"https://github.com/{REPO}/releases/download/{tag}/Mochi.zip"
    if (url != expected_url or not isinstance(digest, str) or not HASH_RE.fullmatch(digest)
            or not isinstance(size, int) or not 0 < size <= MAX_ZIP):
        raise UpdateError("This release cannot be verified safely. Download manually from GitHub.")
    return {"version": tag, "download": url, "digest": digest[7:], "size": size,
            "release_url": f"https://github.com/{REPO}/releases/tag/{tag}"}


def newer(remote, current=APP_VERSION):
    lhs, rhs = version_tuple(remote), version_tuple(current)
    return lhs is not None and rhs is not None and lhs > rhs


def _safe_stage(archive: Path, target: Path, expected_version: str, current_app: Path):
    """Only app files; no path traversal, links, decompression bombs or user files."""
    if target.exists():
        # Only our own known temporary staging path may be reused.
        if target.is_symlink() or not target.name == "app.next":
            raise UpdateError("Update staging is not safe; reinstall Mochi manually.")
        shutil.rmtree(target)
    target.mkdir(parents=True)
    seen, total = set(), 0
    try:
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if not members or len(members) > MAX_ENTRIES:
                raise UpdateError("The update ZIP is incomplete or unusually large.")
            for member in members:
                name = member.filename
                if name.endswith("/"):
                    continue
                if not name.startswith("Mochi/app/") or "\\" in name:
                    # Root installers are intentionally ignored, all other contents rejected.
                    if name in ("Mochi/Install-Mochi-Windows.cmd", "Mochi/Install-Mochi-Mac.command",
                                "Mochi/Install-Mochi-Linux.sh", "Mochi/📖 READ ME.txt"):
                        continue
                    raise UpdateError("The downloaded ZIP contains unexpected files.")
                parts = Path(name.removeprefix("Mochi/app/")).parts
                if (not parts or any(p in ("", ".", "..") or ":" in p for p in parts)
                        or any(p.endswith((" ", ".")) for p in parts)
                        or name.casefold() in seen):
                    raise UpdateError("The downloaded ZIP has unsafe or repeated paths.")
                seen.add(name.casefold())
                if (stat.S_IFMT(member.external_attr >> 16) == stat.S_IFLNK
                        or member.flag_bits & 1):
                    raise UpdateError("The downloaded ZIP has an unsupported file type.")
                total += member.file_size
                if member.file_size > MAX_ZIP or total > MAX_UNPACKED:
                    raise UpdateError("The downloaded ZIP expands beyond safe limits.")
                destination = target.joinpath(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.resolve().is_relative_to(target.resolve()):
                    raise UpdateError("Update ZIP contains an unsafe path.")
                with z.open(member) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 128 * 1024)
        if not all((target / p).is_file() for p in REQUIRED):
            raise UpdateError("Update is missing essential Mochi files.")
        version_file = (target / "version.py").read_text(encoding="utf-8")
        expected = re.search(r'^APP_VERSION\s*=\s*["\']([0-9.]+)["\']', version_file, re.M)
        if not expected or "v" + expected.group(1) != expected_version:
            raise UpdateError("Update version does not match its release.")
        # Unknown dependency changes must use the normal manual installer, not an unsafe partial update.
        for requirement in ("requirements.txt", "requirements-ai.txt"):
            previous = current_app / requirement
            incoming = target / requirement
            if previous.exists() != incoming.exists() or (
                previous.exists() and previous.read_bytes() != incoming.read_bytes()
            ):
                raise UpdateError("This version changes its tools. Use the official installer to update safely.")
    except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
        raise UpdateError("The update could not be unpacked safely. Please retry.") from exc


def _download(release, file_path: Path, progress):
    url = release["download"]
    digest = hashlib.sha256()
    received = 0
    opener = urllib.request.build_opener(GitHubOnlyRedirects)
    try:
        with opener.open(_release_request(url), timeout=18) as resp, file_path.open("xb") as output:
            while True:
                chunk = resp.read(128 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_ZIP or received > release["size"]:
                    raise UpdateError("The update download was larger than expected.")
                output.write(chunk)
                digest.update(chunk)
                progress(min(90, int(received / release["size"] * 90)))
        if received != release["size"] or digest.hexdigest() != release["digest"]:
            raise UpdateError("Update verification failed. Nothing was installed.")
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError("Download interrupted. Your current Mochi is unchanged.") from exc


class UpdateManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = {"phase": "idle", "message": "", "percent": 0}
        self.cached = None
        self.checked_at = 0

    def read(self, root=None):
        with self.lock:
            current = dict(self.state)
        if current["phase"] != "idle" or root is None:
            return current
        # The detached worker can report an interrupted/rolled-back result
        # after a server restart without relying on stale in-memory state.
        file = Path(root) / ".mochi" / "updates" / "status.json"
        try:
            if file.is_symlink() or file.stat().st_size > 4096:
                return current
            saved = json.loads(file.read_text(encoding="utf-8"))
            if (saved.get("phase") in ("updated", "rolled-back", "failed")
                    and time.time() - float(saved.get("time", 0)) < 3600):
                return {"phase": saved["phase"], "message": str(saved.get("message", ""))[:240],
                        "percent": 100 if saved["phase"] == "updated" else 0}
        except (OSError, ValueError, TypeError):
            pass
        return current

    def _set(self, phase, message, percent=None):
        with self.lock:
            self.state.update(phase=phase, message=message)
            if percent is not None:
                self.state["percent"] = percent

    def check(self, force=False):
        with self.lock:
            if self.state["phase"] in ("downloading", "staging", "restarting"):
                return self.read()
            cached = self.cached if (not force and time.monotonic() - self.checked_at < 600) else None
        try:
            latest = cached or fetch_latest()
            with self.lock:
                self.cached = latest
                self.checked_at = time.monotonic()
                available = newer(latest["version"])
                self.state = {"phase": "available" if available else "current",
                              "message": "A new Mochi version is ready!" if available else "Mochi is up to date.",
                              "current": "v" + APP_VERSION, "latest": latest["version"],
                              "release_url": latest["release_url"], "percent": 0}
            return self.read()
        except UpdateError as exc:
            self._set("offline", str(exc), 0)
            return self.read()

    def start(self, root: Path, job, server):
        with job.lock:
            if job.active or job.updating:
                raise UpdateError("Finish or cancel your current task before updating.")
            with self.lock:
                if self.state["phase"] != "available" or not self.cached or not newer(self.cached["version"]):
                    raise UpdateError("Check for a newer release first.")
                release = dict(self.cached)
                self.state = {"phase": "downloading", "message": "Downloading the verified update…", "percent": 0}
                job.updating = True
        threading.Thread(target=self._work, args=(Path(root), release, job, server), daemon=True).start()

    def _work(self, root: Path, release: dict, job, server):
        state_dir = root / ".mochi"
        updates = state_dir / "updates"
        archive = updates / "Mochi.zip.part"
        target = updates / "app.next"
        try:
            updates.mkdir(parents=True, exist_ok=True)
            if updates.is_symlink() or archive.is_symlink() or target.is_symlink():
                raise UpdateError("Update folder is unsafe. Please reinstall manually.")
            if archive.exists():
                archive.unlink()
            _download(release, archive, lambda value: self._set("downloading", "Downloading…", value))
            self._set("staging", "Checking the new Mochi files…", 92)
            _safe_stage(archive, target, release["version"], app_dir(root))
            archive.unlink(missing_ok=True)
            # The running server must exit before the worker can swap app files.
            worker = updates / "update_worker.py"
            shutil.copy2(app_dir(root) / "update_worker.py", worker)
            self._set("restarting", "Restarting Mochi safely…", 98)
            log = updates / "update.log"
            with log.open("a", encoding="utf-8") as f:
                opts = {"stdin": subprocess.DEVNULL, "stdout": f, "stderr": f, "cwd": str(root)}
                if os.name == "nt":
                    opts["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                else:
                    opts["start_new_session"] = True
                subprocess.Popen([sys.executable, str(worker), str(root), release["version"]], **opts)
            # Give this HTTP request time to answer, then stop serving old code.
            def stop():
                time.sleep(1)
                server.shutdown()
            threading.Thread(target=stop, daemon=True).start()
        except (UpdateError, OSError, ValueError, shutil.Error, subprocess.SubprocessError) as exc:
            with job.lock:
                job.updating = False
            self._set("error", str(exc) if isinstance(exc, UpdateError)
                      else "Could not finish the update. Your original Mochi is unchanged.", 0)
            try:
                archive.unlink(missing_ok=True)
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
            except OSError:
                pass
