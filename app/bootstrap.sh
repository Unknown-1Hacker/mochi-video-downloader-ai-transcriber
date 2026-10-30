#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$HERE" in */.mochi/app) ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd) ;; *) ROOT=$(CDPATH= cd -- "$HERE/.." && pwd) ;; esac
STATE="$ROOT/.mochi"
TOOLS="$STATE/tools"
UV="$TOOLS/uv"
PY="$STATE/venv/bin/python"
mkdir -p "$TOOLS"
export UV_INSTALL_DIR="$TOOLS" UV_NO_MODIFY_PATH=1 UV_PYTHON_INSTALL_DIR="$STATE/python" UV_CACHE_DIR="$STATE/cache"
printf '\n  ✦ Mochi is taking care of setup ✦\n\n'
if [ ! -x "$UV" ]; then
  if command -v uv >/dev/null 2>&1; then UV=$(command -v uv)
  else
    printf '[1/5] Getting setup helper…\n'
    if command -v curl >/dev/null 2>&1; then
      curl --fail --location --silent --show-error --retry 3 'https://astral.sh/uv/install.sh' -o "$STATE/uv-install.sh"
    elif command -v wget >/dev/null 2>&1; then
      wget -qO "$STATE/uv-install.sh" 'https://astral.sh/uv/install.sh'
    else echo 'Connect to the internet and install curl or wget, then retry.' >&2;exit 1;fi
    sh "$STATE/uv-install.sh"
    rm -f "$STATE/uv-install.sh"
  fi
fi
[ -x "$UV" ] || { echo 'Could not prepare setup helper.' >&2; exit 1; }
printf '[2/5] Preparing private Python…\n'
"$UV" venv --python 3.12 "$STATE/venv"
printf '[3/5] Preparing video and AI tools…\n'
REQ="$HERE/requirements.lock"
[ -f "$REQ" ] || REQ="$HERE/requirements.txt"
"$UV" pip install --python "$PY" -r "$REQ"
printf '[4/5] Preparing media tools…\n'
"$PY" "$HERE/setup_ffmpeg.py"
if [ ! -x "$STATE/deno/bin/deno" ] && ! command -v deno >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --retry 3 https://deno.land/install.sh -o "$STATE/deno-install.sh"
  else wget -qO "$STATE/deno-install.sh" https://deno.land/install.sh;fi
  DENO_INSTALL="$STATE/deno" sh "$STATE/deno-install.sh"
  rm -f "$STATE/deno-install.sh"
fi
printf '[5/5] Organizing Mochi and opening it…\n'
if [ -d "$ROOT/app" ]; then
  "$PY" "$HERE/install_layout.py" prepare
fi
export PATH="$STATE/deno/bin:$PATH"
if "$PY" "$STATE/app/launcher.py"; then
  "$PY" "$STATE/app/install_layout.py" finish
  printf '\n ✨ All done! Next time, double-click Run Mochi Now.\n'
else
  "$PY" "$HERE/install_layout.py" rollback 2>/dev/null || true
  echo 'Could not open Mochi. Setup files are kept for repair.' >&2
  exit 1
fi
