# Monitor, Tray, Auto-Convert & Startup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add folder monitoring, system tray, auto-convert, Windows startup shortcut, and settings persistence to the FLAC→MP3 converter.

**Architecture:** New `settings.py` handles JSON persistence; new `monitor.py` wraps watchdog for folder watching; `gui.py` gains four checkboxes, tray logic via pystray, and startup shortcut management via PowerShell subprocess. All checkbox state is saved immediately on change and restored on launch.

**Tech Stack:** Python 3.14, customtkinter, tkinterdnd2, watchdog, pystray, Pillow

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `settings.py` | **Create** | Load/save `settings.json` with atomic write |
| `monitor.py` | **Create** | `FolderMonitor` class: watchdog Observer, file-stability polling, CUE pairing |
| `gui.py` | **Modify** | 4 new checkboxes, tray, startup shortcut, settings wiring |
| `requirements.txt` | **Modify** | Add watchdog, pystray, Pillow |
| `tests/test_settings.py` | **Create** | Unit tests for settings load/save |
| `tests/test_monitor.py` | **Create** | Unit tests for FolderMonitor |

---

## Task 1: Install new dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Update requirements.txt**

Replace the file contents with:

```
customtkinter>=5.2.0
tkinterdnd2>=0.3.0
pytest>=7.0.0
watchdog>=4.0.0
pystray>=0.19.0
Pillow>=10.0.0
```

- [ ] **Step 2: Install**

```bash
py -m pip install watchdog pystray Pillow
```

Expected: Successfully installed (or "already satisfied") for all three packages.

- [ ] **Step 3: Verify imports work**

```bash
py -c "import watchdog; import pystray; from PIL import Image; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add watchdog, pystray, Pillow dependencies"
```

---

## Task 2: `settings.py` — load/save JSON settings

**Files:**
- Create: `settings.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_settings.py`:

```python
import json
import pytest
from pathlib import Path
import settings as smod


DEFAULTS = {
    "delete_flac": False,
    "auto_convert": False,
    "minimize_to_tray": False,
    "start_on_startup": False,
    "monitor_enabled": False,
    "monitor_folder": None,
}


def test_load_missing_file_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(smod, "_SETTINGS_PATH", tmp_path / "settings.json")
    result = smod.load()
    assert result == DEFAULTS


def test_load_corrupt_file_returns_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("not json")
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    result = smod.load()
    assert result == DEFAULTS


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    data = {**DEFAULTS, "delete_flac": True, "monitor_folder": "/music"}
    smod.save(data)
    assert p.exists()
    result = smod.load()
    assert result["delete_flac"] is True
    assert result["monitor_folder"] == "/music"


def test_load_partial_file_fills_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"delete_flac": True}))
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    result = smod.load()
    assert result["delete_flac"] is True
    assert result["auto_convert"] is False  # filled from defaults


def test_save_is_atomic(tmp_path, monkeypatch):
    """save() writes to .tmp then renames — file should never be half-written."""
    p = tmp_path / "settings.json"
    monkeypatch.setattr(smod, "_SETTINGS_PATH", p)
    smod.save(DEFAULTS)
    # No .tmp file should remain after save
    assert not (tmp_path / "settings.json.tmp").exists()
    assert p.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
py -m pytest tests/test_settings.py -v
```

Expected: `ModuleNotFoundError: No module named 'settings'` (or similar import error)

- [ ] **Step 3: Implement `settings.py`**

Create `settings.py` next to `main.py`:

```python
import json
from pathlib import Path
from typing import Any, Dict

_SETTINGS_PATH = Path(__file__).parent / "settings.json"

_DEFAULTS: Dict[str, Any] = {
    "delete_flac": False,
    "auto_convert": False,
    "minimize_to_tray": False,
    "start_on_startup": False,
    "monitor_enabled": False,
    "monitor_folder": None,
}


def load() -> Dict[str, Any]:
    """Load settings from disk. Returns defaults on missing or corrupt file."""
    try:
        raw = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULTS, **{k: raw[k] for k in _DEFAULTS if k in raw}}
    except Exception:
        return dict(_DEFAULTS)


def save(data: Dict[str, Any]) -> None:
    """Atomically write settings to disk."""
    tmp = _SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_PATH)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
py -m pytest tests/test_settings.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add settings.py tests/test_settings.py
git commit -m "feat: add settings.py for persistent checkbox state"
```

