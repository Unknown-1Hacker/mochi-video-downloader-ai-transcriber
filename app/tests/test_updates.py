"""Offline safety tests for GitHub updates, bookmarks and crash recovery."""
import hashlib
import io
import json
import os
import stat
import threading
import time
import zipfile
from pathlib import Path

import pytest

import updater
import update_worker


def _release(version="v0.3.6", payload=b"tiny-zip"):
    return {
        "tag_name": version,
        "draft": False,
        "prerelease": False,
        "assets": [{
            "name": "Mochi.zip",
            "browser_download_url": f"https://github.com/{updater.REPO}/releases/download/{version}/Mochi.zip",
            "digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }]
    }


def _mock_api(monkeypatch, value):
    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *exc): self.close()
    raw = json.dumps(value).encode()
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: Response(raw))


def test_versions_compare_numerically_and_ignore_unrecognized():
    assert updater.newer("v0.3.10", "0.3.9")
    assert not updater.newer("v0.3.5", "0.3.5")
    assert not updater.newer("v0.3.4", "0.3.5")
    for invalid in ("v0.3.6-rc1", "latest", "v0.3.6.1", "v2.0.0+abc", "../0.3.5"):
        assert not updater.newer(invalid, "0.3.5")
    assert updater.version_tuple("v" + updater.RELEASE_VERSION) is not None


def test_only_verified_stable_mochi_release_is_accepted(monkeypatch):
    _mock_api(monkeypatch, _release())
    result = updater.fetch_latest()
    assert result["version"] == "v0.3.6"
    assert result["digest"] == hashlib.sha256(b"tiny-zip").hexdigest()
    for change in (
        lambda d: d.update(prerelease=True),
        lambda d: d["assets"][0].update(digest=None),
        lambda d: d["assets"][0].update(browser_download_url="https://evil.example/Mochi.zip"),
        lambda d: d["assets"][0].update(size=updater.MAX_ZIP + 1),
        lambda d: d["assets"].append(dict(d["assets"][0])),
    ):
        item = _release()
        change(item)
        _mock_api(monkeypatch, item)
        with pytest.raises(updater.UpdateError):
            updater.fetch_latest()


def test_redirects_allow_only_github_https():
    handler = updater.GitHubOnlyRedirects()
    req = updater.urllib.request.Request("https://github.com/example")
    for url in ("http://github.com/test", "https://evil.example/test",
                "https://githubusercontent.com.evil.example/test",
                "https://me:pw@github.com/test"):
        with pytest.raises(updater.UpdateError):
            handler.redirect_request(req, None, 302, "", {}, url)


def _archive(path, version="v0.3.6", bad=None, extra=None):
    files = {p: b"fake-fixture" for p in updater.REQUIRED}
    files["version.py"] = f'APP_VERSION = "0.3.1"\nRELEASE_VERSION = "{version[1:]}"\n'.encode()
    files["requirements.txt"] = b"same-tools\n"
    files["requirements-ai.txt"] = b"same-ai\n"
    if bad:
        files[bad] = b"BAD"
    if extra:
        files.update(extra)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            key = name if name.startswith("Mochi/") else "Mochi/app/" + name
            z.writestr(key, data)


def _current_app(tmp_path):
    app = tmp_path / ".mochi" / "app"
    app.mkdir(parents=True)
    (app / "requirements.txt").write_bytes(b"same-tools\n")
    (app / "requirements-ai.txt").write_bytes(b"same-ai\n")
    (app / "sentinel.txt").write_text("DO NOT TOUCH")
    return app


def test_stage_github_zip_only_in_private_staging(tmp_path):
    current = _current_app(tmp_path)
    zipfile_path = tmp_path / "update.zip"
    _archive(zipfile_path)
    stage = tmp_path / ".mochi" / "updates" / "app.next"
    updater._safe_stage(zipfile_path, stage, "v0.3.6", current)
    assert (stage / "studio.py").is_file()
    assert (current / "sentinel.txt").read_text() == "DO NOT TOUCH"
    assert not (tmp_path / "app").exists()


