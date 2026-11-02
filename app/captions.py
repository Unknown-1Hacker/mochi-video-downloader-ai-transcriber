"""Fast, caption-first speech files. No third-party transcript-site scraping.

Public YouTube caption tracks are tried once; unavailable, broken, or malformed
tracks return None so Mochi can use its existing local speech recognition.
"""
from __future__ import annotations

import html
import os
import re
import tempfile
from pathlib import Path

_CLOCK = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})$")
_TAG = re.compile(r"<[^>]*>")


def _seconds(value: str):
    match = _CLOCK.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _rows(vtt: str):
    """Accept valid WebVTT cues, rejecting empty and malformed responses."""
    rows = []
    # Note/Style blocks without timestamp lines are naturally ignored.
    for block in re.split(r"\r?\n\s*\r?\n", vtt.replace("\ufeff", "")):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            if "-->" not in line:
                continue
            a, b = line.split("-->", 1)
            start = _seconds(a)
            end = _seconds(b.split(None, 1)[0])
            if start is None or end is None or end <= start:
                continue
            parts = []
            for raw in lines[i + 1:]:
                plain = html.unescape(_TAG.sub("", raw)).strip()
                if plain:
                    parts.append(plain)
            text = " ".join(parts).strip()
            if text and (not rows or rows[-1][2] != text):
                rows.append((start, end, text))
            break
    return rows


def _language(info, requested):
    """Use actual published tracks, not guessed or translated languages."""
    authored = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    if not isinstance(authored, dict) or not isinstance(automatic, dict):
        return None
    def has_vtt(tracks):
        return isinstance(tracks, list) and any(
            isinstance(track, dict) and track.get("ext") == "vtt" for track in tracks
        )
    native = str(info.get("language") or "").strip()
    preferred = [requested] if requested else [native, "en"]
    for requested_lang in preferred:
        if not requested_lang:
            continue
        for bucket, is_auto in ((authored, False), (automatic, True)):
            for code, tracks in bucket.items():
                if (code == requested_lang or
                    (code.startswith(requested_lang + "-") and not requested)) and has_vtt(tracks):
                    return code, is_auto
    if requested:
        return None  # Never quietly serve the wrong language.
    for bucket, is_auto in ((authored, False), (automatic, True)):
        for code, tracks in bucket.items():
            # yt-dlp offers machine-translated tracks in many languages. When
            # the native code is known, avoid unintentionally selecting those.
            if has_vtt(tracks) and (not native or code == native or code.startswith(native + "-")):
                return code, is_auto
    return None


def _save_rows(rows, out: Path, subtitle: bool, cancel):
    """Publish timed captions or text through the same atomic staging path."""
    from core import stamp
    contents = (
        {"Subtitles.srt": "".join(
            f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n"
            for i, (start, end, text) in enumerate(rows, 1)),
         "Subtitles.vtt": "WEBVTT\n\n" + "".join(
             f"{stamp(start, True)} --> {stamp(end, True)}\n{text}\n\n"
             for start, end, text in rows)}
        if subtitle else
        {"Transcript.txt": "\n".join(text for _, _, text in rows) + "\n"}
    )
    with tempfile.TemporaryDirectory(prefix=".captions-out-", dir=out) as folder:
        stage = Path(folder)
        for name, body in contents.items():
            (stage / name).write_text(body, encoding="utf-8")
        if cancel.is_set():
            return None
        saved = []
        for name in contents:
            target = out / name
            os.replace(stage / name, target)
            saved.append(target)
    return saved


