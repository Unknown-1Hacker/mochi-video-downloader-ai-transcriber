import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import studio

@pytest.fixture
def server(tmp_path,monkeypatch):
    monkeypatch.setattr(studio, 'ROOT',tmp_path)
    monkeypatch.setattr(studio, 'OUTPUT_DIR',tmp_path/'My Downloads')
    import shutil
    shutil.copytree(Path(studio.__file__).parent/'assets',tmp_path/'app'/'assets')
    s=ThreadingHTTPServer(('127.0.0.1',0),studio.WebHandler)
    s.daemon_threads=True
    s.secret='test-secret-for-local-sessions-only'
    t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    yield f'http://127.0.0.1:{s.server_address[1]}',s.secret,tmp_path
    s.shutdown();s.server_close();t.join(timeout=3)

def request(base,path,token=None,data=None):
    headers={'X-Mochi-Key':token} if token else {}
    content=None
    if data is not None:
        content=json.dumps(data).encode();headers['Content-Type']='application/json'
    r=urllib.request.Request(base+path,headers=headers,data=content)
    return urllib.request.urlopen(r,timeout=3)

def test_home_requires_session(server):
    base,token,_=server
    with pytest.raises(urllib.error.HTTPError) as exc:request(base,'/')
    assert exc.value.code==403
    with request(base,'/?key='+token) as r:
        page=r.read().decode()
        assert 'Mochi' in page and 'Full video' in page and token in page
        assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']

def test_api_requires_session(server):
    base,_,_=server
    with pytest.raises(urllib.error.HTTPError) as exc:request(base,'/api/status')
    assert exc.value.code==403

def test_bogus_origin_rejected(server):
    base,token,_=server
    req=urllib.request.Request(base+'/api/start',data=json.dumps({'url':'https://youtu.be/abc'}).encode(),headers={'X-Mochi-Key':token,'Origin':'https://evil.example'})
    with pytest.raises(urllib.error.HTTPError) as exc:urllib.request.urlopen(req,timeout=3)
    assert exc.value.code==403

def test_html_assets_served(server):
    base,token,_=server
    for path in ['/assets/app.js','/assets/style.css']:
        with request(base,path) as r:assert r.status==200 and len(r.read())>1000

def test_one_job_end_to_end_through_server(server,monkeypatch):
    base,token,root=server
    done=threading.Event()
    def fake_process(url,root,output,opts,update,cancel):
        update('Processing original audio…',70)
        result=output/'test-id'/'Transcript.txt'
        result.parent.mkdir(parents=True,exist_ok=True)
        result.write_text('Real recognized speech')
        done.set()
        return [result]
    monkeypatch.setattr(studio,'process',fake_process)
    data={'url':'https://www.youtube.com/watch?v=MgngwkPAuqQ','options':{'mode':'transcript'}}
    with request(base,'/api/start',token,data) as r:assert r.status==200
    assert done.wait(3)
    for _ in range(30):
        with request(base,'/api/status',token) as r:status=json.loads(r.read())
        if status['state']=='done':break
        time.sleep(.05)
    assert status['state']=='done' and status['files']==['Transcript.txt']
    assert (root/'My Downloads'/'test-id'/'Transcript.txt').exists()
    # Real completed state exposes only its saved transcript through local auth.
    with request(base, '/api/transcript', token) as resp:
        payload = json.loads(resp.read())
        assert resp.headers['Cache-Control'] == 'no-store'
    assert payload == {'text': 'Real recognized speech'}

def test_invalid_input_server_400(server):
    base,token,_=server
    with pytest.raises(urllib.error.HTTPError) as exc: request(base,'/api/start',token,{'url':'file:///etc/passwd'})
    assert exc.value.code==400

def test_large_requests_rejected(server):
    base,token,_=server
    with pytest.raises(urllib.error.HTTPError) as exc: request(base,'/api/start',token,{'url':'x'*9000})
    assert exc.value.code==400


def test_health_advertises_version(server):
    base,token,_=server
    with request(base,'/api/health',token) as resp:
        health=json.loads(resp.read())
    assert health['ok'] and health['version']==studio.APP_VERSION


def test_repair_endpoint_runs_once_and_returns_state(server,monkeypatch):
    base,token,root=server
    finished=threading.Event()
    def fake_repair(root,update,**kwargs):
        update('Repairing known tools…',55)
        finished.set()
    monkeypatch.setattr(studio,'repair',fake_repair)
    monkeypatch.setattr(studio,'remember_fix',lambda *a:None)
    with request(base,'/api/repair',token,{}) as resp:
        assert resp.status==200
    assert finished.wait(3)
    for _ in range(50):
        with request(base,'/api/status',token) as resp:
            result=json.loads(resp.read())
        if result['state']=='repaired':break
        time.sleep(.025)
    assert result['state']=='repaired'
    assert result['percent']==100