---

## Task 3: `monitor.py` — FolderMonitor

**Files:**
- Create: `monitor.py`
- Create: `tests/test_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_monitor.py`:

```python
import time
import threading
from pathlib import Path
import pytest
from monitor import FolderMonitor


def wait_for(condition_fn, timeout=5.0, interval=0.05):
    """Poll until condition_fn() is True or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition_fn():
            return True
        time.sleep(interval)
    return False


def test_detects_new_flac(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "callback not fired"
        assert received[0] == [str(flac)]
    finally:
        m.stop()


def test_pairs_cue_with_flac(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        cue = tmp_path / "album.cue"
        cue.write_text("TITLE \"Album\"")
        flac = tmp_path / "album.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "callback not fired"
        assert str(flac) in received[0]
        assert str(cue) in received[0]


    finally:
        m.stop()


def test_ignores_non_flac_files(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        (tmp_path / "notes.txt").write_text("hello")
        time.sleep(0.8)
        assert len(received) == 0
    finally:
        m.stop()


def test_no_duplicate_trigger(tmp_path):
    received = []
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) >= 1)
        time.sleep(0.8)
        assert len(received) == 1, "duplicate callback fired"
    finally:
        m.stop()


def test_detects_flac_in_subfolder(tmp_path):
    received = []
    sub = tmp_path / "sub"
    sub.mkdir()
    m = FolderMonitor(str(tmp_path), lambda paths: received.append(paths))
    m.start()
    try:
        flac = sub / "deep.flac"
        flac.write_bytes(b"fLaC" + b"\x00" * 100)
        assert wait_for(lambda: len(received) == 1), "subfolder callback not fired"
        assert received[0] == [str(flac)]
    finally:
        m.stop()


def test_stop_is_idempotent(tmp_path):
    m = FolderMonitor(str(tmp_path), lambda paths: None)
    m.start()
    m.stop()
    m.stop()  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
py -m pytest tests/test_monitor.py -v
```

Expected: `ModuleNotFoundError: No module named 'monitor'`

- [ ] **Step 3: Implement `monitor.py`**

Create `monitor.py` next to `main.py`:

```python
import threading
import time
from pathlib import Path
from typing import Callable, List, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# How long the file size must be stable before we consider it fully written.
_STABLE_SECS = 0.5
_POLL_INTERVAL = 0.1


def _wait_stable(path: Path) -> bool:
    """Poll until file size is stable for _STABLE_SECS. Returns False if file disappears."""
    prev_size = -1
    stable_since = None
    while True:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == prev_size:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= _STABLE_SECS:
                return True
        else:
            stable_since = None
        prev_size = size
        time.sleep(_POLL_INTERVAL)


class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[List[str]], None], inflight: Set[str], lock: threading.Lock):
        self._callback = callback
        self._inflight = inflight
        self._lock = lock

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".flac":
            return
        key = str(path)
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(target=self._process, args=(path,), daemon=True).start()

    def _process(self, flac: Path) -> None:
        try:
            if not _wait_stable(flac):
                return
            paths = [str(flac)]
            cue = flac.with_suffix(".cue")
            if cue.exists():
                paths.append(str(cue))
            self._callback(paths)
        finally:
            with self._lock:
                self._inflight.discard(str(flac))


class FolderMonitor:
    """Watch a folder (recursively) for new FLAC files and trigger conversion."""

    def __init__(self, folder: str, on_files: Callable[[List[str]], None]):
        self._folder = folder
        self._on_files = on_files
        self._observer: Observer | None = None
        self._inflight: Set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching. No-op if already running."""
        if self._observer is not None:
            return
        handler = _Handler(self._on_files, self._inflight, self._lock)
        self._observer = Observer()
        self._observer.schedule(handler, self._folder, recursive=True)
        self._observer.start()

    def stop(self) -> None:
        """Stop watching. Safe to call multiple times."""
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None
        with self._lock:
            self._inflight.clear()
```

