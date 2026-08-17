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
- **Download Limit** — Cap how many torrents transfer at once (1–20)
- **Resume After Restart** — Unfinished downloads continue and interrupted
  encodes re-run on the next launch

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
5. (Optional) Drag the **Active downloads** slider to cap how many torrents
   transfer at once — 1 to 20, 5 by default. Anything over the cap is
   accepted and shown as `QUEUED`, and starts the moment a slot frees up.
   Raising the slider mid-session starts waiting torrents immediately;
   lowering it never kills a transfer already in flight, it just applies to
   what starts next.

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

Anything that did *not* finish is picked up separately, on the next launch —
see [Resuming After a Restart](#resuming-after-a-restart).

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
| `max_active_downloads` | How many torrents may transfer at once (1–20, default 5) |
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

## Resuming After a Restart

Closing Hoarder kills every download and every ffmpeg run with it. `session.json`
(next to the executable, or `%LOCALAPPDATA%\Hoarder\` when the install folder is
read-only) records what was still unfinished, and the next launch picks it up.

**Downloads genuinely resume.** The partial data and aria2c's `.aria2` control
file are still sitting in `.hoarder-incoming`, so re-adding the torrent
continues from where it stopped instead of starting over. What gets recorded is
the magnet URI, or — for a `.torrent` file — the private copy Hoarder made when
the download started, since the original may have been deleted by **Delete
torrent file after adding** long ago. Torrents that were still waiting on the
**Active downloads** cap are remembered too, and queue up again in the same
order.

**Encodes restart rather than resume.** ffmpeg has no way back into a
half-written file, so an interrupted batch is run again from the beginning. Its
partial output is deleted first: a truncated `.mp3` is indistinguishable from a
finished one by name alone, and leaving it would either be picked up as a source
file or collide with the rerun's own output. Nothing is lost — sources are only
deleted once a batch actually succeeds.

If something can't be resumed — a `.torrent` copy swept out of `%TEMP%`, a
source file deleted in the meantime — that entry is dropped quietly and the rest
still resume. A message in the drop zone reports what was picked up.

**What keeps a half-finished download out of the encoder.** On startup the
staging folder is swept for downloads an orphaned aria2c finished after the app
itself was closed; anything complete is moved into the monitored folder to be
converted. Three guards stop a torrent that is *not* finished from being swept
up along with them:

- aria2c's `.aria2` control file, which it writes **beside** what it is
  downloading — for a multi-file torrent that means `Album.aria2` sits next to
  the `Album` folder, not inside it.
- the saved session, which names every transfer that was still in flight at
  shutdown, and so covers a torrent killed before aria2c's first control-file
  save had written anything.
- resuming with `--check-integrity`, so aria2c hash-checks the partial data on
  disk and continues from it rather than trusting a control file that may be
  stale — or absent.

Anything the session still calls unfinished stays in staging for the resume,
however complete it looks.

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

Output: `dist/Plunder.exe` — one self-contained portable file.

### Windows Defender false positives

A PyInstaller `--onefile` executable is a self-extracting packed binary, which
is structurally what a dropper looks like. Defender's machine-learning
heuristics flag these routinely under generic names — `Trojan:Win32/Wacatac.B!ml`
and friends — and will delete the exe without asking. It is a false positive:
the detection is on the *shape* of the file, not on anything it does.

The build already avoids the two cheapest triggers:

- **No UPX.** `--noupx` in `build.py`, `upx=False` in the `.spec`. Packed
  sections are one of the strongest generic signals there is, and the few MB
  saved are not worth a quarantine.
- **A real version resource.** `version_info.txt` gives the exe a company name,
  description and version, so it does not look like a freshly packed binary
  with nothing to say for itself.

If a build still gets quarantined:

1. **Get it back** — Windows Security → *Virus & threat protection* →
   *Protection history* → find the detection → *Actions* → **Restore**.
2. **Exclude the build output** — *Virus & threat protection* → *Manage
   settings* → *Exclusions* → *Add an exclusion* → **Folder** → the `dist`
   folder. Exclude the folder, not the whole project, and keep it narrow.
3. **Report it** — submit the exe at
   <https://www.microsoft.com/en-us/wdsi/filesubmission> as a *software
   developer*, marked **incorrectly detected**. Turnaround is usually a day or
   two, and the correction applies to everyone rather than just this machine.

The durable fix is an authenticode code-signing certificate from a CA: signed
binaries accrue SmartScreen reputation over time. A self-signed certificate
does not help with SmartScreen, though it does let you trust the exe locally.

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
├── library.py           # Record of what has already been converted
├── session.py           # Unfinished downloads/encodes, for resume on restart
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