def test_extractor_failure_auto_repairs_once(server,monkeypatch):
    base,token,root=server
    calls=[]
    repair_calls=[]
    def fake_process(url,root,output,opts,update,cancel):
        calls.append(url)
        if len(calls)==1:raise ValueError('nsig extraction failed')
        file=output/'sample'/'Transcript.txt';file.parent.mkdir(parents=True,exist_ok=True);file.write_text('audio output')
        return [file]
    monkeypatch.setattr(studio,'process',fake_process)
    monkeypatch.setattr(studio,'repair',lambda *args,**kwargs: repair_calls.append('yes'))
    monkeypatch.setattr(studio,'remember_fix',lambda *args:None)
    monkeypatch.setattr(studio,'recently_failed',lambda *args:False)
    data={'url':'https://youtu.be/MgngwkPAuqQ','options':{'mode':'transcript'}}
    with request(base,'/api/start',token,data) as resp:assert resp.status==200
    for _ in range(50):
        with request(base,'/api/status',token) as resp:status=json.loads(resp.read())
        if status['state']=='done':break
        time.sleep(.025)
    assert status['state']=='done'
    assert len(calls)==2 and len(repair_calls)==1


def test_approved_bunny_asset_is_really_served(server):
    base, _, _ = server
    with request(base, '/assets/hero-bunny.png?v=1.5.0') as resp:
        assert resp.status == 200
        assert resp.headers['Content-Type'] == 'image/png'
        assert resp.read()[:8] == b'\x89PNG\r\n\x1a\n'


def test_real_favicon_served(server):
    base,token,_=server
    with request(base,'/favicon.ico') as resp:
        assert resp.headers['Content-Type']=='image/x-icon'
        assert resp.read()[:4]==b'\x00\x00\x01\x00'
    with request(base,'/assets/mochi.png') as resp:
        assert resp.headers['Content-Type']=='image/png'
        assert resp.read()[:8]==b'\x89PNG\r\n\x1a\n'


def test_downloads_button_opens_folder_even_before_first_job(server, monkeypatch):
    base, token, root = server
    calls = []
    monkeypatch.setattr(studio.subprocess, 'Popen', lambda args: calls.append(args))
    with request(base, '/api/open-downloads', token, {}) as resp:
        assert json.loads(resp.read())['ok']
    assert (root / 'My Downloads').is_dir()
    if os.name == 'nt':
        assert calls == []  # Windows uses os.startfile, not subprocess.Popen
    else:
        command = 'open' if sys.platform == 'darwin' else 'xdg-open'
        assert calls == [[command, str((root / 'My Downloads').resolve())]]


def test_downloads_button_rejects_unauthorized_calls(server):
    base, token, root = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/open-downloads', None, {})
    assert exc.value.code == 403


def test_new_ui_uses_real_controls(server):
    base, token, _ = server
    with request(base, '/?key=' + token) as resp:
        page = resp.read().decode()
    assert 'Paste your YouTube link' in page
    assert 'class="sidebar"' in page
    assert 'name="mode" value="transcript"' in page
    assert 'data-open-downloads' in page
    assert page.count('id="repair"') == 1


