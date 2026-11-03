"""Keep public docs aligned with the working Mochi browser studio."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def test_readme_shows_real_current_ui_and_completed_transcript():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    ui = (ROOT / "app/assets/index.html").read_text(encoding="utf-8")
    assert ui.count('class="side-link"') == 3
    assert "Home" not in ui.split('<aside class="sidebar"')[1].split("</aside>")[0]
    assert 'id="open-transcript"' in ui
    assert 'id="copy-transcript"' in ui
    assert 'id="open-folder"' in ui
    for image in ("mochi-interface.webp", "mochi-transcript-result.webp",
                  "mochi-first-time-vs-next-time.webp"):
        assert f"docs/{image}" in readme
        path = ROOT / "docs" / image
        assert path.is_file()
        with Image.open(path) as img:
            assert img.format == "WEBP"
            assert img.width >= 800 and img.height >= 180
            img.verify()


def test_documentation_does_not_promise_unreleased_updater_or_bookmark_support():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "issues/11" in readme
    assert "not available yet" in readme
    assert "A bookmarked local browser link can stop working" in readme
    assert "Run Mochi Now" in readme


def test_both_bundled_guides_match_actual_result_actions():
    guide = (ROOT / "📖 READ ME.txt").read_text(encoding="utf-8")
    installed = (ROOT / "app/install_layout.py").read_text(encoding="utf-8")
    for label in ("Open transcript", "Copy for AI", "Open folder", "Run Mochi Now"):
        assert label in guide
        assert label in installed
    assert "Open my saved files" not in guide
    assert "Open my saved files" not in installed


def test_preview_generator_is_reusable_without_publishing_fake_features():
    workflow = (ROOT / ".github/workflows/docs-screenshots.yml").read_text(encoding="utf-8")
    script = (ROOT / ".github/scripts/render_docs_previews.py").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "capture_actual_ui" in script
    assert "This example uses demonstration text" in script
    assert "open-transcript" in script and "copy-transcript" in script


def test_setup_guide_preserves_approved_mascot_artwork():
    """Automatic UI screenshots must never overwrite the curated bunny guide."""
    script = (ROOT / ".github/scripts/render_docs_previews.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/docs-screenshots.yml").read_text(encoding="utf-8")
    assert "capture_setup_guide(browser)" not in script
    assert "def guide_html(" not in script
    assert "git add docs/mochi-interface.webp docs/mochi-transcript-result.webp\\n" in workflow
    assert "git add docs/mochi-interface.webp docs/mochi-transcript-result.webp docs/mochi-first-time-vs-next-time.webp" not in workflow
