"""Storage promises: no eager AI, safe cache cleanup, recoverable fallback."""
import os
import sys
import threading
import types
from pathlib import Path

import pytest

import core
import doctor
import install_layout


def test_initial_requirements_do_not_force_ai_download():
    app = Path(core.__file__).parent
    base = (app / "requirements.txt").read_text(encoding="utf-8")
    ai = (app / "requirements-ai.txt").read_text(encoding="utf-8")
    assert "yt-dlp" in base
    assert "faster-whisper" not in base
    assert "ctranslate2" not in base
    assert "faster-whisper>=1.1,<1.3" in ai
    assert "av>=16,<19" in ai


def test_either_platform_shortcut_does_not_force_ai_setup():
    src = Path(install_layout.__file__).read_text(encoding="utf-8")
    assert 'u.find_spec("yt_dlp")' in src
    assert 'u.find_spec("faster_whisper")' not in src


def test_cache_cleanup_never_touches_saved_media_or_models(tmp_path):
    state = tmp_path / ".mochi"
    cache = state / "cache" / "archive"
    cache.mkdir(parents=True)
    (cache / "packages.tmp").write_bytes(b"temporary")
    downloaded = state / "Downloads" / "my-video.mp4"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"MY VIDEO")
    model = state / "models" / "keep-model.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"MY MODEL")
    assert doctor.trim_setup_cache(tmp_path) is True
    assert not (state / "cache").exists()
    assert downloaded.read_bytes() == b"MY VIDEO"
    assert model.read_bytes() == b"MY MODEL"


@pytest.mark.skipif(os.name == "nt", reason="Symbolic links vary by Windows developer-mode permissions")
def test_cleanup_does_not_follow_symlinks(tmp_path):
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()
    (elsewhere / "important.txt").write_text("KEEP", encoding="utf-8")
    state = tmp_path / ".mochi"
    state.mkdir()
    (state / "cache").symlink_to(elsewhere, target_is_directory=True)
    assert doctor.trim_setup_cache(tmp_path) is False
    assert (elsewhere / "important.txt").read_text(encoding="utf-8") == "KEEP"


def test_ai_is_not_installed_when_already_present(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
    monkeypatch.setitem(sys.modules, "ctranslate2", types.ModuleType("ctranslate2"))
    monkeypatch.setattr(doctor, "_uv", lambda *a: pytest.fail("Must not invoke installer"))
    assert doctor.ensure_speech_tools(tmp_path, lambda *a: None) is False


def test_missing_ai_installs_only_known_package_list(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    app = tmp_path / ".mochi" / "app"
    app.mkdir(parents=True)
    requirements = app / "requirements-ai.lock"
    requirements.write_text("faster-whisper==1.2.1\n", encoding="utf-8")
    cache = tmp_path / ".mochi" / "cache"
    cache.mkdir()
    (cache / "download.part").write_bytes(b"temp")
    monkeypatch.setattr(doctor, "_uv", lambda root: "uv")
    commands = []
    def run(cmd, **kwargs):
        commands.append((cmd, kwargs))
        assert str(requirements) == cmd[-1]
        assert cmd[:3] == ["uv", "pip", "install"]
        assert kwargs["env"]["UV_CACHE_DIR"] == str(cache)
        assert kwargs["timeout"] == 900
        monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
        monkeypatch.setitem(sys.modules, "ctranslate2", types.ModuleType("ctranslate2"))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(doctor.subprocess, "run", run)
    changes = []
    assert doctor.ensure_speech_tools(tmp_path, lambda message, pct: changes.append(pct))
    assert len(commands) == 1
    assert changes == [67, 68]
    assert not cache.exists()
    log = tmp_path / ".mochi" / "ai-setup.log"
    assert log.is_file()
    if os.name != "nt":
        assert log.stat().st_mode & 0o077 == 0


def test_ai_install_failure_keeps_downloads_and_explains_it(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    app = tmp_path / "app"
    app.mkdir()
    (app / "requirements-ai.txt").write_text("faster-whisper<1.3\n", encoding="utf-8")
    saved = tmp_path / ".mochi" / "Downloads" / "saved.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"NEVER DELETE")
    monkeypatch.setattr(doctor, "_uv", lambda root: "uv")
    monkeypatch.setattr(doctor.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1))
    with pytest.raises(doctor.RepairError, match="internet and free disk space"):
        doctor.ensure_speech_tools(tmp_path, lambda *a: None)
    assert saved.read_bytes() == b"NEVER DELETE"


def test_cancelled_ai_install_does_not_run_uv(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    monkeypatch.setattr(doctor, "_uv", lambda root: pytest.fail("Cancelled before install"))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(doctor.RepairError, match="Cancelled"):
        doctor.ensure_speech_tools(tmp_path, lambda *a: None, cancel)


def test_readme_explains_what_can_be_removed():
    text = (Path(core.__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    for item in (".mochi", "cache/", "models/", "Downloads/", "venv/", "AI"):
        assert item in text
