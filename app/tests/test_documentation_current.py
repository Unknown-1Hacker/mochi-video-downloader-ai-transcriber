"""Keep public docs aligned with the working Mochi browser studio."""
from pathlib import Path
from xml.etree import ElementTree
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



def test_visual_workflow_is_readable_responsive_and_not_a_mock_ui():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '<picture>' in readme
    assert 'media="(max-width: 700px)"' in readme
    assert 'srcset="docs/mochi-how-it-works-mobile.svg"' in readme
    assert 'src="docs/mochi-how-it-works.svg"' in readme
    assert "Illustrated workflow" in readme
    assert 'docs/mochi-interface.webp' in readme
    for name, width in (("mochi-how-it-works.svg", "1280"),
                        ("mochi-how-it-works-mobile.svg", "720")):
        file = ROOT / "docs" / name
        assert file.is_file()
        svg = ElementTree.parse(file).getroot()
        assert svg.attrib["width"] == width
        assert svg.attrib["role"] == "img"
        assert svg.attrib.get("aria-label")
        text = " ".join(svg.itertext())
        for word in ("yt-dlp", "FFmpeg", "youtube-transcript-api",
                     "faster-whisper", "Subtitles.srt", "Transcript.txt"):
            assert word in text, (name, word)
        assert not any(element.tag.rsplit("}", 1)[-1] in
                       ("script", "foreignObject") for element in svg.iter())
        assert not any(key.endswith("href") for element in svg.iter()
                       for key in element.attrib)
    workflow = (ROOT / ".github/workflows/docs-screenshots.yml").read_text(encoding="utf-8")
    assert "git add docs/mochi-how-it-works.svg" not in workflow
    assert "git add docs/mochi-how-it-works-mobile.svg" not in workflow


def test_documentation_does_not_promise_unreleased_updater_or_bookmark_support():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "issues/11" in readme
    assert "Still planned, not available yet" in readme
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
    assert "git add docs/mochi-interface.webp docs/mochi-transcript-result.webp" in workflow
    assert "git add docs/mochi-interface.webp docs/mochi-transcript-result.webp docs/mochi-first-time-vs-next-time.webp" not in workflow


def test_update_button_replaces_duplicate_settings_link_without_losing_controls():
    ui = (ROOT / "app/assets/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/assets/app.js").read_text(encoding="utf-8")
    assert ui.count('class="side-link"') == 3
    assert ui.count('data-check-updates') == 2
    assert 'data-go-settings' not in ui
    assert 'id="finishing"' in ui  # Main quality/language settings remain.
    for element in ('update-dialog', 'install-update', 'cancel-update',
                    'check-update-again', 'close-updates'):
        assert f'id="{element}"' in ui
    for path in ("/api/update/check", "/api/update/start", "/api/update/cancel",
                 "/api/update/status"):
        assert path in script
    assert "In-app updates, persistent transcript history" not in (ROOT / "README.md").read_text(encoding="utf-8")