def try_captions(url, root: Path, out: Path, language, subtitle: bool, update, cancel):
    """Return SRT/VTT or TXT paths, or None to use original-audio local AI.

    Attempts one caption language with bounded yt-dlp retries, no outside
    transcript services, no login, and no changes to saved media on failure.
    """
    if cancel.is_set():
        return None
    try:
        import yt_dlp
        # Caption retrieval does not require FFmpeg or an AI model download.
        opts = {"noplaylist": True, "skip_download": True, "quiet": True,
                "no_warnings": True, "retries": 1, "extractor_retries": 1,
                "socket_timeout": 12}
        update("Checking for instant captions…", 8)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict) or cancel.is_set():
            return None
        picked = _language(info, language)
        if picked is None:
            return None
        code, is_auto = picked
        with tempfile.TemporaryDirectory(prefix=".captions-", dir=out) as folder:
            opts.update({"subtitleslangs": [code], "subtitlesformat": "vtt",
                         "writesubtitles": not is_auto,
                         "writeautomaticsub": is_auto,
                         "outtmpl": str(Path(folder) / "speech.%(ext)s"),
                         "overwrites": True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            if cancel.is_set():
                return None
            files = list(Path(folder).glob("speech.*.vtt"))
            if len(files) != 1 or files[0].stat().st_size > 8 * 1024 * 1024:
                return None
            rows = _rows(files[0].read_text(encoding="utf-8", errors="replace"))
        if not rows or cancel.is_set():
            return None

        saved = _save_rows(rows, out, subtitle, cancel)
        if saved is None:
            return None
        update("Instant captions saved! No AI model needed.", 98)
        return saved
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError):
        return None
    except Exception:
        # yt-dlp raises its own extractor/download subclasses.
        # This is a best-effort fast path; local AI remains authoritative fallback.
        return None


def _video_id(url: str):
    """Accept only one standard YouTube video ID (no arbitrary remote URLs)."""
    from urllib.parse import parse_qs, urlsplit
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in ("https", "http") or parsed.username or parsed.password:
            return None
        if host == "youtu.be":
            candidate = parsed.path.strip("/")
        elif host in ("youtube.com", "youtube-nocookie.com") or host.endswith((".youtube.com", ".youtube-nocookie.com")):
            parts = parsed.path.strip("/").split("/")
            if parts[0] == "watch":
                candidate = (parse_qs(parsed.query).get("v") or [""])[0]
            elif len(parts) == 2 and parts[0] in ("shorts", "live", "embed", "v"):
                candidate = parts[1]
            else:
                return None
        else:
            return None
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None
    except (ValueError, TypeError, AttributeError):
        return None


def try_alternative_captions(url, out: Path, language, subtitle: bool, update, cancel):
    """Second independent YouTube caption method; local audio AI remains last.

    Uses the maintained youtube-transcript-api library, not scraping hosted
    transcript sites or attempting to bypass their usage restrictions.
    """
    if cancel.is_set():
        return None
    video_id = _video_id(url)
    if not video_id:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        update("Trying another quick caption method…", 9)
        transcripts = list(YouTubeTranscriptApi().list(video_id))
        if cancel.is_set():
            return None
        if language:
            preferred = [t for t in transcripts if
                         str(t.language_code).lower() == language or
                         str(t.language_code).lower().startswith(language + "-")]
        else:
            english = [t for t in transcripts if
                       str(t.language_code).lower() == "en" or
                       str(t.language_code).lower().startswith("en-")]
            preferred = english or transcripts
        if not preferred:
            return None
        # Prefer creator-written subtitles over auto captions within the language.
        chosen = sorted(preferred, key=lambda t: bool(t.is_generated))[0]
        fetched = chosen.fetch()
        if cancel.is_set():
            return None
        rows = []
        text_size = 0
        import math
        for snippet in fetched:
            if cancel.is_set():
                return None
            try:
                start, duration = float(snippet.start), float(snippet.duration)
                if not (math.isfinite(start) and math.isfinite(duration) and
                        start >= 0 and duration > 0 and math.isfinite(start + duration)):
                    continue
                text = " ".join(html.unescape(_TAG.sub("", snippet.text)).split())
                if not text:
                    continue
                text_size += len(text.encode("utf-8"))
                if text_size > 8 * 1024 * 1024 or len(rows) >= 50000:
                    return None
                rows.append((start, start + duration, text))
            except (TypeError, ValueError, AttributeError):
                continue
        if not rows or cancel.is_set():
            return None
        saved = _save_rows(rows, out, subtitle, cancel)
        if saved is not None:
            update("Quick captions saved! No AI model needed.", 98)
        return saved
    except Exception:
        # Providers, network and caption availability can change; never let a
        # failed caption lookup prevent original-audio transcription.
        return None