@pytest.mark.parametrize("unsafe", [
    "Mochi/app/../../private.txt",
    "Mochi/app/../app/other.txt",
    "Mochi/app/\\evil.txt",
    "Mochi/something.txt",
])
def test_stage_rejects_bad_zip_paths(tmp_path, unsafe):
    current = _current_app(tmp_path)
    archive = tmp_path / "bad.zip"
    _archive(archive, extra={unsafe: b"UNSAFE"})
    with pytest.raises(updater.UpdateError):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next", "v0.3.6", current)
    assert (current / "sentinel.txt").read_text() == "DO NOT TOUCH"


def test_stage_rejects_version_and_dependency_mismatch(tmp_path):
    current = _current_app(tmp_path)
    archive = tmp_path / "bad.zip"
    _archive(archive, version="v0.3.6")
    with pytest.raises(updater.UpdateError, match="version"):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next", "v0.3.7", current)
    _archive(archive, extra={"requirements.txt": b"DIFFERENT"})
    with pytest.raises(updater.UpdateError, match="tools"):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next", "v0.3.6", current)


def test_stage_rejects_decompression_size_limit(tmp_path, monkeypatch):
    current = _current_app(tmp_path)
    archive = tmp_path / "large.zip"
    _archive(archive)
    monkeypatch.setattr(updater, "MAX_UNPACKED", 5)
    with pytest.raises(updater.UpdateError, match="limits"):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next", "v0.3.6", current)


def test_update_refuses_when_job_is_active(tmp_path):
    class Job:
        lock = threading.RLock()
        active = True
        updating = False
    manager = updater.UpdateManager()
    manager.check = lambda: None
    manager.cached = {"version": "v0.3.6"}
    manager.state["phase"] = "available"
    with pytest.raises(updater.UpdateError, match="Finish"):
        manager.start(tmp_path, Job(), None)
    assert manager.state["phase"] == "available"


def _worker_root(tmp_path):
    state = tmp_path / ".mochi"
    live = state / "app"
    backup = state / "app.previous"
    staged = state / "updates" / "app.next"
    live.mkdir(parents=True)
    staged.mkdir(parents=True)
    for path in update_worker.REQUIRED:
        item = staged / path
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"new")
    (live / "sentinel.txt").write_text("old")
    return live, backup, staged


def test_detached_worker_installs_only_after_server_exits(tmp_path, monkeypatch):
    live, backup, staged = _worker_root(tmp_path)
    monkeypatch.setattr(update_worker, "_server_alive", lambda state: False)
    monkeypatch.setattr(update_worker, "_run_launcher", lambda root, new: None)
    update_worker.install(tmp_path, "v0.3.6")
    assert (live / "studio.py").read_bytes() == b"new"
    assert not backup.exists() and not staged.exists()
    assert (tmp_path / ".mochi" / "updates" / "status.json").exists()


def test_detached_worker_rolls_back_on_launch_failure(tmp_path, monkeypatch):
    live, backup, staged = _worker_root(tmp_path)
    monkeypatch.setattr(update_worker, "_server_alive", lambda state: False)
    def fail(root, app):
        if app == live and (app / "studio.py").exists():
            raise RuntimeError("new app crashed")
    monkeypatch.setattr(update_worker, "_run_launcher", fail)
    with pytest.raises(RuntimeError, match="new app crashed"):
        update_worker.install(tmp_path, "v0.3.6")
    assert (live / "sentinel.txt").read_text() == "old"
    assert not backup.exists()


def test_recover_interrupted_app_rename_without_harming_downloads(tmp_path, monkeypatch):
    live, backup, staged = _worker_root(tmp_path)
    live.rename(backup)
    file = tmp_path / ".mochi" / "Downloads" / "keep.txt"
    file.parent.mkdir()
    file.write_text("USER DATA")
    monkeypatch.setattr(update_worker, "_server_alive", lambda state: False)
    assert update_worker.recover(tmp_path)
    assert (live / "sentinel.txt").read_text() == "old"
    assert file.read_text() == "USER DATA"