- [ ] **Step 4: Run tests**

```bash
py -m pytest tests/test_monitor.py -v
```

Expected: 6 passed. (File-system tests may take 2–5 s each due to stability polling.)

- [ ] **Step 5: Run full suite to check nothing broke**

```bash
py -m pytest tests/ -v
```

Expected: all existing tests + 6 new = 38+ passed, 0 failed

- [ ] **Step 6: Commit**

```bash
git add monitor.py tests/test_monitor.py
git commit -m "feat: add FolderMonitor with watchdog, stability polling, CUE pairing"
```

---

## Task 4: Extend `gui.py` — settings wiring + new checkboxes

**Files:**
- Modify: `gui.py`

This task adds the 4 new checkboxes, the monitor folder picker row, and wires settings load/save. No functional behavior yet (tray and monitor are wired in Tasks 5 & 6).

- [ ] **Step 1: Add imports and settings load to `App.__init__`**

At the top of `gui.py`, add imports after the existing import block (`Path` is already imported — skip it; only add the two new module imports):

```python
import settings as smod
import monitor as mmod
```

In `App.__init__`, before `self._build_ui()`, add:

```python
self._settings = smod.load()
self._monitor: mmod.FolderMonitor | None = None
self._hiding_to_tray = False
self._tray_icon = None
```

- [ ] **Step 2: Replace `_build_ui` with extended version**

Replace the entire `_build_ui` method in `gui.py` with:

```python
def _build_ui(self) -> None:
    s = self._settings

    # Drop zone frame
    self._drop_frame = tk.Frame(
        self,
        bg="#2b2b2b",
        highlightbackground="#555555",
        highlightthickness=2,
        cursor="hand2",
    )
    self._drop_frame.place(x=20, y=20, width=460, height=150)

    self._drop_label = tk.Label(
        self._drop_frame,
        text="Drop FLAC (+ CUE) here\nor click to browse",
        bg="#2b2b2b",
        fg="#aaaaaa",
        font=("Segoe UI", 12),
        justify="center",
    )
    self._drop_label.place(relx=0.5, rely=0.5, anchor="center")

    for widget in (self._drop_frame, self._drop_label):
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", self._on_drop)
        widget.bind("<Button-1>", lambda e: self._browse())

    # File info
    self._info_label = tk.Label(
        self,
        text="No files loaded",
        bg="#1a1a1a",
        fg="#888888",
        font=("Segoe UI", 10),
        wraplength=460,
        justify="left",
        anchor="w",
    )
    self._info_label.place(x=20, y=185, width=460, height=50)

    # --- Checkboxes ---
    self._delete_var = tk.BooleanVar(value=s["delete_flac"])
    self._delete_check = ctk.CTkCheckBox(
        self, text="Delete FLAC after conversion",
        variable=self._delete_var, font=("Segoe UI", 11),
    )
    self._delete_check.place(x=20, y=245)

    self._auto_convert_var = tk.BooleanVar(value=s["auto_convert"])
    self._auto_check = ctk.CTkCheckBox(
        self, text="Auto-convert on load",
        variable=self._auto_convert_var, font=("Segoe UI", 11),
    )
    self._auto_check.place(x=20, y=275)

    self._tray_var = tk.BooleanVar(value=s["minimize_to_tray"])
    self._tray_check = ctk.CTkCheckBox(
        self, text="Minimize to tray",
        variable=self._tray_var, font=("Segoe UI", 11),
        command=self._on_tray_toggle,
    )
    self._tray_check.place(x=20, y=305)

    self._startup_var = tk.BooleanVar(value=s["start_on_startup"])
    self._startup_check = ctk.CTkCheckBox(
        self, text="Start on Windows startup",
        variable=self._startup_var, font=("Segoe UI", 11),
        command=self._on_startup_toggle,
    )
    self._startup_check.place(x=20, y=335)

    # --- Folder monitor row ---
    self._monitor_var = tk.BooleanVar(value=False)  # activated after folder set
    self._monitor_check = ctk.CTkCheckBox(
        self, text="Monitor folder",
        variable=self._monitor_var, font=("Segoe UI", 11),
        command=self._on_monitor_toggle,
    )
    self._monitor_check.place(x=20, y=365)

    self._monitor_browse_btn = ctk.CTkButton(
        self, text="Browse…", font=("Segoe UI", 11),
        width=90, height=26,
        command=self._browse_monitor_folder,
    )
    self._monitor_browse_btn.place(x=390, y=365)

    self._monitor_folder_var = tk.StringVar(
        value=s["monitor_folder"] or ""
    )
    self._monitor_folder_label = tk.Label(
        self,
        textvariable=self._monitor_folder_var,
        bg="#1a1a1a", fg="#888888",
        font=("Segoe UI", 9),
        anchor="w", wraplength=460,
    )
    self._monitor_folder_label.place(x=20, y=393, width=460, height=20)

    # Restore monitor enabled state (only if folder is saved)
    if s["monitor_folder"] and s["monitor_enabled"]:
        self._monitor_var.set(True)
        self._start_monitor(s["monitor_folder"])

    # Convert button
    self._convert_btn = ctk.CTkButton(
        self,
        text="Convert",
        font=("Segoe UI", 13, "bold"),
        state="disabled",
        command=self._start_conversion,
        width=460,
        height=45,
    )
    self._convert_btn.place(x=20, y=423)

    # Status line
    self._status_label = tk.Label(
        self,
        text="",
        bg="#1a1a1a",
        fg="#88cc88",
        font=("Segoe UI", 10),
        wraplength=460,
        anchor="w",
    )
    self._status_label.place(x=20, y=478, width=460, height=40)

    # Settings traces (save on any change)
    for var in (
        self._delete_var, self._auto_convert_var,
        self._tray_var, self._startup_var,
        self._monitor_var, self._monitor_folder_var,
    ):
        var.trace_add("write", lambda *_: self._save_settings())

    # Tray: bind minimize event
    self.bind("<Unmap>", self._on_unmap)
```

