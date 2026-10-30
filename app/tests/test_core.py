import json
import os
import sys
import threading
import types
from pathlib import Path

import pytest
import core

URL = 'https://www.youtube.com/watch?v=MgngwkPAuqQ'

@pytest.mark.parametrize('url', [URL,'https://youtu.be/MgngwkPAuqQ','https://m.youtube.com/shorts/abc123','https://music.youtube.com/watch?v=abc123'])
def test_allowed_youtube(url):
    assert core.check_url(url) == url

@pytest.mark.parametrize('url', ['', 'javascript:alert(1)', 'file:///etc/passwd','http://127.0.0.1:8080','https://youtube.com.bad-site.net/watch?v=x','https://evil.com/?u=youtube.com','https://u:p@youtube.com/watch?v=x','https://youtube.com/playlist?list=PLx'])
def test_rejects_unsafe_urls(url):
    with pytest.raises(core.FriendlyError): core.check_url(url)

def test_filenames_are_safe_and_bounded():
    name = core.slug('../\\:*?<>|My Video\x00  ') 
    assert not any(c in name for c in '/\\:*?<>|')
    assert len(core.slug('a'*150)) <= 90

def test_timestamps_edge_rounding():
    assert core.stamp(0.0) == '00:00:00,000'
    assert core.stamp(3600.9999) == '01:00:01,000'
    assert core.stamp(12.345, True) == '00:00:12.345'

def test_video_resolutions_are_real_not_invented():
    data = {'formats': [{'height': 1080, 'vcodec': 'av1'},{'height':720,'vcodec':'h264'},{'height':720,'vcodec':'vp9'},{'height':None,'vcodec':'none'},{'height':240,'vcodec':'none'}]}
    assert core.choices(data) == [1080,720]

def test_ffmpeg_is_prepared_locally(tmp_path):
    d=Path(core.ensure_ffmpeg(tmp_path))
    name='ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    assert (d/name).is_file() and (d/name).stat().st_size > 1000

def fake_ydl(tmp_path, monkeypatch, broken=False, abort=False):
    class YDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download):
            if abort: raise RuntimeError('Request blocked')
            if not download: return {'title':'Video','formats':[{'height':480,'vcodec':'h264'}]}
            p=Path(self.opts['outtmpl'].replace('%(title).90B','Test').replace('%(id)s','abc').replace('%(ext)s','webm'))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'a'*8192)
            self.opts['progress_hooks'][0]({'status':'downloading','total_bytes':8192,'downloaded_bytes':4000})
            self.opts['progress_hooks'][0]({'status':'finished'})
            return {'title':'Test'}
    monkeypatch.setitem(sys.modules, 'yt_dlp', types.SimpleNamespace(YoutubeDL=YDL))
    monkeypatch.setattr(core, 'common_ydl', lambda r: {'noplaylist':True})

def test_ytdlp_downloads_audio_without_subtitles(tmp_path, monkeypatch):
    fake_ydl(tmp_path,monkeypatch)
    events=[]
    f=core._download(URL,tmp_path,tmp_path/'out','audio',None,False,lambda m,p:events.append((m,p)),threading.Event())
    assert f.is_file() and events and events[-1][1]==96

def test_download_cancellation_is_detected(tmp_path,monkeypatch):
    fake_ydl(tmp_path,monkeypatch)
    cancel=threading.Event();cancel.set()
    with pytest.raises(core.UserCancelled): core._download(URL,tmp_path,tmp_path/'out','audio',None,False,lambda *x:None,cancel)

def test_download_error_is_visible(tmp_path,monkeypatch):
    fake_ydl(tmp_path,monkeypatch,abort=True)
    with pytest.raises(RuntimeError,match='blocked'): core._download(URL,tmp_path,tmp_path/'out','audio',None,False,lambda *x:None,threading.Event())

def test_download_formats_follow_settings():
    assert 'height<=720' in core._formats('video',720)
    assert core._formats('video',None)=='bv*+ba/b'
    assert core._formats('audio',None)=='bestaudio/best'

