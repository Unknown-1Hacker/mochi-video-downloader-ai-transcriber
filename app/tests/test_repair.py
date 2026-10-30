"""Regression tests for Oct-2026 PyAV incompatibility and bounded self-repair."""
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest
import core
import doctor


def sample_audio(tmp_path):
    binpath = Path(core.ensure_ffmpeg(tmp_path)) / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    filename = tmp_path / 'input.wav'
    subprocess.run([str(binpath), '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=2', '-ar', '16000', str(filename)], check=True)
    return filename


def mock_model(monkeypatch, *, fail_on_iteration=False, fail_both=False, cuda=False):
    calls=[]
    class WhisperModel:
        def __init__(self, model, device, compute_type, download_root):
            self.device=device
        def transcribe(self, source, **kwargs):
            calls.append(source)
            if isinstance(source, str) and not fail_on_iteration:
                raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
            if isinstance(source, str) and fail_on_iteration:
                def broken():
                    raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
                    yield
                return broken(),types.SimpleNamespace(duration=2.0)
            if fail_both:
                raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
            assert isinstance(source, np.ndarray)
            assert source.size > 10000
            row=types.SimpleNamespace(start=0.1,end=1.9,text='Audio processed successfully')
            return iter([row]), types.SimpleNamespace(duration=2.0)
    monkeypatch.setitem(sys.modules,'faster_whisper',types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setitem(sys.modules,'ctranslate2',types.SimpleNamespace(get_cuda_device_count=lambda: int(cuda)))
    return calls


@pytest.mark.parametrize('during_iteration',[False,True])
def test_real_ffmpeg_recovers_exact_pyav_bug(tmp_path,monkeypatch,during_iteration):
    # Actual generated audio is decoded by FFmpeg; only ML is substituted.
    audio=sample_audio(tmp_path)
    calls=mock_model(monkeypatch,fail_on_iteration=during_iteration)
    messages=[]
    outputs=core.recognize(audio,tmp_path/'out','balanced',None,False,
                           lambda text,pct:messages.append(text),threading.Event())
    assert outputs[0].read_text(encoding='utf-8').strip()=='Audio processed successfully'
    assert len(calls)==2
    assert any('Fixing audio compatibility' in m for m in messages)
    assert not list((tmp_path/'out').glob('.decoder-*'))


def test_decoder_fallback_is_bounded(tmp_path,monkeypatch):
    audio=sample_audio(tmp_path)
    calls=mock_model(monkeypatch,fail_both=True)
    with pytest.raises(TypeError,match='metadata_errors'):
        core.recognize(audio,tmp_path/'out','balanced',None,False,lambda *a:None,threading.Event())
    assert len(calls)==2
    assert not (tmp_path/'out'/'Transcript.txt').exists()


def test_other_type_errors_not_swallowed(tmp_path,monkeypatch):
    class BadModel:
        def __init__(self,*args,**kwargs): pass
        def transcribe(self,*args,**kwargs):raise TypeError('A totally unrelated library bug')
    monkeypatch.setitem(sys.modules,'faster_whisper',types.SimpleNamespace(WhisperModel=BadModel))
    monkeypatch.setitem(sys.modules,'ctranslate2',types.SimpleNamespace(get_cuda_device_count=lambda:0))
    with pytest.raises(TypeError,match='unrelated'):
        core.recognize(tmp_path/'input.mp3',tmp_path/'out','balanced',None,False,lambda *a:None,threading.Event())


def test_known_extractor_problems_only():
    for e in ('nsig extraction failed', 'signature solving failed', 'Unable to extract player response', 'Javascript runtime was not found'):
        assert doctor.is_extractor_problem(Exception(e))
    for e in ('HTTP Error 403', 'Private video. Sign in', 'disk full', 'captcha required', 'metadata_errors'):
        assert not doctor.is_extractor_problem(Exception(e))


def test_tool_repair_only_known_dependencies(tmp_path,monkeypatch):
    uv=tmp_path/'.mochi'/'tools'/('uv.exe' if os.name=='nt' else 'uv')
    uv.parent.mkdir(parents=True);uv.write_bytes(b'tool')
    (tmp_path/'app').mkdir(); (tmp_path/'app'/'requirements.txt').write_text('av<19\n')
    captured=[]
    class Done:
        returncode=0
    def fake_run(args,**kwargs):
        captured.append(args)
        return Done()
    monkeypatch.setattr(doctor.subprocess,'run',fake_run)
    monkeypatch.setattr(doctor,'inspect',lambda root:{'versions':{'av':'18.1.0'}})
    monkeypatch.setattr(core,'ensure_ffmpeg',lambda r:str(r))
    info=doctor.repair(tmp_path,lambda *x:None)
    assert info['after']['versions']['av']=='18.1.0'
    assert captured[0][0]==str(uv)
    assert 'pip' in captured[0]
    assert captured[0][-1]==str(tmp_path/'app'/'requirements.txt')


def test_1hack_credit_is_real_link():
    html=(Path(core.__file__).parent/'assets'/'index.html').read_text(encoding='utf-8')
    assert 'Made with' in html and 'https://onehack.st/' in html
    assert 'rel="noopener noreferrer"' in html


def test_compatible_pin_prevents_new_bad_setup():
    content=(Path(core.__file__).parent/'requirements.txt').read_text(encoding='utf-8')
    assert 'av>=16,<19' in content
    assert 'faster-whisper>=1.1,<1.3' in content


def test_broken_ffmpeg_is_repaired(tmp_path,monkeypatch):
    directory=core.ffmpeg_folder(tmp_path);directory.mkdir(parents=True)
    for name in ('ffmpeg','ffprobe'):
        p=directory/(name+('.exe' if os.name=='nt' else ''));p.write_bytes(b'not an executable')
    # Real installed tools supply the repair source; corrupt copies must be replaced.
    result=core.ensure_ffmpeg(tmp_path)
    assert (Path(result)/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')).stat().st_size>1000
    assert (Path(result)/('ffprobe.exe' if os.name=='nt' else 'ffprobe')).stat().st_size>1000


def test_repair_respects_cancel_before_changes(tmp_path,monkeypatch):
    uv=tmp_path/'.mochi'/'tools'/('uv.exe' if os.name=='nt' else 'uv');uv.parent.mkdir(parents=True);uv.write_bytes(b'tool')
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(doctor.RepairError,match='cancelled'):
        doctor.repair(tmp_path,lambda *x:None,cancelled=cancelled)


def test_private_repair_history_is_bounded_and_reuses_failures(tmp_path):
    doctor.remember_fix(tmp_path,'extractor','update_downloader',False)
    assert doctor.recently_failed(tmp_path,'extractor','update_downloader')
    doctor.remember_fix(tmp_path,'extractor','update_downloader',True)
    assert not doctor.recently_failed(tmp_path,'extractor','update_downloader')
    for _ in range(90):
        doctor.remember_fix(tmp_path,'tools','repair_dependencies',True)
    import json
    entries=json.loads((tmp_path/'.mochi'/'fix-history.json').read_text(encoding='utf-8'))
    assert len(entries)==64
    assert all('url' not in e and 'path' not in e for e in entries)
