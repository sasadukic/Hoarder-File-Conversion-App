# Audio Converter — Design Spec
**Date:** 2026-05-18

## Overview

A single-window desktop GUI application for Windows that converts FLAC audio files to 320kbps MP3. Supports two modes, auto-detected from the files provided:

- **Split + Convert:** takes a single-file FLAC + CUE sheet, splits by track, and converts each track to 320kbps MP3
- **Convert Only:** takes one or more already-split FLAC files and converts each to 320kbps MP3

---

## Technology Stack

| Component | Choice | Reason |
|---|---|---|
| Language | Python 3 | Available on system |
| GUI framework | customtkinter | Modern look over plain tkinter, pure Python, easy install |
| Drag and drop | tkinterdnd2 | Native Windows DnD support for tkinter |
| Audio backend | ffmpeg (system PATH) | Industry standard, handles splitting and encoding |

---

## UI Layout

Single window, approximately 500×400px, customtkinter dark theme.

Top to bottom:

1. **Drop zone** — large dashed rectangle with label "Drop FLAC (+ CUE) here or click to browse". Accepts drag-and-drop. Clicking opens a file picker dialog (multi-select enabled).
2. **File info area** — displays loaded filenames and detected mode, e.g.:
   - `album.flac, album.cue — Mode: Split + Convert`
   - `track01.flac, track02.flac — Mode: Convert Only`
3. **Delete source FLAC checkbox** — unchecked by default, label: "Delete FLAC after conversion"
4. **Convert button** — full-width, disabled until valid files are loaded
5. **Status line** — single line of text below the button showing progress or result

---

## Auto-Detection Logic

| Input | Detected Mode |
|---|---|
| Exactly 1 `.flac` + exactly 1 `.cue` | Split + Convert |
| 1 or more `.flac`, no `.cue` | Convert Only |
| `.cue` without a `.flac` | Error: "Please also provide a FLAC file" |
| Non-FLAC/CUE files included | Error: "Unsupported file type" |
| Anything else | Error shown, Convert button stays disabled |

---

## Backend Logic

### Path 1 — Split + Convert

1. Parse the CUE file to extract per-track: track number, title, start timestamp, end timestamp (last track has no end — ffmpeg reads to EOF). CUE files are read as UTF-8 first; if that fails, fall back to Latin-1 (cp1252).
2. For each track, invoke ffmpeg:
   ```
   ffmpeg -ss <start> -to <end> -i <input.flac> -b:a 320k <output.mp3>
   ```
   (last track omits `-to`)
3. Output filename format: `01 - Track Title.mp3` in the same directory as the source FLAC
4. Tracks processed sequentially
5. Status text updates per track: "Converting track 3 of 12..."

### Path 2 — Convert Only

1. For each FLAC file, invoke ffmpeg:
   ```
   ffmpeg -i <input.flac> -b:a 320k <output.mp3>
   ```
2. Output filename: same stem as input, extension changed to `.mp3`, same directory
3. Status text updates per file: "Converting file 2 of 5..."

### Post-Conversion (both paths)

- If "Delete FLAC" is checked AND all conversions succeeded: delete the source FLAC file(s)
- If any conversion failed: stop batch, report error, do NOT delete any FLACs
- If FLAC deletion fails after successful conversion: show a warning but do not treat as failure

---

## Filename Sanitization

Track titles from CUE files are sanitized before use as filenames. The following characters are stripped or replaced with a space:

```
/ \ : * ? " < > |
```

---

## Error Handling

| Condition | Behavior |
|---|---|
| ffmpeg not on PATH | Status: "ffmpeg not found. Please install it and ensure it's on your PATH." |
| CUE file malformed | Status: "Could not parse CUE file: [reason]" — abort |
| ffmpeg call fails mid-batch | Status: "Error on track [N]: [ffmpeg stderr]" — stop, leave converted files, no FLAC deletion |
| Output file already exists | Overwrite silently (default ffmpeg behavior) |
| FLAC deletion fails | Status warning shown, app does not report overall failure |
| Drag-drop of unsupported type | Status: "Unsupported file type" — Convert button stays disabled |

---

## File Structure

```
Audio Convert/
├── main.py          # Entry point, launches GUI
├── gui.py           # customtkinter window and widgets
├── converter.py     # ffmpeg invocation logic (split+convert, convert-only)
├── cue_parser.py    # CUE file parsing, returns list of Track(num, title, start, end)
└── requirements.txt # customtkinter, tkinterdnd2
```

---

## Out of Scope

- Metadata tagging of output MP3s (ID3 tags beyond what ffmpeg copies automatically)
- Output format options (only 320kbps MP3)
- Queue management / history
- Configurable output directory (always same folder as input)