def test_sidebar_has_only_three_utilities_and_home_keeps_four_choices(server):
    """Avoid duplicate mode selectors; retain operational shortcuts."""
    from html.parser import HTMLParser

    class SidebarReader(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside_sidebar = False
            self.buttons = []
            self.button_level = 0
            self.current = None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'aside' and 'sidebar' in attrs.get('class', '').split():
                self.inside_sidebar = True
            elif self.inside_sidebar and tag == 'button':
                self.current = attrs
                self.button_level += 1
                self.buttons.append(attrs)
        def handle_endtag(self, tag):
            if tag == 'button' and self.inside_sidebar and self.button_level:
                self.button_level -= 1
                self.current = None
            elif tag == 'aside' and self.inside_sidebar:
                self.inside_sidebar = False

    base, token, _ = server
    with request(base, '/?key=' + token) as resp:
        page = resp.read().decode()
    reader = SidebarReader()
    reader.feed(page)
    assert len(reader.buttons) == 3
    assert ['data-go-settings' in b for b in reader.buttons] == [True, False, False]
    assert ['data-open-downloads' in b for b in reader.buttons] == [False, True, False]
    assert ['data-repair' in b for b in reader.buttons] == [False, False, True]
    assert 'data-choose-mode' not in page
    assert 'data-go-home' not in page
    for mode in ('video', 'audio', 'subtitles', 'transcript'):
        assert page.count(f'name="mode" value="{mode}"') == 1
    # The same tools remain available via the header when mobile hides the sidebar.
    assert page.count('data-go-settings') == 2
    assert page.count('data-open-downloads') == 2
    assert page.count('data-repair') == 1
    assert page.count('id="repair"') == 1


def test_sidebar_javascript_keeps_real_shortcuts_without_removed_handlers():
    source = (Path(studio.__file__).parent / 'assets' / 'app.js').read_text(encoding='utf-8')
    assert 'data-go-home' not in source
    assert 'data-choose-mode' not in source
    assert "document.querySelectorAll('[name=\"mode\"]')" in source
    assert "document.querySelectorAll('[data-go-settings]')" in source
    assert "document.querySelectorAll('[data-repair]')" in source
    assert "document.querySelectorAll('[data-open-downloads]')" in source


def test_transcript_requires_private_session(server):
    base, token, root = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript')
    assert exc.value.code == 403


def test_transcript_unavailable_until_job_completed(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(
        read=lambda: {'state': 'working', 'folder': '', 'files': ['Transcript.txt']}
    ))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400


def test_transcript_preview_preserves_unicode_and_newlines(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    folder = root / 'My Downloads' / 'Family [video]'
    folder.mkdir(parents=True)
    text = 'Hello, AI!\nவணக்கம் 🌸\nArabic: مرحبا\n'
    (folder / 'Transcript.txt').write_text(text, encoding='utf-8')
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(
        read=lambda: {'state': 'done', 'folder': str(folder), 'files': ['Transcript.txt']}
    ))
    with request(base, '/api/transcript', token) as resp:
        assert resp.status == 200
        assert resp.headers['X-Content-Type-Options'] == 'nosniff'
        assert json.loads(resp.read()) == {'text': text}


def test_transcript_does_not_read_unlisted_or_outside_files(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    folder = root / 'My Downloads' / 'finished'
    folder.mkdir(parents=True)
    (folder / 'Transcript.txt').write_text('SAVED')
    current = {'state': 'done', 'folder': str(folder), 'files': []}
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(read=lambda: dict(current)))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400
    # Even a forged "done" state must not expose files outside Mochi's output root.
    outsider = root / 'personal'
    outsider.mkdir()
    (outsider / 'Transcript.txt').write_text('PRIVATE')
    current.update(folder=str(outsider), files=['Transcript.txt'])
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400


@pytest.mark.skipif(os.name == 'nt', reason='Symlink creation may need elevated Windows permissions')
def test_transcript_does_not_follow_symlink(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    folder = root / 'My Downloads' / 'finished'
    folder.mkdir(parents=True)
    other = root / 'private.txt'
    other.write_text('NEVER SHARE')
    (folder / 'Transcript.txt').symlink_to(other)
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(
        read=lambda: {'state': 'done', 'folder': str(folder), 'files': ['Transcript.txt']}
    ))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400


def test_transcript_too_large_to_copy_as_json(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    folder = root / 'My Downloads' / 'finished'
    folder.mkdir(parents=True)
    (folder / 'Transcript.txt').write_bytes(b'a' * (studio.TRANSCRIPT_PREVIEW_LIMIT + 1))
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(
        read=lambda: {'state': 'done', 'folder': str(folder), 'files': ['Transcript.txt']}
    ))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400
    assert 'too large' in exc.value.read().decode().lower()


def test_transcript_read_failure_does_not_expose_other_files(server, monkeypatch):
    from types import SimpleNamespace
    base, token, root = server
    folder = root / 'My Downloads' / 'finished'
    folder.mkdir(parents=True)
    (folder / 'Transcript.txt').write_bytes(b'\xff\xff')
    monkeypatch.setattr(studio, 'JOB', SimpleNamespace(
        read=lambda: {'state': 'done', 'folder': str(folder), 'files': ['Transcript.txt']}
    ))
    with pytest.raises(urllib.error.HTTPError) as exc:
        request(base, '/api/transcript', token)
    assert exc.value.code == 400


def test_finished_transcript_controls_are_optional_and_local(server):
    base, token, _ = server
    with request(base, '/?key=' + token) as resp:
        page = resp.read().decode()
    for control in ('open-transcript', 'copy-transcript', 'open-folder',
                    'transcript-text', 'transcript-preview'):
        assert f'id="{control}"' in page
    assert 'readonly' in page
    assert 'ChatGPT, Claude, or any AI' in page
    js = (Path(studio.__file__).parent / 'assets' / 'app.js').read_text(encoding='utf-8')
    assert "api('/api/transcript')" in js
    assert 'navigator.clipboard.writeText(text)' in js
    assert "st.files.includes('Transcript.txt')" in js
    assert 'https://chatgpt.com' not in js and 'https://claude.ai' not in js
