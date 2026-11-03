"""No-network checks of YouTube caption-first and original-audio AI fallback."""
import json
import os
import sys
import threading
import types
from pathlib import Path

import pytest

import core
import captions


URL = "https://www.youtube.com/watch?v=MgngwkPAuqQ"
SAMPLE = """WEBVTT

00:00:00.000 --> 00:00:01.500
<c>Hello &amp; welcome</c>

00:00:01.500 --> 00:00:03.200 align:start position:0%
Today we learn.

00:00:03.200 --> 00:00:04.000
Today we learn.

NOTE this is not speech

00:00:04.500 --> 00:00:05.000
<strong>Goodbye!</strong>
"""


def fake_youtube(monkeypatch, *, tracks=True, broken=False, malformed=False, language="en"):
    calls = []
    class YDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts.copy())
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False):
            assert url == URL
            if broken:
                raise RuntimeError("YouTube captions request failed")
            info = {"title": "Example", "language": language,
                    "subtitles": {language: [{"ext": "vtt"}]} if tracks else {},
                    "automatic_captions": {}}
            if download:
                assert self.opts["skip_download"] is True
                assert self.opts["writesubtitles"] is True
                assert self.opts["writeautomaticsub"] is False
                folder = Path(self.opts["outtmpl"]).parent
                folder.mkdir(parents=True, exist_ok=True)
                (folder / ("speech." + language + ".vtt")).write_text(
                    "Nothing useful" if malformed else SAMPLE, encoding="utf-8"
                )
            return info
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YDL))
    return calls


def test_caption_parser_rejects_bad_cues_and_cleans_tags():
    rows = captions._rows(SAMPLE)
    assert [x[2] for x in rows] == ["Hello & welcome", "Today we learn.", "Goodbye!"]
    assert rows[0][:2] == (0.0, 1.5)
    assert rows[-1][:2] == (4.5, 5.0)
    assert captions._rows("WEBVTT\n\nNOTE no valid cues") == []


def test_prefers_real_subtitles_and_correct_language():
    info = {"language": "en", "subtitles": {"en": [{"ext": "vtt"}]},
            "automatic_captions": {"en": [{"ext": "vtt"}], "es": [{"ext": "vtt"}]}}
    assert captions._language(info, None) == ("en", False)
    assert captions._language(info, "es") == ("es", True)
    assert captions._language(info, "hi") is None


def test_transcript_fast_path_skips_audio_ai_and_saves_files(tmp_path, monkeypatch):
    calls = fake_youtube(monkeypatch)
    monkeypatch.setattr(core, "_get_audio", lambda *a, **k: pytest.fail("AI audio should not be downloaded"))
    monkeypatch.setattr(core, "recognize", lambda *a, **k: pytest.fail("Whisper should not be loaded"))
    updates = []
    result = core.process(URL, tmp_path, tmp_path, {"mode": "transcript"},
                          lambda message, pct=None: updates.append(message), threading.Event())
    assert result[0].name == "Transcript.txt"
    assert result[0].read_text(encoding="utf-8") == "Hello & welcome\nToday we learn.\nGoodbye!\n"
    assert len(calls) == 2
    assert "Instant captions" in updates[-1]
    # Cache is valid: next request does not hit the caption provider.
    other = core.process(URL, tmp_path, tmp_path, {"mode": "transcript"},
                         lambda *args: None, threading.Event())
    assert other == result and len(calls) == 2


def test_subtitles_fast_path_are_valid_formats(tmp_path, monkeypatch):
    fake_youtube(monkeypatch)
    files = core.process(URL, tmp_path, tmp_path, {"mode": "subtitles"},
                         lambda *args: None, threading.Event())
    srt, vtt = (file.read_text(encoding="utf-8") for file in files)
    assert [file.name for file in files] == ["Subtitles.srt", "Subtitles.vtt"]
    assert "00:00:00,000 --> 00:00:01,500" in srt
    assert vtt.startswith("WEBVTT\n\n")
    assert "Hello & welcome" in srt and "Goodbye!" in vtt


@pytest.mark.parametrize("status", ["missing", "broken", "malformed"])
def test_failure_falls_back_to_original_audio(tmp_path, monkeypatch, status):
    fake_youtube(monkeypatch, tracks=status != "missing",
                 broken=status == "broken", malformed=status == "malformed")
    # Both caption strategies are unavailable; only then run local AI.
    monkeypatch.setattr(captions, "try_alternative_captions", lambda *args: None)
    media = tmp_path / "audio.mp3"
    media.write_bytes(b"test")
    counter = []
    def get_audio(*args):
        counter.append("audio")
        return media
    def recognize(_media, out, quality, language, subtitle, update, cancel):
        counter.append("whisper")
        file = out / "Transcript.txt"
        file.write_text("AI heard the original audio.", encoding="utf-8")
        return [file]
    monkeypatch.setattr(core, "_get_audio", get_audio)
    monkeypatch.setattr(core, "recognize", recognize)
    result = core.process(URL, tmp_path, tmp_path, {"mode": "transcript"},
                          lambda *args: None, threading.Event())
    assert counter == ["audio", "whisper"]
    assert result[0].read_text(encoding="utf-8") == "AI heard the original audio."


def test_cancelled_fast_path_never_publishes_output(tmp_path, monkeypatch):
    cancel = threading.Event()
    class YDL:
        def __init__(self, opts): self.opts = opts
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            cancel.set()
            return {"language": "en", "subtitles": {"en": [{"ext": "vtt"}]}}
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YDL))
    with pytest.raises(core.UserCancelled):
        core.process(URL, tmp_path, tmp_path, {"mode": "transcript"},
                     lambda *args: None, cancel)
    assert not list(tmp_path.rglob("Transcript.txt"))


def test_caption_readers_are_direct_and_no_hosted_url_is_hardcoded():
    src = Path(captions.__file__).read_text(encoding="utf-8")
    assert "yt_dlp.YoutubeDL" in src
    assert "YouTubeTranscriptApi" in src
    assert "http://" not in src and "https://" not in src
