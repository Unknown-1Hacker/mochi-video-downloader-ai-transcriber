<p align="center">
  <img src="app/assets/mochi.png" width="82" alt="Mochi bunny icon" />
</p>

<h1 align="center">Mochi</h1>
<p align="center"><strong>Video Downloader &amp; AI Transcriber</strong></p>
<p align="center">One YouTube link. Your choice. Done. ✨</p>

<p align="center">
  <a href="https://github.com/Unknown-1Hacker/mochi-video-downloader-ai-transcriber/releases/latest/download/Mochi.zip"><strong>⬇️ Download Mochi.zip</strong></a>
  &nbsp; · &nbsp;
  <a href="https://github.com/Unknown-1Hacker/mochi-video-downloader-ai-transcriber/releases/latest">View latest release</a>
</p>
<p align="center"><sub>Free · Windows · macOS · Linux · Local AI · No account</sub></p>

<p align="center">
  <img src="docs/mochi-interface.webp" width="940" alt="Mochi's real purple interface with a bunny above the video link box and four simple download choices" />
</p>

### 🎁 What can Mochi do?

| Pick | What you get |
|:--|:--|
| 🎬 **Full video** | Video + audio, at your chosen available quality |
| 🎧 **Audio only** | Original audio or MP3 |
| 💬 **Subtitles** | AI-generated SRT + VTT with timestamps |
| 📝 **Transcript** | Spoken words in a TXT file |

### 🧭 How Mochi works

<p align="center">
  <strong>🖱️ Open Mochi</strong><br/>
  <sub>Checks its tools and prepares what's missing</sub><br/><br/>
  ⬇️<br/><br/>
  <strong>🔗 Paste a YouTube link → 🎯 Pick what you want</strong><br/>
  <sub>Best available quality by default, or choose your own</sub><br/><br/>
  ⬇️
</p>

| 🎬 Video / 🎧 Audio | 💬 Subtitles / 📝 Transcript |
|:---:|:---:|
| **📥 [yt-dlp](https://github.com/yt-dlp/yt-dlp)** | **📥 yt-dlp → 🧠 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)** |
| Downloads your selected media and quality | Downloads the original audio, then listens to the speech locally—not existing captions |
| **💾 Video or audio file** | **💾 SRT + VTT subtitles or TXT text** |

<p align="center">
  <strong>✅ Saved on your computer</strong><br/>
  <sub>⚡ Smart defaults · ♻️ Reuses completed work · 🛠️ Repairs known issues · 🧹 Keeps things tidy</sub>
</p>

### 🚀 Three steps. That's it.

1. **[Download Mochi.zip](https://github.com/Unknown-1Hacker/mochi-video-downloader-ai-transcriber/releases/latest/download/Mochi.zip)** and extract it.
2. **Open `Install-Mochi-Windows.cmd`, `Install-Mochi-Mac.command`, or `Install-Mochi-Linux.sh`** for your OS. Mochi prepares its tools.
3. **Paste a YouTube link → pick what you want → Make it happen ✦**

### 🗂 First time vs next time

**Download and extract `Mochi.zip` → open the `Mochi` folder.** On your OS, use **Install-Mochi** once for setup (or again for updates), then **Run Mochi Now** for everyday use.

<p align="center">
  <img src="docs/mochi-first-time-vs-next-time.webp" width="940" alt="Illustrated Mochi folder guide: on Windows first run Install-Mochi-Windows.cmd, then Run Mochi Now.lnk; on macOS first run Install-Mochi-Mac.command, then Run Mochi Now.app; on Linux first run Install-Mochi-Linux.sh, then Run Mochi Now.desktop. Keep your .mochi data folder." />
</p>

<sub>Illustration: folder appearances vary by OS; the `.mochi` folder is created during setup.</sub>

💜 Next time, just open **Run Mochi Now**. Your downloads stay on your computer.

> 🐧 On Linux, if the shortcut won't launch, right-click **Run Mochi Now.desktop → Allow Launching**. Or open a terminal in the Mochi folder and run `sh .mochi/run.sh`. Keep the `.mochi` folder when upgrading.

> 💡 First setup needs internet. Your OS might ask you to approve the launcher; keep its security protections enabled. **Linux opens the file as text?** Open a terminal inside the extracted Mochi folder and run `sh ./Install-Mochi-Linux.sh`.

**🛠️ Something stuck?** Open Mochi → **Fix my tools**. It can repair recognized problems without deleting your downloads.

<details>
<summary>⚙️ Requirements, privacy & developer notes</summary>

- **System:** Modern 64-bit Windows, macOS, or Linux. Compatibility with every device isn't guaranteed.
- **Internet:** Needed for setup, AI model downloads, and video downloads; speech recognition runs locally without a cloud transcription API.
- **Permissions:** Download only content you're allowed to save, respecting site terms and creators' rights.
- **Contributing:** Source lives in `app/`. To run tests, install Python dependencies plus `pytest`, `numpy`, `pillow`, and FFmpeg, then run `python -m pytest -q`. Automated checks don't guarantee every video or OS setup will work.

</details>

---

<p align="center">💜 Made with love by <a href="https://onehack.st/"><strong>1Hack</strong></a></p>
