---
name: ship
description: Release Hoarder after a work session — run the suite, commit, push to GitHub, build the portable exe, install it to C:\Program Files\Hoarder, and launch it for testing. Use when the user says "ship it", "finished working", "release this", "deploy Hoarder", or asks to install and open the built app.
---

# Ship Hoarder

Takes the working tree from "code is done" to "the built app is running on this
machine". Run the steps in order and stop at the first failure — never carry a
red suite or a failed build into an install.

## 1. Verify

```bash
py -m pytest tests/ -q
```

All tests must pass. If any fail, fix them or report and stop — do not ship.

The suite does not cover `_build_ui`, so if this session changed widget
construction in `gui.py`, also build the real `App` headlessly before shipping.
Force safe settings when doing so — the live `settings.json` may have
`monitor_enabled` + `auto_convert` + `delete_flac` pointed at a real folder,
and constructing `App` normally would start converting and deleting files
there:

```python
import settings as smod
smod.load = lambda: {k: False for k in (
    "delete_flac", "auto_convert", "minimize_to_tray", "start_on_startup",
    "monitor_enabled", "torrent_enabled", "torrent_delete_source")} | {
    "monitor_folder": None, "torrent_download_folder": None,
    "torrent_finished_folder": None}
smod.save = lambda data: None
import gui
app = gui.App(); app.update(); app.destroy()
```

## 2. Commit

Group changes into logical commits with a body explaining *why*, not just
what. Never `git add -A` a mixed working tree into one commit.

`settings.json` and `Hoarder.spec` hold machine-specific paths (the user's real
monitor/download folders, the local site-packages path). Commit them separately
from code, or leave them dirty — ask if unsure.

## 3. Push

```bash
git push origin master
```

Note: the remote URL has historically carried an embedded `ghp_` personal
access token. If it still does, flag it — that is a plaintext credential in
`.git/config`. Do not print the remote URL into a transcript or a published
artifact.

## 4. Build

```bash
py build.py
```

Takes several minutes — it bundles `bin/ffmpeg.exe` and `bin/ffprobe.exe`
(~100 MB each). Run it in the background and wait for the completion notice.
Output lands in `dist/Hoarder/`.

`build.py` derives the `tkinterdnd2`/`customtkinter` paths from whichever
interpreter runs it and regenerates `Hoarder.spec`, so the committed spec is a
build artifact. Confirm `py` resolves to the interpreter whose site-packages
you actually want bundled.

Verify `dist/Hoarder/Hoarder.exe` exists before continuing.

## 5. Install

Target: `C:\Program Files\Hoarder`

This needs elevation, which means a UAC prompt the user must accept. Tell them
it is coming rather than letting it appear unexplained. Close any running
instance first — a running `Hoarder.exe` locks files in the target folder.

```powershell
Start-Process powershell -Verb RunAs -Wait -ArgumentList @(
  '-NoProfile','-Command',
  'Get-Process Hoarder -EA SilentlyContinue | Stop-Process -Force;
   Remove-Item "C:\Program Files\Hoarder\*" -Recurse -Force -EA SilentlyContinue;
   Copy-Item "<repo>\dist\Hoarder\*" "C:\Program Files\Hoarder\" -Recurse -Force'
)
```

**Settings persistence caveat.** When frozen, `settings.py` writes
`settings.json` next to the executable. `C:\Program Files\` is not writable by
standard users and PyInstaller exes carry a manifest, so UAC file virtualization
does not apply — settings silently fail to save unless the install folder grants
the user write access. Either grant it explicitly during install, or install to
`%LOCALAPPDATA%\Hoarder` instead. Raise the tradeoff rather than deciding
silently: a user-writable directory under `Program Files` is a privilege-
escalation vector if anything ever runs the exe elevated.

## 6. Launch

```powershell
Start-Process 'C:\Program Files\Hoarder\Hoarder.exe'
```

**Before launching, check the settings the app will start with.** A fresh
install has no `settings.json` and falls back to all-`False` defaults, which is
safe. But if a previous install left one behind, `monitor_enabled` +
`auto_convert` + `delete_flac` against a real folder means the app starts
converting and deleting files in that folder the moment it opens. Read the
installed `settings.json` first and warn the user if it is armed.

Confirm the process is actually running before reporting success — a
`Start-Process` that returns cleanly does not mean the GUI came up:

```powershell
Start-Sleep -Seconds 3
Get-Process Hoarder -ErrorAction SilentlyContinue
```

## Report

Tell the user what shipped: the commits pushed, where the build landed, and
anything skipped or degraded. If a step was blocked (UAC declined, build
failed), say so plainly rather than reporting partial success as done.