- [ ] **Step 3: Update window size in `__init__`**

In `App.__init__`, change:
```python
self.geometry("500x410")
```
to:
```python
self.geometry("500x530")
```

- [ ] **Step 4: Add `_save_settings` helper**

Add this method to `App`:

```python
def _save_settings(self) -> None:
    smod.save({
        "delete_flac": self._delete_var.get(),
        "auto_convert": self._auto_convert_var.get(),
        "minimize_to_tray": self._tray_var.get(),
        "start_on_startup": self._startup_var.get(),
        "monitor_enabled": self._monitor_var.get(),
        "monitor_folder": self._monitor_folder_var.get() or None,
    })
```

- [ ] **Step 5: Update `_load_files` to support auto-convert**

Find the end of `_load_files` (after `self._status_label.config(text="", ...)`). Add:

```python
        if self._auto_convert_var.get():
            self._start_conversion()
```

- [ ] **Step 6: Verify existing tests still pass**

```bash
py -m pytest tests/ -v
```

Expected: 38+ passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: add 4 new checkboxes, settings wiring, auto-convert on load"
```

---

## Task 5: `gui.py` — folder monitor integration

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add `_browse_monitor_folder`**

Add to `App`:

```python
def _browse_monitor_folder(self) -> None:
    folder = filedialog.askdirectory(title="Select folder to monitor")
    if not folder:
        return
    self._monitor_folder_var.set(folder)
    # If monitor checkbox is on, restart with new folder
    if self._monitor_var.get():
        self._stop_monitor()
        self._start_monitor(folder)
```

- [ ] **Step 2: Add `_on_monitor_toggle`**

Add to `App`:

```python
def _on_monitor_toggle(self) -> None:
    folder = self._monitor_folder_var.get()
    if self._monitor_var.get():
        if not folder:
            self._set_status("Select a folder to monitor first.", "#cc4444")
            self._monitor_var.set(False)
            return
        self._start_monitor(folder)
    else:
        self._stop_monitor()
