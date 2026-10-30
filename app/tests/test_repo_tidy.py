from pathlib import Path
import install_layout


def test_github_zip_source_extras_are_preserved_and_hidden(tmp_path, monkeypatch):
    root = tmp_path / 'Mochi'
    root.mkdir()
    state = root / '.mochi'
    monkeypatch.setattr(install_layout, 'ROOT', root)
    monkeypatch.setattr(install_layout, 'STATE', state)
    (root/'README.md').write_text('# 🐰 Mochi — Video Downloader & AI Transcriber\nHello', encoding='utf-8')
    (root/'pytest.ini').write_text('[pytest]\npythonpath = app\n', encoding='utf-8')
    (root/'.gitignore').write_text('# Mochi generated files and private user data\n', encoding='utf-8')
    (root/'personal-note.txt').write_text('Never touch', encoding='utf-8')
    (root/'docs').mkdir()
    (root/'docs'/'mochi-interface.png').write_bytes(b'PNG original file')
    install_layout._organize_repository_extras()
    assert sorted(p.name for p in root.iterdir()) == ['.mochi', 'personal-note.txt']
    assert (state/'source-extras'/'README.md').read_text(encoding='utf-8').endswith('Hello')
    assert (state/'source-extras'/'docs'/'mochi-interface.png').read_bytes() == b'PNG original file'
    assert (root/'personal-note.txt').read_text(encoding='utf-8') == 'Never touch'


def test_git_checkout_is_never_modified(tmp_path, monkeypatch):
    monkeypatch.setattr(install_layout, 'ROOT', tmp_path)
    monkeypatch.setattr(install_layout, 'STATE', tmp_path/'.mochi')
    (tmp_path/'.git').mkdir()
    readme=tmp_path/'README.md'
    readme.write_text('# 🐰 Mochi — Video Downloader & AI Transcriber\n', encoding='utf-8')
    install_layout._organize_repository_extras()
    assert readme.exists()
