"""Independent captions → alternate captions → local audio AI, fully offline tests."""
import sys
import threading
import types

import pytest
import captions
import core

URL = "https://www.youtube.com/watch?v=MgngwkPAuqQ"


class Snippet:
    def __init__(self, start, duration, text):
        self.start, self.duration, self.text = start, duration, text


class Track:
    def __init__(self, lang="en", generated=False, parts=None, error=None):
        self.language_code = lang
        self.is_generated = generated
        self.parts = parts if parts is not None else [Snippet(0, 2.5, "Hello from captions.")]
        self.error = error
        self.called = 0

    def fetch(self):
        self.called += 1
        if self.error:
            raise self.error
        return self.parts


def fake_api(monkeypatch, tracks, *, error=None, cancel=None):
    calls = []
    class Api:
        def list(self, video_id):
            calls.append(video_id)
            if cancel is not None:
                cancel.set()
            if error:
                raise error
            return tracks
    monkeypatch.setitem(sys.modules, "youtube_transcript_api",
                        types.SimpleNamespace(YouTubeTranscriptApi=Api))
    return calls


def test_youtube_id_validation():
    v = "MgngwkPAuqQ"
    assert captions._video_id(URL) == v
    assert captions._video_id("https://youtu.be/" + v) == v
    assert captions._video_id("https://www.youtube.com/shorts/" + v) == v
    assert captions._video_id("https://music.youtube.com/watch?v=" + v) == v
    assert captions._video_id("https://www.youtube.com/live/" + v) == v
    assert captions._video_id("https://evil.example/watch?v=" + v) is None
    assert captions._video_id("http://127.0.0.1/watch?v=" + v) is None
    assert captions._video_id("https://youtube.com/playlist?list=" + v) is None
    assert captions._video_id("https://youtube.com/watch?v=not-an-id") is None


def test_secondary_saves_subtitles_without_audio_or_ai(tmp_path, monkeypatch):
    import yt_dlp
    class PrimaryMissing:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def extract_info(self, url, download=False):
            return {"title": "Sample", "language": "en", "subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", PrimaryMissing)
    calls = fake_api(monkeypatch, [Track(parts=[Snippet(1, 1.25, "<b>Hello &amp; welcome</b>")])])
    monkeypatch.setattr(core, "_get_audio", lambda *args: pytest.fail("Should not download audio"))
    monkeypatch.setattr(core, "recognize", lambda *args: pytest.fail("Should not load AI"))
    updates = []
    result = core.process(URL, tmp_path, tmp_path, {"mode": "subtitles"},
                          lambda m, p=None: updates.append(m), threading.Event())
    assert calls == ["MgngwkPAuqQ"]
    assert [p.name for p in result] == ["Subtitles.srt", "Subtitles.vtt"]
    assert "00:00:01,000 --> 00:00:02,250" in result[0].read_text(encoding="utf-8")
    assert "Hello & welcome" in result[1].read_text(encoding="utf-8")
    assert "Quick captions saved" in updates[-1]


def test_secondary_prefers_human_caption_track(tmp_path, monkeypatch):
    generated = Track("en", generated=True, parts=[Snippet(0, 1, "Automatic.")])
    manual = Track("en", generated=False, parts=[Snippet(0, 1, "Creator text.")])
    fake_api(monkeypatch, [generated, manual])
    result = captions.try_alternative_captions(URL, tmp_path, None, False,
                                               lambda *args: None, threading.Event())
    assert result[0].read_text(encoding="utf-8") == "Creator text.\n"
    assert generated.called == 0
    assert manual.called == 1


def test_automatic_language_uses_available_non_english_track(tmp_path, monkeypatch):
    fake_api(monkeypatch, [Track("ta", parts=[Snippet(0, 1, "வணக்கம்")])])
    result = captions.try_alternative_captions(URL, tmp_path, None, False,
                                               lambda *args: None, threading.Event())
    assert result[0].read_text(encoding="utf-8") == "வணக்கம்\n"


def test_requested_language_never_uses_wrong_track(tmp_path, monkeypatch):
    fake_api(monkeypatch, [Track("en")])
    result = captions.try_alternative_captions(URL, tmp_path, "hi", True,
                                               lambda *args: None, threading.Event())
    assert result is None
    assert not list(tmp_path.glob("Subtitles.*"))


@pytest.mark.parametrize("parts", [
    [], [Snippet(0, 0, "No duration")],
    [Snippet(-3, 2, "Invalid")],
    [Snippet(0, 1, "")],
    [Snippet(0, 1, "<b></b>")],
])
def test_bad_or_empty_secondary_captions_never_published(tmp_path, monkeypatch, parts):
    fake_api(monkeypatch, [Track(parts=parts)])
    assert captions.try_alternative_captions(
        URL, tmp_path, None, True, lambda *args: None, threading.Event()) is None
    assert not list(tmp_path.glob("Subtitles.*"))


def test_secondary_network_failure_falls_back_to_local_audio(tmp_path, monkeypatch):
    fake_api(monkeypatch, [], error=RuntimeError("YouTube declined the request"))
    monkeypatch.setattr(captions, "try_captions", lambda *args: None)
    audio = tmp_path / "cached-audio.mp3"
    audio.write_bytes(b"already downloaded")
    actions = []
    monkeypatch.setattr(core, "_get_audio",
                        lambda *args: (actions.append("audio") or audio))
    def recognize(_media, out, *args):
        actions.append("ai")
        target = out / "Transcript.txt"
        target.write_text("From the original audio", encoding="utf-8")
        return [target]
    monkeypatch.setattr(core, "recognize", recognize)
    result = core.process(URL, tmp_path, tmp_path, {"mode": "transcript"},
                          lambda *args: None, threading.Event())
    assert actions == ["audio", "ai"]
    assert result[0].read_text(encoding="utf-8") == "From the original audio"


def test_cancel_during_secondary_fetch_never_saves_files(tmp_path, monkeypatch):
    cancelled = threading.Event()
    fake_api(monkeypatch, [Track()], cancel=cancelled)
    assert captions.try_alternative_captions(
        URL, tmp_path, None, True, lambda *args: None, cancelled) is None
    assert not list(tmp_path.glob("Subtitles.*"))


def test_no_unauthorized_hosted_site_scraping():
    source = open(captions.__file__, encoding="utf-8").read()
    assert "freeyoutubetranscribe.com" not in source
    assert "yoututranscript.com" not in source