```

- [ ] **Step 3: Add `_start_monitor` and `_stop_monitor`**

Add to `App`:

```python
def _start_monitor(self, folder: str) -> None:
    self._stop_monitor()
    self._monitor = mmod.FolderMonitor(folder, self._on_monitor_files)
    try:
        self._monitor.start()
        self._set_status(f"Monitoring: {folder}", "#88cc88")
    except Exception as e:
        self._set_status(f"Monitor error: {e}", "#cc4444")
        self._monitor_var.set(False)
        self._monitor = None

def _stop_monitor(self) -> None:
    if self._monitor is not None:
        self._monitor.stop()
        self._monitor = None
```

- [ ] **Step 4: Add `_on_monitor_files` callback**

Add to `App`:

```python
def _on_monitor_files(self, paths: List[str]) -> None:
    """Called from watchdog thread — marshal to main thread."""
    self.after(0, self._load_and_auto_convert, paths)

def _load_and_auto_convert(self, paths: List[str]) -> None:
    """Load files from monitor and always start conversion.

    _load_files may already trigger conversion when auto_convert is on.
    Only call _start_conversion here when it hasn't been triggered yet.
    """
    self._load_files(paths)
    # _load_files calls _start_conversion when auto_convert is on.
    # When auto_convert is off we still want to convert (monitor always converts).
    if self._mode is not None and not self._auto_convert_var.get():
        self._start_conversion()
```

- [ ] **Step 5: Ensure monitor stops on app close**

Override `destroy` in `App`:

```python
def destroy(self) -> None:
    self._stop_monitor()
    if self._tray_icon is not None:
        try:
            self._tray_icon.stop()
        except Exception:
            pass
    super().destroy()
```

- [ ] **Step 6: Run full test suite**

```bash
py -m pytest tests/ -v
```

Expected: all passed, 0 failed

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: wire folder monitor into GUI with start/stop/callback"
```

---

## Task 6: `gui.py` — system tray

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add pystray import at top of `gui.py`**

Add after existing imports:

```python
import pystray
from PIL import Image, ImageDraw
```

- [ ] **Step 2: Add `_build_tray_icon`**

Add to `App`:

```python
def _build_tray_icon(self) -> pystray.Icon:
    """Create a 64x64 tray icon with 'F→M' text."""
    img = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    draw.text((8, 20), "F\u2192M", fill=(200, 200, 200, 255))
    menu = pystray.Menu(
        pystray.MenuItem("Open", self._tray_open, default=True),
        pystray.MenuItem("Quit", self._tray_quit),
    )
    return pystray.Icon("FLAC Converter", img, "FLAC Converter", menu)

def _tray_open(self, icon=None, item=None) -> None:
    self.after(0, self._restore_from_tray)

def _tray_quit(self, icon=None, item=None) -> None:
    if self._tray_icon is not None:
        self._tray_icon.stop()
        self._tray_icon = None
    self.after(0, self.destroy)

def _restore_from_tray(self) -> None:
    if self._tray_icon is not None:
        self._tray_icon.stop()
        self._tray_icon = None
    self.deiconify()
    self.lift()
    self.focus_force()
```

- [ ] **Step 3: Add `_on_unmap` handler**

Add to `App`:

```python
def _on_unmap(self, event) -> None:
    """Called when window is minimized (or hidden). Route to tray if enabled."""
    if event.widget is not self:
        return
    if self._hiding_to_tray:
        return
    if not self._tray_var.get():
        return
    self._hiding_to_tray = True
    try:
        self._tray_icon = self._build_tray_icon()
        self.withdraw()
        self._tray_icon.run_detached()
    except Exception as e:
        self._hiding_to_tray = False
        self._tray_var.set(False)
        self._set_status(f"Tray error: {e}", "#cc4444")
    finally:
        self._hiding_to_tray = False
```

- [ ] **Step 4: Add `_on_tray_toggle`**

Add to `App`:

```python
def _on_tray_toggle(self) -> None:
    """If tray is unchecked while window is hidden, restore immediately."""
    if not self._tray_var.get() and self._tray_icon is not None:
        self._restore_from_tray()
```

- [ ] **Step 5: Run app manually and test minimize to tray**

```bash
py main.py
```

- Check "Minimize to tray", minimize the window — should disappear to tray
- Right-click tray icon → Open → window restores
- Right-click tray icon → Quit → app exits cleanly

