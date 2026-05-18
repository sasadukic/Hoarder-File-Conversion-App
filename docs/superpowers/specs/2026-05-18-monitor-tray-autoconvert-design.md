# Design: Folder Monitor, System Tray, Auto-Convert, Startup & Settings Persistence

**Date:** 2026-05-18
**Status:** Approved

## Overview

Extends the existing FLAC-to-MP3 converter with four new features controlled by checkboxes:

1. **Auto-convert** — files loaded via drop, browse, or monitor trigger conversion immediately (no button press)
2. **Folder monitor** — watch a selected folder (and subfolders) for new FLACs; auto-convert on arrival
3. **Minimize to tray** — hide window to system tray on minimize; tray icon with Open / Quit menu
4. **Start on Windows startup** — create/remove a `.lnk` shortcut in the Windows Startup folder

All checkbox states and the monitored folder path are persisted to `settings.json` and restored on next launch.

The folder layout stays as-is; `run.bat` remains the single entry point.

---

## New Modules

### `monitor.py`

`FolderMonitor(folder: str, on_files: Callable[[List[str]], None])`

Responsibilities:
- Wraps a `watchdog` `Observer` with `recursive=True` to cover subfolders
- `FileSystemEventHandler.on_created` fires for every new file; only `.flac` files are acted on
- **File-stability wait:** after `on_created`, poll the file's size every 100 ms until it has not changed for 500 ms (handles large files still being copied into the folder)
- After stability: look for a `.cue` file with the same stem in the same directory. If found, call `on_files([flac_path, cue_path])`; otherwise call `on_files([flac_path])`
- **In-flight tracking:** a `set` of paths currently being waited on / converted prevents duplicate triggers for the same file
- `start()` — creates and starts the `Observer`
- `stop()` — stops and joins the `Observer`; clears in-flight set
- `on_files` is called from the watchdog thread; callers must marshal to the main thread (via `self.after(0, ...)`)

### `settings.py`

Loads and saves a JSON file (`settings.json`) next to `main.py`.

Keys:

| Key | Type | Default |
|-----|------|---------|
| `delete_flac` | bool | false |
| `auto_convert` | bool | false |
| `minimize_to_tray` | bool | false |
| `start_on_startup` | bool | false |
| `monitor_enabled` | bool | false |
| `monitor_folder` | str or null | null |

- `load() -> dict` — reads the file; on missing or corrupt JSON, returns defaults silently
- `save(data: dict) -> None` — writes atomically (write to `.tmp`, rename)

---

## Changes to `gui.py`

### New checkboxes (added below existing "Delete FLAC" checkbox)

Layout (y positions, window height grows from 410 → 530):

| Widget | y |
|--------|---|
| Drop zone | 20 |
| Info label | 185 |
| Delete FLAC checkbox | 245 |
| Auto-convert checkbox | 275 |
| Minimize to tray checkbox | 305 |
| Start on startup checkbox | 335 |
| Monitor checkbox + Browse button (inline) | 365 |
| Monitor folder path label | 393 |
| Convert button | 423 |
| Status label | 478 |
| **Window height** | **530** |

### Settings persistence

- `App.__init__` calls `settings.load()` before `_build_ui()`
- Each `BooleanVar` / `StringVar` gets `trace_add("write", _on_settings_change)`
- `_on_settings_change` calls `settings.save(...)` immediately

### Auto-convert

- `_load_files` checks `self._auto_convert_var.get()` at the end; if True, calls `self._start_conversion()` directly
- Monitor callback also calls `_start_conversion()` after loading files (monitor always auto-converts)

### Folder monitor

- "Monitor" checkbox + "Browse…" button on the same row
- Browsing opens `filedialog.askdirectory()`; selected path shown in a small label below
- Checking the box (with a folder selected) calls `self._monitor.start()`
- Unchecking calls `self._monitor.stop()`
- Monitor's `on_files` callback is: `self.after(0, self._on_monitor_files, paths)`
- `_on_monitor_files(paths)` calls `_load_files(paths)` which triggers `_start_conversion()` (auto-convert is implicit for monitor)
- If checkbox is checked but no folder is selected, show status error and uncheck

### System tray

- `pystray` + `Pillow`; icon is a 64×64 RGBA image generated at runtime (dark background, white "F→M" text)
- `_build_tray_icon()` — creates the `pystray.Icon` with menu items Open and Quit; does not show it yet
- Binding `<Unmap>` on the window; handler checks `self._minimize_to_tray_var.get()` and a `_hiding_to_tray` re-entrance guard (since `withdraw()` itself fires `<Unmap>`):
  - If True: `self.withdraw()`, `self._tray_icon.run_detached()`
  - If False: normal minimize
- Open menu item: `self.after(0, self.deiconify)` + `self._tray_icon.stop()`
- Quit menu item: `self._tray_icon.stop()` then `self.destroy()`
- Double-click tray icon also triggers Open
- When "Minimize to tray" is unchecked while window is hidden in tray: restore window immediately, stop icon

### Windows startup shortcut

- Target: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FLAC Converter.lnk`
- On check: run PowerShell one-liner via `subprocess` to create the `.lnk` pointing to the full resolved path of `run.bat`
- On uncheck: `Path(lnk).unlink(missing_ok=True)`
- On app launch with the checkbox checked: verify the `.lnk` target still matches the current `run.bat` path; if stale (folder moved), silently recreate it

PowerShell command template:
```powershell
$s=(New-Object -COM WScript.Shell).CreateShortcut('<lnk_path>');
$s.TargetPath='<run_bat_path>';
$s.Save()
```

---

## Dependencies Added

```
watchdog>=4.0.0
pystray>=0.19.0
Pillow>=10.0.0
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Monitor folder deleted while watching | watchdog raises; catch in `on_error`, set status "Monitor folder no longer accessible", uncheck monitor checkbox |
| File copied into monitored folder then deleted before conversion starts | ffmpeg fails with RuntimeError; show error in status, remove from in-flight set |
| PowerShell unavailable (very old Windows) | Catch `FileNotFoundError` on subprocess, show status "Could not create startup shortcut" |
| `settings.json` corrupt on load | Log to stderr, use defaults; overwrite on next save |
| Tray icon creation fails (no display) | Catch exception, uncheck "Minimize to tray", show status message |

---

## Testing

- `monitor.py` — unit tests with a temp directory: create a `.flac` file, assert callback fires with correct paths; test CUE pairing; test in-flight dedup
- `settings.py` — unit tests: load missing file returns defaults; save/load roundtrip; corrupt file returns defaults
- `gui.py` — existing 32 tests unaffected; `detect_mode` and `parse_drop_paths` are pure functions and stay testable
- Startup shortcut and tray icon not unit-tested (OS-dependent side effects); covered by manual smoke test
