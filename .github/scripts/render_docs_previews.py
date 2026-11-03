#!/usr/bin/env python3
"""Capture README images from the real local Mochi UI, never from a mockup.

The completed-job example uses a clearly synthetic TXT file. No YouTube
traffic, accounts, third-party AI, or private user data is involved.
"""
from __future__ import annotations

import html
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
import studio  # noqa: E402

DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)
SAMPLE = (
    "Welcome to Mochi! This is a sample transcript for the documentation.\n"
    "Choose Transcript to save spoken words as a text file.\n"
    "Mochi checks published YouTube captions before using local AI.\n"
    "When the transcript finishes, choose Open transcript to read it right here.\n"
    "Choose Copy for AI to paste the text into ChatGPT, Claude, or any AI.\n"
    "Choose Open folder to find the original Transcript.txt on your computer.\n"
    "Your text is not sent anywhere automatically.\n"
    "This example uses demonstration text, not an actual YouTube transcript.\n"
)


def save_webp(page, name: str, *, locator: str | None = None) -> None:
    path = DOCS / name
    png = path.with_suffix(".capture.png")
    if locator:
        page.locator(locator).screenshot(path=str(png), animations="disabled")
    else:
        page.screenshot(path=str(png), full_page=True, animations="disabled")
    with Image.open(png) as image:
        image.convert("RGB").save(path, "WEBP", quality=88, method=6)
    png.unlink()
    if path.stat().st_size < 8_000:
        raise RuntimeError(f"Invalid tiny screenshot: {name}")


def capture_actual_ui(browser) -> None:
    studio.ROOT = ROOT
    studio.OUTPUT_DIR = ROOT / ".mochi" / "Downloads"
    studio.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    studio.JOB = studio.JobState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), studio.WebHandler)
    server.daemon_threads = True
    server.secret = "docs-demo-local-session-key-not-for-users"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/?key={server.secret}"
    page = browser.new_page(viewport={"width": 1440, "height": 1000},
                            device_scale_factor=1)
    try:
        page.goto(base, wait_until="networkidle", timeout=30000)
        page.locator(".hero-bunny img").evaluate(
            "(image) => image.decode()"
        )
        assert page.locator("aside.sidebar .side-link").count() == 3
        assert page.locator("label.choice").count() == 4
        assert page.locator("aside.sidebar").inner_text().find("Full video") == -1
        save_webp(page, "mochi-interface.webp")

        page.locator('label.choice:has(input[value="transcript"])').click()
        folder = studio.OUTPUT_DIR / "Mochi sample - demo"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Transcript.txt").write_text(SAMPLE, encoding="utf-8")
        studio.JOB.update(
            "All done! Your files are ready 💜", 100, state="done",
            files=["Transcript.txt"], folder=str(folder)
        )
        page.locator("#open-transcript").wait_for(state="visible", timeout=10000)
        page.locator("#open-transcript").click()
        page.locator("#transcript-preview").wait_for(state="visible", timeout=10000)
        assert "This is a sample transcript" in page.locator("#transcript-text").input_value()
        assert page.locator("#copy-transcript").is_visible()
        assert page.locator("#open-folder").is_visible()
        save_webp(page, "mochi-transcript-result.webp", locator="#activity")
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def guide_html() -> str:
    src = (ROOT / "app" / "install_layout.py").read_text(encoding="utf-8")
    first = [
        ("Windows", "🪟", "Install-Mochi-Windows.cmd", "Run Mochi Now.lnk"),
        ("macOS", "🍎", "Install-Mochi-Mac.command", "Run Mochi Now.app"),
        ("Linux", "🐧", "Install-Mochi-Linux.sh", "Run Mochi Now.desktop"),
    ]
    for _os, _icon, install, next_time in first:
        assert (ROOT / install).is_file(), install
        assert next_time in src, next_time
    cards = []
    for platform, icon, installer, launcher in first:
        cards.append(f"""
        <article>
          <header><span class="os-icon">{icon}</span><h2>{platform}</h2></header>
          <div class="step"><span class="num">1</span><div>
             <div class="eyebrow">FIRST TIME · INSTALL</div>
             <div class="filename">{html.escape(installer)}</div>
             <p>Run once to set up Mochi.</p></div></div>
          <div class="step"><span class="num">2</span><div>
             <div class="eyebrow">NEXT TIME · OPEN</div>
             <div class="filename">{html.escape(launcher)}</div>
             <p>Use for everyday launching.</p></div></div>
        </article>""")
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
    <style>
      *{box-sizing:border-box}body{margin:0;background:#f7f5fe;color:#241a4b;
      font-family:Arial,Helvetica,sans-serif}main{padding:54px 58px 40px}
      .headline{display:flex;align-items:center;justify-content:space-between;gap:36px}
      .bunny{font-size:64px}.heading{flex:1}.heading h1{font-size:48px;margin:0 0 10px;
      letter-spacing:-1.5px}.heading p{font-size:20px;color:#72658c;margin:0}
      .chip{background:#e7dffc;color:#6950b5;padding:12px 20px;border-radius:99px;
      font-size:16px;font-weight:800}.cards{display:grid;grid-template-columns:repeat(3,1fr);
      gap:22px;margin:40px 0 28px}article{background:white;border:1px solid #e3dcf2;
      border-radius:24px;overflow:hidden;box-shadow:0 10px 30px #4d308812}
      article header{padding:24px 28px;background:#eae3fa;display:flex;gap:12px;align-items:center}
      article h2{font-size:27px;margin:0}.os-icon{font-size:29px}.step{display:flex;gap:17px;
      align-items:start;padding:28px 24px 20px;min-height:163px}
      .step+.step{border-top:1px solid #eee9f6}.num{width:35px;height:35px;flex:0 0 35px;
      display:grid;place-items:center;background:#8c6eeb;color:white;border-radius:50%;font-weight:900}
      .eyebrow{font-size:12px;font-weight:900;letter-spacing:1.1px;color:#7960b5;margin:0 0 10px}
      .filename{font-size:18px;font-weight:800;line-height:1.35;overflow-wrap:anywhere}
      .step p{font-size:15px;color:#766d8e;margin:9px 0 0}
      footer{display:flex;align-items:center;justify-content:center;gap:16px;
      font-size:18px;padding:26px 22px;background:#eae4fa;border-radius:20px}
      footer strong{color:#5e42b2}footer .divider{color:#aaa0bf}
    </style></head><body><main><div class="headline"><span class="bunny">🐰</span>
      <div class="heading"><h1>Mochi — first time vs next time</h1>
      <p>Same idea on every computer: install once, then open normally.</p></div>
      <span class="chip">2 simple steps ✨</span></div>
      <div class="cards">""" + "\n".join(cards) + """</div>
      <footer>💜 <strong>Keep the hidden .mochi folder</strong>
      <span class="divider">·</span> It stores your tools and saved downloads
      <span class="divider">·</span> 🐧 Linux: allow launching if prompted</footer>
    </main></body></html>"""


def capture_setup_guide(browser) -> None:
    page = browser.new_page(viewport={"width": 1600, "height": 760},
                            device_scale_factor=1)
    try:
        page.set_content(guide_html(), wait_until="load")
        assert page.locator("article").count() == 3
        save_webp(page, "mochi-first-time-vs-next-time.webp")
    finally:
        page.close()


def main() -> None:
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            capture_actual_ui(browser)
            capture_setup_guide(browser)
        finally:
            browser.close()
    for path in sorted(DOCS.glob("*.webp")):
        print(f"✔ {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
