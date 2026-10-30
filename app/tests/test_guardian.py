"""Guardian regression tests: recovery, privacy and version consistency."""
import os
from pathlib import Path

import guardian
import launcher
import studio
import version


URL = "https://www.youtube.com/watch?v=5bKz"


def test_one_version_for_client_server_and_mac_bundle():
    assert studio.APP_VERSION == launcher.APP_VERSION == version.APP_VERSION
    assert version.APP_VERSION == "0.2.0"


def test_private_job_checkpoint_and_manual_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "ROOT", tmp_path)
    opts = {"mode": "subtitles", "language": "en", "speech_quality": "balanced"}
    guardian.save_pending(tmp_path, URL, opts)
    checkpoint = tmp_path / ".mochi" / "pending-job.json"
    assert checkpoint.exists()
    if os.name != "nt":
        assert checkpoint.stat().st_mode & 0o077 == 0
    assert guardian.load_pending(tmp_path)["options"] == opts
    state = studio.JobState().read()
    assert state["state"] == "interrupted"
    assert state["pending"]["url"] == URL
    guardian.clear_pending(tmp_path)
    assert guardian.load_pending(tmp_path) is None


def test_no_untrusted_or_large_checkpoint(tmp_path):
    guardian.save_pending(tmp_path, "https://not-youtube.example", {"mode": "video"})
    assert guardian.load_pending(tmp_path) is None
    guardian.clear_pending(tmp_path)
    guardian.save_pending(tmp_path, URL, {"mode": "unknown"})
    assert guardian.load_pending(tmp_path) is None
    p = tmp_path / ".mochi" / "pending-job.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text("x" * 5000)
    assert guardian.load_pending(tmp_path) is None


def test_error_redaction():
    msg = "oops https://youtu.be/SECRET?v=1 key=abc123 /home/alice/private /Users/bob/mail person@example.org"
    safe = guardian.redact(msg)
    assert "SECRET" not in safe and "abc123" not in safe
    assert "alice" not in safe and "bob" not in safe
    assert "person@example.org" not in safe
    assert "[link]" in safe and "[home]" in safe


def test_existing_downloads_never_touched(tmp_path):
    private = tmp_path / ".mochi" / "Downloads"
    private.mkdir(parents=True)
    original = private / "holiday.mp4"
    original.write_bytes(b"keep this forever")
    guardian.save_pending(tmp_path, URL, {"mode": "video"})
    guardian.clear_pending(tmp_path)
    assert original.read_bytes() == b"keep this forever"


def test_installer_prefers_release_lockfile():
    source = Path(studio.__file__).parent
    shell = (source / "bootstrap.sh").read_text()
    powershell = (source / "bootstrap.ps1").read_text()
    assert "requirements.lock" in shell and "requirements.lock" in powershell
    assert "requirements.txt" in shell and "requirements.txt" in powershell


def test_downloader_rollback_is_bounded(tmp_path, monkeypatch):
    import doctor
    import types
    calls = []
    monkeypatch.setattr(doctor, "_uv", lambda root: "uv")
    def fake_run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    assert doctor.restore_downloader(tmp_path, "2026.10.26")
    assert len(calls) == 1 and "--reinstall-package" in calls[0]
    assert "yt-dlp[default]==2026.10.26" in calls[0]
    assert not doctor.restore_downloader(tmp_path, "latest; do-something")
    assert len(calls) == 1


def test_manual_repair_prefers_release_lock(tmp_path, monkeypatch):
    import doctor
    import types
    app = tmp_path / "app"
    app.mkdir()
    (app / "requirements.txt").write_text("av<19\n")
    lock = app / "requirements.lock"
    lock.write_text("av==18.1.0\n")
    calls = []
    monkeypatch.setattr(doctor, "_uv", lambda root: "uv")
    monkeypatch.setattr(doctor.subprocess, "run", lambda args, **kwargs: (calls.append(args) or types.SimpleNamespace(returncode=0)))
    monkeypatch.setattr(doctor, "inspect", lambda root: {})
    import core
    monkeypatch.setattr(core, "ensure_ffmpeg", lambda root: str(root))
    doctor.repair(tmp_path, lambda *x: None)
    assert calls[0][-1] == str(lock)
