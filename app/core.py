"""Mochi video operations. Native downloads; speech products always from audio."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tempfile
from pathlib import Path
from mochi_paths import root_dir
from urllib.parse import urlsplit, parse_qs


class FriendlyError(Exception):
    pass


class UserCancelled(Exception):
    pass


def check_url(url: str) -> str:
    if not isinstance(url, str):
        raise FriendlyError('Please paste a normal YouTube video link.')
    url = url.strip()
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
    except (ValueError, TypeError):
        raise FriendlyError('That link looks incomplete. Paste a YouTube video link.')
    allowed = host == 'youtu.be' or host == 'youtube.com' or host.endswith('.youtube.com') or host == 'youtube-nocookie.com' or host.endswith('.youtube-nocookie.com')
    if parsed.scheme not in ('https', 'http') or not allowed or parsed.username or parsed.password:
        raise FriendlyError('Please paste a normal YouTube or youtu.be video link.')
    if parsed.path.rstrip('/') in ('/playlist', '/channel', '/@') or (parsed.path in ('/', '') and 'v' not in parse_qs(parsed.query)):
        raise FriendlyError('Please paste a link to one video, not a playlist or channel.')
    if len(url) > 2048:
        raise FriendlyError('That video link is unusually long. Please paste a normal YouTube link.')
    return url


def slug(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '', s if isinstance(s, str) and s else 'YouTube video').strip().strip('.')
    s = re.sub(r'\s+', ' ', s)
    return s[:90] or 'YouTube video'


def video_key(url: str) -> str:
    return hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]


def stamp(seconds: float, vtt=False) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}{"." if vtt else ","}{ms:03d}'


def ffmpeg_folder(root: Path) -> Path:
    return root / '.mochi' / 'ffmpeg'


def ensure_ffmpeg(root: Path) -> str:
    """Prepare both ffmpeg and ffprobe beside the app, without admin access."""
    target_dir = ffmpeg_folder(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    exe = '.exe' if os.name == 'nt' else ''
    ffmpeg = target_dir / ('ffmpeg' + exe)
    ffprobe = target_dir / ('ffprobe' + exe)
    if ffmpeg.is_file() and ffprobe.is_file() and ffmpeg.stat().st_size and ffprobe.stat().st_size:
        try:
            if all(subprocess.run([str(tool), '-version'], capture_output=True, timeout=8, check=False).returncode == 0
                   for tool in (ffmpeg, ffprobe)):
                return str(target_dir)
        except (OSError, subprocess.TimeoutExpired):
            pass
        # Broken tool files are regenerated below, without touching user downloads.
        ffmpeg.unlink(missing_ok=True)
        ffprobe.unlink(missing_ok=True)
    # Prefer healthy system media tools before fetching a new binary.
    native_ffmpeg, native_probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    sources = (native_ffmpeg, native_probe) if native_ffmpeg and native_probe else None
    try:
        if not sources:
            from static_ffmpeg import run
            sources = run.get_or_fetch_platform_executables_else_raise()
    except Exception:
        # Fall back to bundled imageio FFmpeg plus an already-installed ffprobe.
        try:
            import imageio_ffmpeg
            probe = shutil.which('ffprobe')
            if probe:
                sources = (imageio_ffmpeg.get_ffmpeg_exe(), probe)
        except Exception:
            pass
    if not sources:
        raise FriendlyError('Could not prepare FFmpeg and FFprobe. Check internet, then click Fix my tools or double-click Run Mochi Now again.')
    try:
        for source, target in zip(sources, (ffmpeg, ffprobe)):
            if Path(source).resolve() != target.resolve():
                shutil.copy2(source, target)
            if os.name != 'nt':
                target.chmod(target.stat().st_mode | 0o111)
            result = subprocess.run([str(target), '-version'], capture_output=True, timeout=15, check=False)
            if result.returncode != 0:
                raise FriendlyError(f'Could not run {target.name}. Please rerun setup.')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FriendlyError(f'FFmpeg setup failed: {exc}') from exc
    return str(target_dir)


def common_ydl(root: Path) -> dict:
    return {
        'noplaylist': True,
        'ignoreerrors': False,
        'retries': 8,
        'fragment_retries': 8,
        'extractor_retries': 3,
        'socket_timeout': 25,
        'concurrent_fragment_downloads': 6,
        'continuedl': True,
        'ffmpeg_location': ensure_ffmpeg(root),
        'quiet': True,
        'no_warnings': True,
    }


def info_for(url: str, root: Path) -> dict:
    import yt_dlp
    opts = common_ydl(root)
    opts['skip_download'] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(url, download=False)
    if not data:
        raise FriendlyError('YouTube did not return this video. Check the URL or try again.')
    return data


def choices(info: dict) -> list[int]:
    heights = set()
    for f in info.get('formats') or []:
        h = f.get('height')
        if isinstance(h, (int, float)) and h >= 144 and f.get('vcodec') not in ('none', None) and f.get('protocol') != 'mhtml':
            heights.add(int(h))
    return sorted(heights, reverse=True)


def _checkpoint(cancel):
    if cancel.is_set():
        raise UserCancelled('Cancelled.')


def _progress_hook(update, cancel):
    def hook(d):
        _checkpoint(cancel)
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            pct = min(95, round(d.get('downloaded_bytes', 0) / total * 95)) if total else None
            speed = d.get('speed')
            detail = (f' · {speed / 1024 / 1024:.1f} MB/s' if isinstance(speed, (float, int)) else '')
            update('Downloading the video/audio…' + detail, pct)
        elif d.get('status') == 'finished':
            update('Download complete. Finishing up…', 96)
    return hook


def _formats(mode: str, height: int | None) -> str:
    if mode == 'video':
        return f'bv*[height<={height}]+ba/b[height<={height}]' if height else 'bv*+ba/b'
    return 'bestaudio/best'


def _download(url: str, root: Path, destination: Path, mode: str, height: int | None, audio_mp3: bool, update, cancel) -> Path:
    import yt_dlp
    destination.mkdir(parents=True, exist_ok=True)
    opts = common_ydl(root)
    opts.update({
        'format': _formats(mode, height),
        'outtmpl': str(destination / '%(title).90B [%(id)s].%(ext)s'),
        'progress_hooks': [_progress_hook(update, cancel)],
        'overwrites': False,
        'writethumbnail': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
    })
    if mode == 'video':
        opts['merge_output_format'] = 'mp4/mkv'
    if audio_mp3:
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
    _checkpoint(cancel)
    update('Connecting to YouTube…', 2)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url, download=True)
            if not result:
                raise FriendlyError('The video was unavailable. Please check the link.')
    except Exception:
        _checkpoint(cancel)
        raise
    _checkpoint(cancel)
    media = sorted((p for p in destination.iterdir() if p.is_file() and p.suffix.lower() not in ('.part', '.ytdl', '.temp', '.json', '.txt', '.vtt', '.srt')),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not media or not media[0].stat().st_size:
        raise FriendlyError('Download ended, but no completed media file was found. Please retry.')
    return media[0]


def _valid_cached_audio(root: Path, path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 4096:
        return False
    ffmpeg = ffmpeg_folder(root) / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    try:
        result = subprocess.run(
            [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-i', str(path),
             '-t', '0.3', '-map', '0:a:0', '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _get_audio(url: str, root: Path, output_root: Path, update, cancel) -> Path:
    cached = output_root / '.mochi' / 'audio-cache' / video_key(url)
    if cached.exists():
        for p in cached.glob('*.?*'):
            if p.is_file() and p.suffix not in ('.part', '.ytdl', '.temp'):
                if _valid_cached_audio(root, p):
                    update('Reusing saved audio (no re-download).', 65)
                    return p
                p.unlink(missing_ok=True)
    def audio_update(message, percent=None):
        update(message, min(65, round(percent * .65)) if percent is not None else None)
    return _download(url, root, cached, 'audio', None, False, audio_update, cancel)


def _whisper_engine(quality: str, update, cancel):
    from faster_whisper import WhisperModel
    model_folder = root_dir(__file__) / '.mochi' / 'models'
    model_folder.mkdir(parents=True, exist_ok=True)
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda = False
    if quality == 'accurate':
        preferred = ('large-v3', 'medium')
    else:
        preferred = ('small', 'small')
    model = preferred[0] if cuda else preferred[1]
    if cuda:
        try:
            update('Loading AI on your GPU (first run downloads the model)…', 67)
            _checkpoint(cancel)
            return WhisperModel(model, device='cuda', compute_type='float16', download_root=str(model_folder)), model, 'cuda'
        except (RuntimeError, OSError, ValueError) as e:
            update('GPU unavailable; using reliable CPU mode instead…', 67)
    _checkpoint(cancel)
    update('Loading local AI (first run downloads the model)…', 67)
    return WhisperModel(preferred[1], device='cpu', compute_type='int8', download_root=str(model_folder)), preferred[1], 'cpu'


def _pyav_signature_error(error: BaseException) -> bool:
    """Upstream faster-whisper 1.2.1 / PyAV 19 API mismatch, NOT bad audio."""
    message = str(error).lower()
    return (isinstance(error, TypeError) and 'metadata_errors' in message
            and ('unexpected keyword' in message or 'invalid keyword' in message))


def _decode_with_ffmpeg(media: Path, out: Path, update, cancel):
    """Compatibility fallback: use existing FFmpeg, never edit packages or user files.

    Stream float32 PCM to a temporary file, then mmap it, so a long video does
    not require holding the entire decompressed audio in RAM.
    """
    import numpy as np
    root = root_dir(__file__)
    ffmpeg = ffmpeg_folder(root) / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    if not ffmpeg.is_file():
        ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise FriendlyError('Audio decoder needs repair. Click Fix my tools or double-click Run Mochi Now again.')
    temporary_dir = Path(tempfile.mkdtemp(prefix='.decoder-', dir=out))
    raw = temporary_dir / 'audio.f32'
    command = [str(ffmpeg), '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-i', str(media), '-vn', '-map', '0:a:0', '-ar', '16000',
               '-ac', '1', '-c:a', 'pcm_f32le', '-f', 'f32le', '-y', str(raw)]
    update('Fixing audio compatibility automatically…', 69)
    proc = None
    try:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)
        deadline = time.monotonic() + 60 * 60 * 4
        while proc.poll() is None:
            if cancel.is_set():
                proc.kill()
                proc.communicate()
                raise UserCancelled('Cancelled.')
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise FriendlyError('Audio decoding exceeded the safety time limit.')
            time.sleep(0.15)
        stderr = proc.communicate()[1]
        if proc.returncode != 0 or not raw.is_file() or raw.stat().st_size < 4:
            detail = stderr.decode('utf-8', errors='replace').strip()[-180:]
            raise FriendlyError(f'Cannot decode this audio. {detail or "Try another video."}')
        result = np.memmap(raw, dtype=np.float32, mode='r')
        return result, temporary_dir
    except BaseException:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def recognize(media: Path, out: Path, quality: str, language: str | None, subtitle: bool, update, cancel) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    model, model_name, device = _whisper_engine(quality, update, cancel)
    args = {'beam_size': 5 if quality == 'accurate' else 3,
            'vad_filter': True, 'condition_on_previous_text': False, 'language': language}
    source = str(media)
    decoded_dir = None
    repaired_decoder = False
    tried_cpu = device == 'cpu'
    try:
        # Maximum 3 passes: standard, PyAV decode repair, CUDA -> CPU repair.
        # Never repeat an identical attempt or hide unexpected exceptions.
        for attempt in range(3):
            _checkpoint(cancel)
            rows = []
            try:
                segments, info = model.transcribe(source, **args)
                update(f'Listening to audio · {model_name} · {device}…', 70)
                for segment in segments:  # Lazy generator: exceptions can occur HERE too.
                    _checkpoint(cancel)
                    text = str(segment.text).strip()
                    if text and segment.end > segment.start:
                        rows.append((float(segment.start), float(segment.end), text))
                        if len(rows) % 50 == 0:
                            duration = max(1.0, float(getattr(info, 'duration', 0) or 1))
                            update(f'Listening… {len(rows)} speech parts recognized',
                                   min(96, 70 + round(float(segment.end) / duration * 26)))
                if repaired_decoder:
                    from doctor import remember_fix
                    remember_fix(root_dir(__file__), 'audio_decoder', 'ffmpeg_fallback', True)
                break
            except TypeError as error:
                if not _pyav_signature_error(error) or repaired_decoder:
                    raise
                _checkpoint(cancel)
                source, decoded_dir = _decode_with_ffmpeg(media, out, update, cancel)
                repaired_decoder = True
            except (RuntimeError, OSError, ValueError) as error:
                if tried_cpu:
                    raise
                tried_cpu = True
                update('GPU had a hiccup. Switching safely to CPU…', 67)
                _checkpoint(cancel)
                from faster_whisper import WhisperModel
                cpu_model = 'medium' if quality == 'accurate' else 'small'
                model = WhisperModel(cpu_model, device='cpu', compute_type='int8',
                                     download_root=str(root_dir(__file__) / '.mochi' / 'models'))
                model_name, device = cpu_model, 'cpu'
        else:
            raise FriendlyError('Automatic recovery exhausted. Use Fix my tools below.')
        update('Preparing your finished files…', 97)
        if not rows:
            raise FriendlyError('No clear speech was detected. Try a different video or clearer audio.')
        _checkpoint(cancel)
        formats = ['srt', 'vtt'] if subtitle else ['txt']
        if subtitle:
            contents = {
                'srt': ''.join(f'{i}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n' for i, (start, end, text) in enumerate(rows, 1)),
                'vtt': 'WEBVTT\n\n' + ''.join(f'{stamp(start, True)} --> {stamp(end, True)}\n{text}\n\n' for start, end, text in rows),
            }
        else:
            contents = {'txt': '\n'.join(text for _, _, text in rows) + '\n'}
        stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=out))
        try:
            for ext in formats:
                (stage / f'speech.{ext}').write_text(contents[ext], encoding='utf-8')
            _checkpoint(cancel)
            saved = []
            for ext in formats:
                target = out / ('Subtitles.' + ext if subtitle else 'Transcript.txt')
                os.replace(stage / f'speech.{ext}', target)
                saved.append(target)
            return saved
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    finally:
        # memmap must release its backing file before Windows allows deletion.
        if decoded_dir is not None:
            if not isinstance(source, str):
                # Windows cannot delete the PCM temp file until numpy releases its mmap.
                mapped = getattr(source, '_mmap', None)
                if mapped is not None:
                    mapped.close()
                del source
            shutil.rmtree(decoded_dir, ignore_errors=True)


def process(url: str, root: Path, output_root: Path, options: dict, update, cancel) -> list[Path]:
    url = check_url(url)
    mode = options.get('mode', 'video')
    if mode not in ('video', 'audio', 'subtitles', 'transcript'):
        raise FriendlyError('Choose video, audio, subtitles, or transcript.')
    quality = options.get('speech_quality', 'balanced')
    if quality not in ('balanced', 'accurate'):
        raise FriendlyError('Choose Balanced or Careful accuracy.')
    height = options.get('height')
    if height not in (None, 'best'):
        if not isinstance(height, int) or not 144 <= height <= 8640:
            raise FriendlyError('That video quality is not available.')
    else:
        height = None
    language = options.get('language', 'auto')
    if language not in ('auto', 'en', 'hi', 'ta', 'es', 'fr', 'de', 'ar', 'ja'):
        raise FriendlyError('Choose a supported language or Automatic.')
    language = None if language == 'auto' else language
    audio_mp3 = options.get('audio_format', 'original') == 'mp3'
    if options.get('audio_format', 'original') not in ('original', 'mp3'):
        raise FriendlyError('Choose Original quality or MP3.')
    job_dir = output_root / (slug(options.get('title') or 'My video') + ' [' + video_key(url) + ']')
    job_dir.mkdir(parents=True, exist_ok=True)
    if mode in ('subtitles', 'transcript'):
        expected = [job_dir / 'Subtitles.srt', job_dir / 'Subtitles.vtt'] if mode == 'subtitles' else [job_dir / 'Transcript.txt']
        manifest = job_dir / ('.mochi-' + mode + '.json')
        cfg = {'url': url, 'mode': mode, 'quality': quality, 'language': language, 'version': 1}
        try:
            previous = json.loads(manifest.read_text(encoding='utf-8'))
            if previous.get('config') == cfg and all(p.is_file() and p.stat().st_size and hashlib.sha256(p.read_bytes()).hexdigest() == previous['hashes'][p.name] for p in expected):
                update('Already done! Reusing verified finished files.', 100)
                return expected
        except (OSError, ValueError, TypeError, KeyError):
            pass
    if mode in ('video', 'audio'):
        profile = f'Video - {height or "Best"}p' if mode == 'video' and height else ('Video - Best' if mode == 'video' else ('Audio - MP3' if audio_mp3 else 'Audio - Original'))
        return [_download(url, root, job_dir / profile, mode, height, audio_mp3, update, cancel)]
    media = _get_audio(url, root, output_root, update, cancel)
    results = recognize(media, job_dir, quality, language, mode == 'subtitles', update, cancel)
    cfg = {'url': url, 'mode': mode, 'quality': quality, 'language': language, 'version': 1}
    manifest = job_dir / ('.mochi-' + mode + '.json')
    meta = {'config': cfg, 'hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in results}}
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=job_dir, delete=False) as fd:
        tmpname = Path(fd.name)
        json.dump(meta, fd)
    os.replace(tmpname, manifest)
    return results