def test_worker_does_not_recover_during_active_update(tmp_path, monkeypatch):
    live, backup, staged = _worker_root(tmp_path)
    live.rename(backup)
    monkeypatch.setattr(update_worker, "_server_alive", lambda state: False)
    update_worker._write_state(tmp_path, "applying", "Update underway")
    assert update_worker.recover(tmp_path) is False
    assert backup.exists()


def test_verified_download_success_corruption_and_cancellation(tmp_path, monkeypatch):
    payload = b"one complete known archive" * 25
    item = _release(payload=payload)["assets"][0]
    release = {"download": item["browser_download_url"], "digest": item["digest"][7:],
               "size": item["size"]}
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(payload)
    monkeypatch.setattr(updater.urllib.request, "build_opener", lambda *args: Opener())
    valid = tmp_path / "verified.part"
    progressed = []
    updater._download(release, valid, progressed.append)
    assert valid.read_bytes() == payload and progressed[-1] == 90
    corrupt = tmp_path / "corrupt.part"
    with pytest.raises(updater.UpdateError, match="verification"):
        updater._download({**release, "digest": "a" * 64}, corrupt, lambda x: None)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(updater.UpdateError, match="cancelled"):
        updater._download(release, tmp_path / "cancelled.part", lambda x: None, cancelled)


def test_recover_does_not_downgrade_successful_update_with_leftover_backup(tmp_path, monkeypatch):
    live, backup, stage = _worker_root(tmp_path)
    backup.mkdir()
    (backup / "sentinel.txt").write_text("old")
    # A successful update already passed health-check but deletion of the backup
    # was interrupted. Keep new app, not the outdated backup.
    for name in update_worker.REQUIRED:
        file = live / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("new")
    update_worker._write_state(tmp_path, "updated", "Mochi updated.")
    monkeypatch.setattr(update_worker, "_server_alive", lambda state: False)
    assert update_worker.recover(tmp_path)
    assert (live / "studio.py").read_text() == "new"
    assert not backup.exists()


def test_updater_does_not_reuse_stale_previous_status_for_new_restart(tmp_path):
    manager = updater.UpdateManager()
    folder = tmp_path / ".mochi" / "updates"
    folder.mkdir(parents=True)
    (folder / "status.json").write_text(json.dumps({
        "phase": "updated", "message": "A previous version", "time": time.time() - 100,
    }))
    manager.started_at = time.time()
    manager.state = {"phase": "restarting", "message": "Updating the next version", "percent": 98}
    assert manager.read(tmp_path)["phase"] == "restarting"


def test_release_identity_distinct_from_internal_server_protocol():
    from version import APP_VERSION, RELEASE_VERSION
    assert APP_VERSION == "0.3.7"
    assert RELEASE_VERSION == "0.3.7"
    assert updater.version_tuple(RELEASE_VERSION) == (0, 3, 7)


def test_case_collision_and_extra_root_content_rejected(tmp_path):
    current = _current_app(tmp_path)
    archive = tmp_path / "collision.zip"
    _archive(archive, extra={"STUDIO.py": b"other"})
    with pytest.raises(updater.UpdateError):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next",
                            "v0.3.6", current)
    _archive(archive, extra={"Mochi/extra.exe": b"unsafe"})
    with pytest.raises(updater.UpdateError):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next",
                            "v0.3.6", current)


def test_signed_or_symlink_zip_members_not_allowed(tmp_path):
    current = _current_app(tmp_path)
    archive = tmp_path / "links.zip"
    _archive(archive)
    with zipfile.ZipFile(archive, "a") as z:
        member = zipfile.ZipInfo("Mochi/app/linked.py")
        member.create_system = 3
        member.external_attr = (0o120777 << 16)
        z.writestr(member, b"../../secret")
    with pytest.raises(updater.UpdateError):
        updater._safe_stage(archive, tmp_path / ".mochi" / "updates" / "app.next",
                            "v0.3.6", current)


def test_update_source_does_not_contain_external_transcript_sites():
    path = Path(updater.__file__)
    source = path.read_text(encoding="utf-8")
    assert "upload" not in source.lower()
    assert "https://api.github.com/repos/" in source
