from pathlib import Path
from core import ensure_ffmpeg
from mochi_paths import root_dir
print('Preparing built-in FFmpeg…')
print(ensure_ffmpeg(root_dir(__file__)))
