#!/usr/bin/env python3
"""Capture README images from the real local Mochi UI, never from a mockup.

The completed-job example uses a clearly synthetic TXT file. No YouTube
traffic, accounts, third-party AI, or private user data is involved.
"""
from __future__ import annotations

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


# The setup guide is hand-designed with Mochi's approved bunny mascot.
# Never regenerate docs/mochi-first-time-vs-next-time.webp from placeholder HTML.


def main() -> None:
    with sync_playwright() as play:
        browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            capture_actual_ui(browser)
        finally:
            browser.close()
    for path in sorted(DOCS.glob("*.webp")):
        print(f"✔ {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
