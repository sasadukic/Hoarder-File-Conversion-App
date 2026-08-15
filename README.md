# Hoarder

A Windows GUI tool for converting lossless audio (FLAC, ALAC, APE, etc.) to 320kbps MP3, and transcoding video to H.265 MP4 with AAC audio. Includes folder monitoring, system tray minimization, and **auto-downloading torrents**.

---

## Features

- **Audio Conversion** — FLAC/ALAC/APE/AIFF/DSD/WMA → 320kbps MP3
- **CUE Splitting** — Split album FLACs by CUE sheet into individual tracks
- **Video Transcoding** — MP4/MKV/MOV/AVI/WMV → H.265 MP4 with AAC audio (GPU-accelerated when available)
- **Folder Monitor** — Watch a folder recursively; auto-convert new files as they arrive
- **Torrent Auto-Download** — Drop `.torrent` or `.magnet` files into the monitored folder (or straight onto the drop zone); they download straight into that same folder and convert when done
- **System Tray** — Minimize to tray and run in the background
- **Windows Startup** — Optionally start with Windows

---

## Quick Start

1. **Launch** `Hoarder.exe` (or `py main.py` for development)
2. **Drop files** onto the drop zone, or click it to browse
3. Conversion starts immediately; watch it in the encoding box below

The main page is the whole app: the drop zone doubles as the status line,
the Downloads box lists torrent progress, and the encoding box lists
conversion progress. Both boxes scroll (no visible scrollbar).

For automatic operation:
1. Enable **Monitor folder** in Setup and choose a folder to watch
2. Any audio/video files copied into that folder will be converted automatically

---

## Torrent Auto-Download

Hoarder can automatically download torrents and convert the media inside them.
There's no separate download folder to configure — torrents land straight in
the monitored folder, so a finished download converts exactly like any other
file dropped in by hand.

### Setup

1. In Setup, check **Monitor folder** and click its label to choose a folder
   to watch — required first, since that's also where torrents download to
2. Check **Auto-download torrents**
3. (Optional) Check **Move music to** / **Move video to** and pick
   destinations — converted output moves there once it's done, out of the
   monitored folder. Click the checkbox's label to pick the folder, the same
   way as Monitor folder.
4. (Optional) Check **Delete torrent file after adding** to clean up
   `.torrent`/`.magnet` files once the download has started

### How It Works

```
Monitored Folder
    ├── movie.torrent          → downloads to Monitored Folder
    └── album.magnet           → downloads to Monitored Folder
           ↓
    Folder watcher sees the finished files, same as any manual drop
           ↓
    Auto-conversion starts
           ↓
    Converted output moved to "Move music/video to" folder, if configured
```

1. Drop a `.torrent` file or `.magnet` link into the monitored folder (or
   straight onto the drop zone)
2. Hoarder detects it and starts downloading into a hidden staging
   subfolder (`.hoarder-incoming`) inside the monitored folder
3. Progress appears as a row in the Downloads box on the main page
4. Only once the download is genuinely complete — confirmed by the
   downloader itself, not guessed from file size — does Hoarder move it into
   the real monitored folder, where the watcher picks it up and converts it
5. If **Move music to** / **Move video to** is enabled, the converted output
   is relocated there once conversion finishes

Downloads stage first rather than landing directly in the watched folder
because BitTorrent doesn't write a file's pieces in order — its size can sit
still mid-download or jump close to final size early, so watching for "size
stopped changing" alone would occasionally start converting a file that
wasn't actually finished.

**If Hoarder is closed or killed mid-download**, the aria2c/libtorrent
process is orphaned and can go on to finish the download entirely on its
own, with nobody left to move it out of staging. Every time monitoring
starts (including at launch), Hoarder sweeps `.hoarder-incoming` for
anything left behind and checks aria2c's own `.aria2` control files — their
absence is aria2c's authoritative "this file is done" signal — to safely
recover anything that actually finished, and leave anything still
downloading or genuinely interrupted alone.

### SOCKS5 Proxy

For routing torrent traffic through a VPN — hides your IP from peers and
trackers. Set up at the bottom of the Setup tab (scroll down): check
**Enable SOCKS5 proxy** and enter the host, port, and (if your provider
requires it) username/password. Works with any SOCKS5-capable VPN provider
(PIA, Mullvad, etc. — most hand out a SOCKS5 endpoint specifically for
torrenting). Free VPNs generally don't offer this — either they block P2P
traffic outright or don't provide a SOCKS5 endpoint at all.

Both the libtorrent and aria2c backends route peer connections, tracker
announces, and DNS lookups through the proxy once enabled. This is not the
same as running the VPN app itself — SOCKS5 alone doesn't encrypt the hop to
the proxy the way a VPN tunnel does. Providers generally expect their SOCKS5
feature to be used *alongside* their VPN app already running, not as a
substitute for it. Saving the settings runs a quick one-time reachability
check (shown in the status line) to catch a mistyped host/port — it isn't a
continuous kill-switch, but a correctly configured SOCKS5 proxy fails closed
rather than silently falling back to a direct connection if it drops.

The proxy password is stored in plaintext in `settings.json`, same as every
other setting in this app.

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
| `auto_convert` | Unused — there is no Convert button, so loaded files always convert |
| `minimize_to_tray` | Send window to system tray on minimize |
| `start_on_startup` | Create a Windows startup shortcut |
| `sounds_enabled` | Play click/starting/done sound effects |
| `monitor_enabled` | Enable folder monitoring |
| `monitor_folder` | Path to the monitored folder |
| `torrent_enabled` | Enable torrent auto-download (downloads into `monitor_folder`) |
| `torrent_delete_source` | Delete `.torrent`/`.magnet` files after adding |
| `move_music_enabled` | Move converted audio out of the monitored folder after conversion |
| `move_music_folder` | Destination for converted audio |
| `move_video_enabled` | Move converted video out of the monitored folder after conversion |
| `move_video_folder` | Destination for converted video |
| `proxy_enabled` | Route torrent traffic through a SOCKS5 proxy |
| `proxy_host` | Proxy hostname or IP |
| `proxy_port` | Proxy port |
| `proxy_username` | Proxy username (optional) |
| `proxy_password` | Proxy password (optional, stored in plaintext) |

---

## Conversion Library

`library.json` (next to the executable, or `%LOCALAPPDATA%\Hoarder\` when the
install folder is read-only) records what has already been converted, so
restarting the app does not re-encode a monitored folder it has already been
through — including its own transcodes, which otherwise look like new source
videos to the startup scan.

- **Identity is content-based.** A file counts as done when the SHA-1 of its
  first 4 MB (salted with its byte size) is recorded, so the same release
  renamed or moved to another folder is not encoded twice. Edit the file and
  it converts again.
- **Digests are cached** per path + size + mtime, so a restart scan costs one
  `stat` per known file and only reads bytes for files it has not seen.
- **Only the automatic paths consult it** — the startup scan and the folder
  watcher (which is also how finished torrent downloads get converted, since
  they land in the monitored folder). Files you drop or browse for by hand
  always convert, so re-dropping a file is how you force a redo.
- Delete `library.json` to forget everything and start over.

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
