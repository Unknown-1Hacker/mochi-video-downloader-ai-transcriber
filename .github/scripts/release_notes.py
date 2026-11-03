"""Version-specific, minimal GitHub release notes; never edit tags or ZIP files.

For a new release, add its verified change to CHANGES first. The publisher
refuses unrecognized versions instead of recycling stale announcement text.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

REPO = "Unknown-1Hacker/mochi-video-downloader-ai-transcriber"
ROOT = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}"

CHANGES = {
    "v0.1.0": "First public Mochi ZIP with local studio and Windows, macOS and Linux launchers.",
    "v0.2.0": "Added crash-aware job recovery and improved repair/launcher reliability.",
    "v0.2.1": "Refined installation and health checks, with more launcher regression tests.",
    "v0.2.2": "Improved installed-app launch and recovery across repeat runs.",
    "v0.3.0": "Tries existing YouTube captions before downloading audio for local AI.",
    "v0.3.1": "Lighter setup: speech AI dependencies and models are prepared only when needed.",
    "v0.3.2": "Added a second direct YouTube caption reader before the local AI fallback.",
    "v0.3.3": "Simplified the interface: four choices on Home, utilities in the sidebar.",
    "v0.3.4": "Added **Open transcript**, **Copy for AI** and **Open folder** for a finished TXT.",
    "v0.3.5": "Refreshed the README, real interface screenshots and OS installation guide.",
    "v0.3.6": "Introduced **Check for updates** with approval, ZIP verification and rollback safeguards.",
    "v0.3.7": "Removed duplicate top-bar buttons; the same three tools now work in the desktop sidebar and compact mobile row.",
}


def note(tag: str, latest: bool) -> str:
    if tag not in CHANGES or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Unknown release {tag}: add its verified change first")
    if latest:
        return f"""**🐰 One YouTube link. Choose video, audio, subtitles or transcript.**

**⬇️ [Download Mochi.zip]({ROOT}/releases/download/{tag}/Mochi.zip)** · Windows · macOS · Linux
*Use Mochi.zip, not GitHub's automatic Source code downloads.*

**🚀 First time:** Download → Extract → Run **Install-Mochi** for your OS.
**Next time:** Open **Run Mochi Now**.

### ✨ What's new in {tag}
- {CHANGES[tag]}

**🔄 Already installed?** On v0.3.6+, use **Check for updates**. On v0.3.5 or older, install this ZIP once into your existing folder **without deleting the hidden .mochi folder** (it holds your files).

[📖 Quick guide]({ROOT}#readme) · [💜 Help on 1Hack](https://onehack.st/t/mochi-free-youtube-downloader-ai-subtitles-transcript/326924)
"""
    return f"""**{tag} · Earlier release**

- {CHANGES[tag]}

**⬇️ [Get the latest Mochi]({ROOT}/releases/latest)** · Older ZIPs stay available below.
"""


def check() -> None:
    assert len(CHANGES) == 12
    for tag in CHANGES:
        for latest in (False, True):
            body = note(tag, latest)
            assert tag in body and CHANGES[tag] in body
            assert body.count("⬇️") == 1
            assert len(body.splitlines()) <= (16 if latest else 5)
            assert "Meet Mochi" not in body
    try:
        note("v99.0.0", True)
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown releases must not inherit obsolete text")
    print("✅ All 12 version-specific notes validated", file=sys.stderr)


def api(method: str, path: str, data: dict | None = None):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GitHub token missing; releases unchanged")
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        API + path, data=body, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mochi-release-notes",
            **({"Content-Type": "application/json"} if body else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def sync() -> None:
    check()
    latest = api("GET", "/releases/latest")
    releases = api("GET", "/releases?per_page=100")
    if not isinstance(releases, list) or len(releases) > 100:
        raise RuntimeError("Unexpected release list; refused to edit")
    if latest["tag_name"] not in CHANGES:
        raise RuntimeError("Newest release is unknown; add notes first")
    updated = unchanged = 0
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name")
        if tag not in CHANGES:
            print(f"⏭️ Unknown historical release {tag}; skipped")
            continue
        assets = release.get("assets") or []
        if len(assets) != 1 or assets[0].get("name") != "Mochi.zip":
            raise RuntimeError(f"Unexpected ZIP assets on {tag}; refused to edit")
        desired = note(tag, latest=(tag == latest["tag_name"]))
        if release.get("body", "").rstrip() == desired.rstrip():
            unchanged += 1
            continue
        # Critical: change ONLY the Markdown body. Tags, titles and assets survive.
        api("PATCH", f"/releases/{release['id']}", {"body": desired})
        updated += 1
        print(f"✅ Simplified {tag}")
    print(f"Updated {updated} releases; {unchanged} already clean")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check" and len(sys.argv) == 2:
        check()
    elif cmd == "render" and len(sys.argv) == 3:
        sys.stdout.write(note(sys.argv[2], True))
    elif cmd == "sync" and len(sys.argv) == 2:
        sync()
    else:
        raise SystemExit("Usage: release_notes.py check | render vX.Y.Z | sync")
