"""First-run launcher smoke tests: actual shell execution, no network."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "Linux": "Install-Mochi-Linux.sh",
    "Mac": "Install-Mochi-Mac.command",
    "Windows": "Install-Mochi-Windows.cmd",
}


def test_launchers_have_unambiguous_shell_safe_names():
    for name in FILES.values():
        assert re.fullmatch(r"[A-Za-z0-9.-]+", name)
        assert (ROOT / name).is_file()
    assert not list(ROOT.glob("1 INSTALL & OPEN*"))


@pytest.mark.skipif(os.name == 'nt', reason='POSIX shell launcher')
@pytest.mark.parametrize("system", ["Linux", "Mac"])
def test_native_shell_launcher_works_from_complex_extracted_path(tmp_path, system):
    folder = tmp_path / "folder with spaces & symbols" / "Mochi"
    folder.mkdir(parents=True)
    launcher = folder / FILES[system]
    shutil.copy2(ROOT / launcher.name, launcher)
    launcher.chmod(0o755)
    app = folder / "app"
    app.mkdir()
    (app / "bootstrap.sh").write_text(
        '#!/bin/sh\nprintf ready > "$MOCHI_LAUNCH_MARKER"\n',
        encoding="utf-8",
    )
    marker = tmp_path / "started"
    env = os.environ.copy()
    env["MOCHI_LAUNCH_MARKER"] = str(marker)
    # Terminal app gets an unquoted *basename*: no spaces, &, or parsing issues.
    run = subprocess.run(["/bin/sh", "-c", "./" + launcher.name],
                         cwd=folder, env=env, capture_output=True,
                         text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert marker.read_text(encoding="utf-8") == "ready"


@pytest.mark.skipif(os.name != 'nt', reason='Windows native cmd launcher')
def test_windows_cmd_launcher_works_from_complex_extracted_path(tmp_path):
    folder = tmp_path / "folder with spaces & symbols" / "Mochi"
    folder.mkdir(parents=True)
    launcher = folder / FILES["Windows"]
    shutil.copy2(ROOT / launcher.name, launcher)
    app = folder / "app"
    app.mkdir()
    (app / "bootstrap.ps1").write_text(
        "Set-Content -LiteralPath $env:MOCHI_LAUNCH_MARKER -Value 'ready' -Encoding UTF8\n",
        encoding="ascii",
    )
    marker = tmp_path / "started"
    env = os.environ.copy()
    env["MOCHI_LAUNCH_MARKER"] = str(marker)
    run = subprocess.run(["cmd.exe", "/d", "/c", launcher.name],
                         cwd=folder, env=env, capture_output=True,
                         text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert marker.read_text(encoding="utf-8-sig").strip() == "ready"