- [ ] **Step 6: Run full test suite**

```bash
py -m pytest tests/ -v
```

Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: add system tray support with Open/Quit menu"
```

---

## Task 7: `gui.py` — Windows startup shortcut

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add `_startup_lnk_path` helper**

Add to `App`:

```python
@staticmethod
def _startup_lnk_path() -> Path:
    import os
    startup = Path(os.environ["APPDATA"]) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup / "FLAC Converter.lnk"

@staticmethod
def _run_bat_path() -> Path:
    return Path(__file__).parent / "run.bat"
```

- [ ] **Step 2: Add `_create_startup_shortcut` and `_remove_startup_shortcut`**

Add to `App`:

```python
def _create_startup_shortcut(self) -> None:
    """Create a .lnk in the Windows Startup folder pointing to run.bat."""
    import subprocess
    lnk = str(self._startup_lnk_path())
    target = str(self._run_bat_path().resolve())
    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
        f'$s.TargetPath="{target}";'
        f'$s.Save()'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell error")

def _remove_startup_shortcut(self) -> None:
    self._startup_lnk_path().unlink(missing_ok=True)
```

- [ ] **Step 3: Add `_on_startup_toggle`**

Add to `App`:

```python
def _on_startup_toggle(self) -> None:
    try:
        if self._startup_var.get():
            self._create_startup_shortcut()
            self._set_status("Added to Windows startup.", "#88cc88")
        else:
            self._remove_startup_shortcut()
            self._set_status("Removed from Windows startup.", "#88cc88")
    except Exception as e:
        self._set_status(f"Startup shortcut error: {e}", "#cc4444")
        self._startup_var.set(not self._startup_var.get())  # revert
```

- [ ] **Step 4: Add stale shortcut check on launch**

In `App.__init__`, after `self._build_ui()`, add:

```python
        self._check_stale_startup_shortcut()
```

Add the method:

```python
def _check_stale_startup_shortcut(self) -> None:
    """Recreate startup shortcut if it exists but points to wrong path."""
    if not self._startup_var.get():
        return
    lnk = self._startup_lnk_path()
    if not lnk.exists():
        # Checkbox says on but .lnk missing — try to recreate
        try:
            self._create_startup_shortcut()
        except Exception:
            pass
        return
    # Check if target matches current run.bat
    import subprocess
    target_expected = str(self._run_bat_path().resolve())
    ps = f'(New-Object -COM WScript.Shell).CreateShortcut("{lnk}").TargetPath'
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        current_target = result.stdout.strip()
        if current_target != target_expected:
            try:
                self._create_startup_shortcut()
            except Exception:
                pass
```

- [ ] **Step 5: Run app manually and test startup shortcut**

```bash
py main.py
```

- Check "Start on Windows startup" — status should say "Added to Windows startup."
- Verify `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\FLAC Converter.lnk` exists
- Uncheck — verify the `.lnk` is deleted

- [ ] **Step 6: Run full test suite**

```bash
py -m pytest tests/ -v
```

Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat: add Windows startup shortcut via PowerShell"
```

---

## Task 8: Final smoke test and cleanup

**Files:**
- No new files

- [ ] **Step 1: Run complete test suite**

```bash
py -m pytest tests/ -v
```

Expected: all passed, 0 failed, 0 errors

- [ ] **Step 2: Launch app and do end-to-end manual check**

```bash
py main.py
```

Verify:
1. App opens at 500×530, all 5 checkboxes visible
2. Drag a FLAC onto the drop zone — info label updates, Convert button enables
3. Check "Auto-convert", drag another FLAC — conversion starts immediately (no button press)
4. Check "Monitor folder", click Browse — folder picker opens; select a folder; status shows "Monitoring: ..."
5. Copy a `.flac` into the monitored folder — auto-converts within ~2 seconds
6. Check "Minimize to tray", minimize window — disappears to tray; right-click → Open restores it
7. Check "Start on Windows startup" — status confirms; `.lnk` file present in Startup folder
8. Close and reopen — all checkboxes restore to saved state

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete monitor, tray, auto-convert, startup features"
```
