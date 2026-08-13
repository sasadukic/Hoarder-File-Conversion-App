# Hoarder

A Windows GUI tool for converting lossless audio (FLAC, ALAC, APE, etc.) to 320kbps MP3, and transcoding video to H.265 MP4 with AAC audio. Includes folder monitoring, system tray minimization, and **auto-downloading torrents**.

---

## Features

- **Audio Conversion** — FLAC/ALAC/APE/AIFF/DSD/WMA → 320kbps MP3
- **CUE Splitting** — Split album FLACs by CUE sheet into individual tracks
- **Video Transcoding** — MP4/MKV/MOV/AVI/WMV → H.265 MP4 with AAC audio (GPU-accelerated when available)
- **Folder Monitor** — Watch a folder recursively; auto-convert new files as they arrive
- **Torrent Auto-Download** — Drop `.torrent` or `.magnet` files into the monitored folder (or straight onto the drop zone); they download automatically and convert when done
- **System Tray** — Minimize to tray and run in the background
- **Windows Startup** — Optionally start with Windows

---

## Quick Start

1. **Launch** `Hoarder.exe` (or `py main.py` for development)
2. **Drop files** onto the drop zone, or browse to select them
3. Click **Convert**

For automatic operation:
1. Enable **Monitor folder** and choose a folder to watch
2. Enable **Auto-convert on load**
3. Any audio/video files copied into that folder will be converted automatically

---

## Torrent Auto-Download

Hoarder can automatically download torrents and convert the media inside them.

### Setup

1. Enable **Monitor folder** and select a folder to watch
2. Check **Auto-download torrents**
3. Choose a **Download folder** — where torrents are saved while downloading
4. Choose a **Finished folder** — where converted files are copied after conversion
5. (Optional) Check **Delete torrent file after adding** to clean up `.torrent`/`.magnet` files

### How It Works

```
Monitored Folder
    ├── movie.torrent          → TorrentDownloader starts
    └── album.magnet           → TorrentDownloader starts
           ↓
    Download Folder
           ↓
    Files copied to Monitored Folder
           ↓
    Auto-conversion starts
           ↓
    Converted files copied to Finished Folder
```

1. Drop a `.torrent` file or `.magnet` link into the monitored folder
2. Hoarder detects it and starts downloading
3. Progress appears in the status bar (e.g., "Torrent: movie 45%")
4. When complete, downloaded media files are copied to the monitored folder
5. Auto-conversion begins (same pipeline as regular files)
6. After conversion, converted files are copied to the Finished folder

### Engines

| Engine | Priority | Notes |
|--------|----------|-------|
| **libtorrent** | Primary | Fast, native Python bindings. Requires Python ≤3.13 (wheels not yet available for 3.14) |
| **aria2c** | Fallback | Single binary, no Python dependency. Live progress is parsed from its output. Place `aria2c.exe` in `bin/aria2c.exe` or ensure it's on your PATH |

If libtorrent is not installed, Hoarder automatically falls back to aria2c.

---

## Settings

All settings are persisted in `settings.json` next to the executable:

| Setting | Description |
|---------|-------------|
| `delete_flac` | Delete source files after conversion |
| `auto_convert` | Start conversion immediately when files are loaded |
| `minimize_to_tray` | Send window to system tray on minimize |
| `start_on_startup` | Create a Windows startup shortcut |
| `monitor_enabled` | Enable folder monitoring |
| `monitor_folder` | Path to the monitored folder |
| `torrent_enabled` | Enable torrent auto-download |
| `torrent_download_folder` | Where torrents are downloaded |
| `torrent_finished_folder` | Where converted files are copied |
| `torrent_delete_source` | Delete `.torrent`/`.magnet` files after adding |

---

## Development

### Requirements

- Python 3.11–3.14
- Windows 10/11

### Dependencies

```bash
py -m pip install -r requirements.txt
```

### Run

```bash
py main.py
```

### Tests

```bash
py -m pytest tests/ -v
```

### Build

```bash
py build.py
```

Output: `dist/Hoarder/` — a self-contained portable folder.

---

## File Structure

```
Hoarder/
├── main.py              # Entry point
├── gui.py               # Tkinter/customtkinter UI
├── converter.py         # ffmpeg/ffprobe wrappers
├── monitor.py           # Folder watcher (watchdog)
├── torrent_downloader.py # BitTorrent download engine
├── settings.py          # JSON settings persistence
├── cue_parser.py        # CUE sheet parser
├── build.py             # PyInstaller build script
├── bin/
│   ├── ffmpeg.exe       # Bundled ffmpeg (optional)
│   ├── ffprobe.exe      # Bundled ffprobe (optional)
│   └── aria2c.exe       # Bundled aria2c for torrent fallback (optional)
└── tests/               # pytest suite
```

---

## License

MIT
