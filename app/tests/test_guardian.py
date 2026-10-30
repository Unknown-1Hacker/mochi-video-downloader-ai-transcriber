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
