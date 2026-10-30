"""True filesystem tests for first-run cleanup, failure preservation and launchers."""
import importlib
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import zipfile

import pytest
import install_layout
from mochi_paths import root_dir, output_dir, app_dir

SOURCE=Path(__file__).resolve().parents[1]

@pytest.fixture
def work(tmp_path, monkeypatch):
    # Use a path with spaces and special but portable characters.
    root=tmp_path/'Downloads'/'my Mochi [video] & studio'
    root.mkdir(parents=True)
    shutil.copytree(SOURCE, root/'app',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    state=root/'.mochi'
    for name,target in [('ROOT',root),('STATE',state),('STAGED',root/'app'),('LIVE',state/'app'),('BACKUP',state/'app.previous'),('NEXT',state/'app.next')]:
        monkeypatch.setattr(install_layout,name,target)
    return root


def test_paths_before_after_move(work):
    assert root_dir(work/'app'/'launcher.py') == work
    assert app_dir(work)==work/'app'
    install_layout.prepare()
    assert root_dir(work/'.mochi'/'app'/'launcher.py')==work
    assert app_dir(work)==work/'.mochi'/'app'


def test_prepare_icon_and_launcher(work):
    install_layout.prepare()
    icon=work/'.mochi'/'icons'/'mochi.png'
    assert icon.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
    assert (work/'.mochi'/'icons'/'favicon.ico').stat().st_size>1000
    assert (work/'.mochi'/'icons'/'mochi.icns').stat().st_size>1000
    assert (work/'Run Mochi Now.desktop').exists()
    assert str(work/'.mochi'/'run.sh') in (work/'Run Mochi Now.desktop').read_text()
    assert (work/'.mochi'/'run.sh').stat().st_mode & 0o100


def test_finish_only_launcher_readme_visible(work):
    (work/'1 INSTALL & OPEN - Linux.sh').write_text('existing installer')
    (work/'LOOK - PREVIEW.png').write_text('example')
    (work/'README - START HERE.txt').write_text('old')
    (work/'README.txt').write_text('✦ MOCHI · FIRST TIME ✦\nMade with love by 1Hack\n')
    install_layout.prepare()
    install_layout.finish()
    assert sorted(p.name for p in work.iterdir() if not p.name.startswith('.'))==['Run Mochi Now.desktop','📖 READ ME.txt']
    readme=(work/'📖 READ ME.txt').read_text()
    assert len(readme)<500 and '1Hack' in readme and '📂' in readme
    assert not (work/'app').exists()
    assert (work/'.mochi'/'app'/'core.py').exists()
    assert (work/'.mochi'/'run.sh').exists()


def test_never_delete_unrelated_files_or_existing_downloads(work):
    (work/'Family video.mp4').write_bytes(b'family memories')
    (work/'Notes.txt').write_text('keep')
    (work/'My Downloads'/'test').mkdir(parents=True)
    (work/'My Downloads'/'test'/'video.mp4').write_bytes(b'example')
    (work/'.mochi'/'models').mkdir(parents=True)
    (work/'.mochi'/'models'/'big-model.bin').write_bytes(b'1234')
    assert output_dir(work)==work/'My Downloads'
    install_layout.prepare(); install_layout.finish()
    assert (work/'Family video.mp4').read_bytes()==b'family memories'
    assert (work/'Notes.txt').read_text()=='keep'
    assert (work/'.mochi'/'Downloads'/'test'/'video.mp4').read_bytes()==b'example'
    assert not (work/'My Downloads').exists()
    assert (work/'.mochi'/'models'/'big-model.bin').read_bytes()==b'1234'


def test_clean_install_downloads_hidden(work):
    assert output_dir(work)==work/'.mochi'/'Downloads'


def test_no_cleanup_before_success(work):
    (work/'1 INSTALL & OPEN - Linux.sh').write_text('original')
    install_layout.prepare()
    assert (work/'app').exists()
    assert (work/'1 INSTALL & OPEN - Linux.sh').read_text()=='original'


def test_upgrade_backup_and_rollback(work):
    old=work/'.mochi'/'app'
    old.mkdir(parents=True)
    (old/'my-installation.txt').write_text('old working version')
    install_layout.prepare()
    assert (work/'.mochi'/'app.previous'/'my-installation.txt').read_text()=='old working version'
    install_layout.rollback()
    assert (old/'my-installation.txt').read_text()=='old working version'
    assert not (work/'.mochi'/'app.previous').exists()
    assert (work/'app').exists()


def test_upgrade_success_cleans_backup(work):
    previous=work/'.mochi'/'app'
    previous.mkdir(parents=True)
    (previous/'old.py').write_text('old')
    (work/'.mochi'/'Downloads').mkdir(parents=True)
    (work/'.mochi'/'Downloads'/'done.txt').write_text('kept')
    install_layout.prepare();install_layout.finish()
    assert not (work/'.mochi'/'app.previous').exists()
    assert not (work/'.mochi'/'app'/'old.py').exists()
    assert (work/'.mochi'/'Downloads'/'done.txt').read_text()=='kept'


def test_mac_launcher_bundle_uses_icon_and_relative_root(work,monkeypatch):
    monkeypatch.setattr(install_layout.sys,'platform','darwin')
    install_layout.prepare()
    bundle=work/'Run Mochi Now.app'
    assert bundle.exists()
    meta=plistlib.loads((bundle/'Contents'/'Info.plist').read_bytes())
    assert meta['CFBundleIconFile']=='mochi.icns'
    assert (bundle/'Contents'/'Resources'/'mochi.icns').exists()
    contents=(bundle/'Contents'/'MacOS'/'Mochi').read_text()
    assert '"$0")/../../..' in contents
    install_layout.finish()
    assert sorted(p.name for p in work.iterdir() if not p.name.startswith('.'))==['Run Mochi Now.app','📖 READ ME.txt']


def test_linux_launcher_shell_is_valid(work):
    install_layout.prepare()
    for sh in ['run.sh','app/bootstrap.sh']:
        f=work/'.mochi'/sh
        r=subprocess.run(['/bin/sh','-n',str(f)],capture_output=True,text=True)
        assert r.returncode==0, r.stderr


def test_favicon_and_branding_source():
    html=(SOURCE/'assets'/'index.html').read_text()
    assert '/assets/mochi.png' in html and '/favicon.ico' in html
    assert 'id="repair"' in html and 'repair hidden' not in html
    assert html.count('id="repair"') == 1
    assert 'https://onehack.st/' in html


def test_interrupted_upgrade_self_recovers(work):
    state=work/'.mochi'
    (state/'app').mkdir(parents=True)
    (state/'app'/'partially-copied.txt').write_text('broken')
    (state/'app.previous').mkdir(parents=True)
    (state/'app.previous'/'working-code.py').write_text('old good code')
    install_layout.prepare()
    assert (state/'app'/'core.py').exists()
    assert (state/'app.previous'/'working-code.py').read_text()=='old good code'
    install_layout.finish()
    assert not (state/'app.previous').exists()


def test_busy_old_server_prevents_cleanup(work,monkeypatch):
    install_layout.prepare()
    (work/'1 INSTALL & OPEN - Linux.sh').write_text('keep while old download works')
    monkeypatch.setattr(install_layout,'_older_app_is_busy',lambda:True)
    with pytest.raises(RuntimeError,match='still working'):
        install_layout.finish()
    assert (work/'app').exists()
    assert (work/'1 INSTALL & OPEN - Linux.sh').exists()


def test_migrate_downloads_does_not_overwrite_collisions(work):
    old=work/'My Downloads';old.mkdir()
    (old/'same.mp4').write_text('original')
    (old/'unique.mp4').write_text('unique')
    new=work/'.mochi'/'Downloads';new.mkdir(parents=True)
    (new/'same.mp4').write_text('existing')
    install_layout.prepare();install_layout.finish()
    assert (new/'same.mp4').read_text()=='existing'
    assert (old/'same.mp4').read_text()=='original'
    assert (new/'unique.mp4').read_text()=='unique'


def test_migrated_output_path_uses_hidden_location(work):
    (work/'My Downloads').mkdir()
    assert output_dir(work)==work/'My Downloads'
    install_layout.prepare()
    assert output_dir(work)==work/'.mochi'/'Downloads'


def test_readme_emoji_name_and_credit(work):
    install_layout.prepare();install_layout.finish()
    readme=work/'📖 READ ME.txt'
    assert readme.exists()
    assert '💜 Made with love by 1Hack — OneHack.st' in readme.read_text()
    assert not (work/'README.txt').exists()

def test_old_generated_readme_is_retired_only_when_owned(work):
    old=work/'README.txt'
    old.write_text('✦ MOCHI · FIRST TIME ✦\nMade with love by 1Hack\n')
    install_layout.prepare();install_layout.finish()
    assert not old.exists()

def test_personal_readme_is_never_removed(work):
    old=work/'README.txt'
    old.write_text('my personal notes')
    install_layout.prepare();install_layout.finish()
    assert old.read_text()=='my personal notes'

def test_favicon_purple_contrast():
    from PIL import Image
    im=Image.open(SOURCE/'assets'/'mochi.png').convert('RGBA')
    assert im.getpixel((130,300))[:3] == (150,127,234)