def fake_whisper(monkeypatch, segments, gpu=False, gpu_fails=False):
    attempts=[]
    class WhisperModel:
        def __init__(self,model,device,compute_type,download_root=None):
            attempts.append((model,device,compute_type))
            if device=='cuda' and gpu_fails:raise RuntimeError('CUDA error')
        def transcribe(self,media,**kwargs):
            return iter(segments), types.SimpleNamespace(duration=5.0,language='en')
    monkeypatch.setitem(sys.modules, 'faster_whisper',types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setitem(sys.modules, 'ctranslate2',types.SimpleNamespace(get_cuda_device_count=lambda : 1 if gpu else 0))
    return attempts

def seg(start,end,text):return types.SimpleNamespace(start=start,end=end,text=text)

def test_transcript_is_from_audio_and_saved(tmp_path,monkeypatch):
    attempts=fake_whisper(monkeypatch,[seg(0,2,' hello there '),seg(2,4,' world ')])
    results=core.recognize(tmp_path/'audio.m4a',tmp_path/'output','balanced',None,False,lambda *a:None,threading.Event())
    assert len(results)==1 and results[0].name=='Transcript.txt'
    assert results[0].read_text()=='hello there\nworld\n'
    assert attempts[0][0]=='small'

def test_subtitle_formats_and_timestamps(tmp_path,monkeypatch):
    fake_whisper(monkeypatch,[seg(0.001,1.901,'Hi'),seg(2.5,3.0,'Goodbye')])
    results=core.recognize(tmp_path/'audio.m4a',tmp_path/'output','accurate','en',True,lambda *a:None,threading.Event())
    assert [x.suffix for x in results]==['.srt','.vtt']
    assert '00:00:00,001 --> 00:00:01,901' in results[0].read_text()
    assert 'WEBVTT' in results[1].read_text()

def test_no_speech_leaves_no_final_files(tmp_path,monkeypatch):
    fake_whisper(monkeypatch,[])
    with pytest.raises(core.FriendlyError,match='No clear speech'): core.recognize(tmp_path/'audio',tmp_path/'out','balanced',None,True,lambda *a:None,threading.Event())
    assert not list((tmp_path/'out').glob('*.srt'))

def test_gpu_fails_and_cpu_safely_recovers(tmp_path,monkeypatch):
    attempts=fake_whisper(monkeypatch,[seg(0,2,'hello')],gpu=True,gpu_fails=True)
    assert core.recognize(tmp_path/'audio',tmp_path/'out','accurate',None,False,lambda *a:None,threading.Event())
    assert attempts==[('large-v3','cuda','float16'),('medium','cpu','int8')]

def test_cancel_does_not_publish_partial_files(tmp_path,monkeypatch):
    cancel=threading.Event()
    class CancelledSegments:
        def __iter__(self):
            yield seg(0,1,'hello')
            cancel.set()
            yield seg(2,3,'world')
    fake_whisper(monkeypatch,CancelledSegments())
    with pytest.raises(core.UserCancelled): core.recognize(tmp_path/'audio',tmp_path/'out','balanced',None,False,lambda *a:None,cancel)
    assert not list((tmp_path/'out').glob('Transcript.txt'))

def test_process_rejects_bad_options(tmp_path):
    with pytest.raises(core.FriendlyError):core.process(URL,tmp_path,tmp_path,{'height':9000},lambda *x:None,threading.Event())
    with pytest.raises(core.FriendlyError):core.process(URL,tmp_path,tmp_path,{'mode':'run-program'},lambda *x:None,threading.Event())

def test_audio_cache_reused_without_download(tmp_path,monkeypatch):
    cache=tmp_path/'.mochi'/'audio-cache'/core.video_key(URL)
    cache.mkdir(parents=True)
    p=cache/'audio.m4a'
    ffmpeg=Path(core.ensure_ffmpeg(tmp_path))/('ffmpeg.exe' if os.name=='nt' else 'ffmpeg')
    import subprocess
    subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','aac','-b:a','128k',str(p)],check=True)
    monkeypatch.setattr(core, '_download', lambda *a,**k:pytest.fail('should not download cached file'))
    assert core._get_audio(URL,tmp_path,tmp_path,lambda *x:None,threading.Event()) == p

def test_not_a_url_object_is_cleanly_rejected():
    for value in [None, 7, {'url':URL}]:
        with pytest.raises(core.FriendlyError):core.check_url(value)

def test_corrupt_cached_audio_is_deleted_and_redownloaded(tmp_path,monkeypatch):
    cache=tmp_path/'.mochi'/'audio-cache'/core.video_key(URL)
    cache.mkdir(parents=True)
    p=cache/'audio.m4a';p.write_bytes(b'x'*8192)
    correct=tmp_path/'new.m4a'
    monkeypatch.setattr(core,'_download',lambda *a,**k:correct)
    assert core._get_audio(URL,tmp_path,tmp_path,lambda *a:None,threading.Event())==correct
    assert not p.exists()

def test_verified_transcripts_reuse_with_matching_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'_get_audio',lambda *a,**k:tmp_path/'audio.m4a')
    counter=[]
    def recog(media,out,*args):
        counter.append(1)
        out.mkdir(parents=True,exist_ok=True)
        p=out/'Transcript.txt';p.write_text('Original audio recognized')
        return [p]
    monkeypatch.setattr(core,'recognize',recog)
    kwargs={'mode':'transcript','speech_quality':'balanced'}
    for _ in range(2):
        out=core.process(URL,tmp_path,tmp_path,kwargs,lambda *a:None,threading.Event())
        assert out[0].read_text()=='Original audio recognized'
    assert len(counter)==1
    out[0].write_text('CORRUPTED')
    core.process(URL,tmp_path,tmp_path,kwargs,lambda *a:None,threading.Event())
    assert len(counter)==2
