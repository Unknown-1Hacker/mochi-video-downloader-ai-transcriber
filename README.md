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

### 🚀 Three steps. That's it.

1. **[Download Mochi.zip](https://github.com/Unknown-1Hacker/mochi-video-downloader-ai-transcriber/releases/latest/download/Mochi.zip)** and extract it.
2. **Double-click `1 INSTALL & OPEN`** for Windows, Mac, or Linux. Mochi prepares its tools.
3. **Paste a YouTube link → pick what you want → Make it happen ✦**

💜 Next time, just open **Run Mochi Now**. Your downloads stay on your computer.

> 💡 First setup needs internet. Your system might ask you to approve the launcher; keep its security protections enabled.

### 🧠 AI that listens to the audio

Mochi uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your computer—not YouTube's existing captions—to make subtitles and transcripts. Video downloads use [yt-dlp](https://github.com/yt-dlp/yt-dlp).

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
