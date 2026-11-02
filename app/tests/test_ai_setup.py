"""Offline checks of private, on-demand speech software setup."""
import os
import threading

import pytest

import ai_setup
from core import FriendlyError, UserCancelled


def test_ready_never_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_setup, '_ready', lambda: True)
    monkeypatch.setattr(ai_setup.subprocess, 'Popen', lambda *a, **k: pytest.fail('Unexpected install'))
    ai_setup.ensure_ai(tmp_path, lambda *a: None, threading.Event())


def test_cancel_before_setup_does_not_install(tmp_path, monkeypatch):
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(ai_setup.subprocess, 'Popen', lambda *a, **k: pytest.fail('Unexpected install'))
    with pytest.raises(UserCancelled):
        ai_setup.ensure_ai(tmp_path, lambda *a: None, cancel)


def test_refuses_global_python(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_setup, '_ready', lambda: False)
    with pytest.raises(FriendlyError, match='private setup'):
        ai_setup.ensure_ai(tmp_path, lambda *a: None, threading.Event())


def test_first_real_ai_request_installs_to_private_environment(tmp_path, monkeypatch):
    ready = iter([False, True])
    monkeypatch.setattr(ai_setup, '_ready', lambda: next(ready))
    private = tmp_path / '.mochi' / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    private.parent.mkdir(parents=True)
    private.write_bytes(b'python')
    monkeypatch.setattr(ai_setup.sys, 'executable', str(private))
    app = tmp_path / '.mochi' / 'app'
    app.mkdir(parents=True)
    (app / 'requirements-ai.txt').write_text('faster-whisper>=1.1,<1.3\n', encoding='utf-8')
    tool = tmp_path / '.mochi' / 'tools' / ('uv.exe' if os.name == 'nt' else 'uv')
    tool.parent.mkdir()
    tool.write_bytes(b'uv')
    calls = []
    class Done:
        returncode = 0
        def poll(self): return 0
    def fake_popen(args, **kw):
        calls.append((args, kw))
        return Done()
    monkeypatch.setattr(ai_setup.subprocess, 'Popen', fake_popen)
    ai_setup.ensure_ai(tmp_path, lambda *a: None, threading.Event())
    assert len(calls) == 1
    args, kw = calls[0]
    assert args[0] == str(tool)
    assert args[1:3] == ['pip', 'install']
    assert args[-1] == str(app / 'requirements-ai.txt')
    assert kw['env']['UV_NO_CACHE'] == '1'
