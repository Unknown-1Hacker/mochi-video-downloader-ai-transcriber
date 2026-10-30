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
    assert 'data-choose-mode="transcript"' in page
    assert 'data-open-downloads' in page
    assert page.count('id="repair"') == 1
