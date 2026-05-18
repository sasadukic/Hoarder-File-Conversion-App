# Audio Converter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-window Python GUI that converts FLAC files to 320kbps MP3, with optional CUE-based splitting.

**Architecture:** Four focused modules — `cue_parser.py` (CUE parsing), `converter.py` (ffmpeg calls), `gui.py` (customtkinter UI), `main.py` (entry point). The GUI runs ffmpeg operations on a background thread to keep the UI responsive.

**Tech Stack:** Python 3, customtkinter, tkinterdnd2, ffmpeg (system PATH), pytest

---

## File Structure

```
Audio Convert/
├── main.py              # Entry point
├── gui.py               # App window (TkinterDnD.Tk subclass)
├── converter.py         # ffmpeg invocation + FLAC deletion
├── cue_parser.py        # CUE file parsing → list of Track
├── requirements.txt     # customtkinter, tkinterdnd2
└── tests/
    ├── test_cue_parser.py
    ├── test_converter.py
    └── test_gui.py
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write requirements.txt**

```
customtkinter>=5.2.0
tkinterdnd2>=0.3.0
pytest>=7.0.0
```

- [ ] **Step 2: Install dependencies**

```bash
py -m pip install customtkinter tkinterdnd2 pytest
```

Expected: all three packages install without errors.

- [ ] **Step 3: Create tests package**

Create an empty file `tests/__init__.py` (no content needed).

- [ ] **Step 4: Verify pytest works**

```bash
py -m pytest tests/ -v
```

Expected: `no tests ran` (0 collected) — not an error.

---

## Task 2: CUE Parser

**Files:**
- Create: `cue_parser.py`
- Create: `tests/test_cue_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cue_parser.py`:

```python
import pytest
from cue_parser import _cue_time_to_seconds, _sanitize_filename, parse_cue
import tempfile, os


def test_cue_time_basic():
    assert _cue_time_to_seconds("00:00:00") == pytest.approx(0.0)


def test_cue_time_minutes():
    assert _cue_time_to_seconds("01:23:00") == pytest.approx(83.0)


def test_cue_time_frames():
    # 75 frames = 1 second
    assert _cue_time_to_seconds("00:00:75") == pytest.approx(1.0)


def test_cue_time_frames_partial():
    assert _cue_time_to_seconds("00:01:37") == pytest.approx(60 + 37 / 75.0)


def test_cue_time_invalid():
    with pytest.raises(ValueError):
        _cue_time_to_seconds("01:23")


def test_sanitize_filename_removes_invalid_chars():
    assert _sanitize_filename('Song: Part/Two') == 'Song  Part Two'


def test_sanitize_filename_strips_whitespace():
    assert _sanitize_filename('  Hello  ') == 'Hello'


def test_sanitize_filename_all_invalid():
    assert _sanitize_filename('/\\:*?"<>|') == ''


def test_parse_cue_two_tracks():
    cue_content = '''\
PERFORMER "Artist"
TITLE "Album"
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    TITLE "First Song"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second Song"
    INDEX 01 03:15:00
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write(cue_content)
        path = f.name
    try:
        tracks = parse_cue(path)
        assert len(tracks) == 2
        assert tracks[0].number == 1
        assert tracks[0].title == "First Song"
        assert tracks[0].start == pytest.approx(0.0)
        assert tracks[0].end == pytest.approx(195.0)  # 3*60+15
        assert tracks[1].number == 2
        assert tracks[1].title == "Second Song"
        assert tracks[1].start == pytest.approx(195.0)
        assert tracks[1].end is None
    finally:
        os.unlink(path)


def test_parse_cue_missing_title_uses_fallback():
    cue_content = '''\
FILE "album.flac" WAVE
  TRACK 01 AUDIO
    INDEX 01 00:00:00
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write(cue_content)
        path = f.name
    try:
        tracks = parse_cue(path)
        assert tracks[0].title == "Track 01"
    finally:
        os.unlink(path)


def test_parse_cue_empty_raises():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.cue',
                                     delete=False, encoding='utf-8') as f:
        f.write("PERFORMER \"Nobody\"\n")
        path = f.name
    try:
        with pytest.raises(ValueError, match="No tracks found"):
            parse_cue(path)
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
py -m pytest tests/test_cue_parser.py -v
```

Expected: `ImportError` — `cue_parser` not found.

- [ ] **Step 3: Implement cue_parser.py**

Create `cue_parser.py`:

```python
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Track:
    number: int
    title: str
    start: float   # seconds
    end: Optional[float]  # None for last track


def _cue_time_to_seconds(time_str: str) -> float:
    """Convert CUE time format mm:ss:ff to seconds (75 frames/sec)."""
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid CUE time format: {time_str!r}")
    mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2])
    return mm * 60 + ss + ff / 75.0


def _sanitize_filename(title: str) -> str:
    """Strip characters invalid in Windows filenames."""
    for ch in r'/\:*?"<>|':
        title = title.replace(ch, " ")
    return title.strip()


def parse_cue(cue_path: str) -> List[Track]:
    """Parse a CUE file and return a list of Track objects.

    Tries UTF-8 encoding first, falls back to cp1252.
    Raises ValueError if no tracks are found or the file is malformed.
    """
    path = Path(cue_path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="cp1252")

    tracks: List[Track] = []
    current_num: Optional[int] = None
    current_title: Optional[str] = None

    for line in content.splitlines():
        line = line.strip()

        m = re.match(r'TRACK\s+(\d+)\s+AUDIO', line, re.IGNORECASE)
        if m:
            current_num = int(m.group(1))
            current_title = None
            continue

        m = re.match(r'TITLE\s+"(.*)"', line, re.IGNORECASE)
        if m and current_num is not None:
            current_title = _sanitize_filename(m.group(1))
            continue

        m = re.match(r'INDEX\s+01\s+(\d+:\d+:\d+)', line, re.IGNORECASE)
        if m and current_num is not None:
            start = _cue_time_to_seconds(m.group(1))
            # Set end time on the previous track
            if tracks:
                prev = tracks[-1]
                tracks[-1] = Track(
                    number=prev.number,
                    title=prev.title,
                    start=prev.start,
                    end=start,
                )
            tracks.append(Track(
                number=current_num,
                title=current_title or f"Track {current_num:02d}",
                start=start,
                end=None,
            ))

    if not tracks:
        raise ValueError("No tracks found in CUE file")

    return tracks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
py -m pytest tests/test_cue_parser.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git init
git add cue_parser.py tests/test_cue_parser.py tests/__init__.py requirements.txt
git commit -m "feat: add CUE parser with tests"
```

---

## Task 3: Converter

**Files:**
- Create: `converter.py`
- Create: `tests/test_converter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_converter.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path
import tempfile, os

from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs
from cue_parser import Track


# --- check_ffmpeg ---

def test_check_ffmpeg_found():
    with patch("converter.shutil.which", return_value="/usr/bin/ffmpeg"):
        assert check_ffmpeg() is True


def test_check_ffmpeg_not_found():
    with patch("converter.shutil.which", return_value=None):
        assert check_ffmpeg() is False


# --- split_and_convert ---

def test_split_and_convert_calls_ffmpeg_per_track():
    tracks = [
        Track(number=1, title="Intro", start=0.0, end=60.0),
        Track(number=2, title="Main", start=60.0, end=None),
    ]
    progress_calls = []
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("converter.subprocess.run", return_value=mock_result) as mock_run:
        split_and_convert(
            "/music/album.flac",
            tracks,
            lambda cur, total: progress_calls.append((cur, total)),
        )

    assert mock_run.call_count == 2
    assert progress_calls == [(1, 2), (2, 2)]

    # Track 1: has -to
    cmd1 = mock_run.call_args_list[0][0][0]
    assert "-ss" in cmd1
    assert "-to" in cmd1
    assert "01 - Intro.mp3" in cmd1[-1]

    # Track 2: no -to (last track)
    cmd2 = mock_run.call_args_list[1][0][0]
    assert "-ss" in cmd2
    assert "-to" not in cmd2
    assert "02 - Main.mp3" in cmd2[-1]


def test_split_and_convert_raises_on_ffmpeg_failure():
    tracks = [Track(number=1, title="Song", start=0.0, end=None)]
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "some error"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Error on track 1"):
            split_and_convert("/music/album.flac", tracks, lambda c, t: None)


# --- convert_files ---

def test_convert_files_calls_ffmpeg_per_file():
    progress_calls = []
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("converter.subprocess.run", return_value=mock_result) as mock_run:
        convert_files(
            ["/music/track01.flac", "/music/track02.flac"],
            lambda cur, total: progress_calls.append((cur, total)),
        )

    assert mock_run.call_count == 2
    assert progress_calls == [(1, 2), (2, 2)]

    cmd1 = mock_run.call_args_list[0][0][0]
    assert cmd1[-1].endswith("track01.mp3")

    cmd2 = mock_run.call_args_list[1][0][0]
    assert cmd2[-1].endswith("track02.mp3")


def test_convert_files_raises_on_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "bad codec"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Error on file 1"):
            convert_files(["/music/track01.flac"], lambda c, t: None)


# --- delete_flacs ---

def test_delete_flacs_success():
    with tempfile.NamedTemporaryFile(suffix=".flac", delete=False) as f:
        path = f.name
    try:
        warning = delete_flacs([path])
        assert warning is None
        assert not Path(path).exists()
    finally:
        if Path(path).exists():
            os.unlink(path)


def test_delete_flacs_missing_file_returns_warning():
    warning = delete_flacs(["/nonexistent/file.flac"])
    assert warning is not None
    assert "file.flac" in warning
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
py -m pytest tests/test_converter.py -v
```

Expected: `ImportError` — `converter` not found.

- [ ] **Step 3: Implement converter.py**

Create `converter.py`:

```python
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from cue_parser import Track


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def split_and_convert(
    flac_path: str,
    tracks: List[Track],
    progress_callback: Callable[[int, int], None],
) -> None:
    """Split a single FLAC by CUE tracks and convert each to 320kbps MP3.

    progress_callback(current, total) is called before each track.
    Raises RuntimeError on ffmpeg failure.
    """
    flac = Path(flac_path)
    total = len(tracks)

    for i, track in enumerate(tracks, start=1):
        progress_callback(i, total)
        stem = f"{track.number:02d} - {track.title}"
        out = flac.parent / f"{stem}.mp3"

        cmd = ["ffmpeg", "-y", "-ss", str(track.start)]
        if track.end is not None:
            cmd += ["-to", str(track.end)]
        cmd += ["-i", str(flac), "-b:a", "320k", str(out)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Error on track {i}: {result.stderr.strip()}")


def convert_files(
    flac_paths: List[str],
    progress_callback: Callable[[int, int], None],
) -> None:
    """Convert one or more FLAC files to 320kbps MP3.

    progress_callback(current, total) is called before each file.
    Raises RuntimeError on ffmpeg failure.
    """
    total = len(flac_paths)

    for i, flac_path in enumerate(flac_paths, start=1):
        progress_callback(i, total)
        flac = Path(flac_path)
        out = flac.parent / (flac.stem + ".mp3")

        cmd = ["ffmpeg", "-y", "-i", str(flac), "-b:a", "320k", str(out)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Error on file {i} ({flac.name}): {result.stderr.strip()}"
            )


def delete_flacs(flac_paths: List[str]) -> Optional[str]:
    """Delete source FLAC files after successful conversion.

    Returns a warning string if any deletion fails, otherwise None.
    """
    failures = []
    for path in flac_paths:
        try:
            Path(path).unlink()
        except OSError as e:
            failures.append(f"{Path(path).name}: {e}")

    if failures:
        return "Warning: could not delete some FLACs: " + "; ".join(failures)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
py -m pytest tests/test_converter.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Run all tests**

```bash
py -m pytest tests/ -v
```

Expected: all 17 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add converter.py tests/test_converter.py
git commit -m "feat: add ffmpeg converter with tests"
```

---

## Task 4: GUI Module

**Files:**
- Create: `gui.py`
- Create: `tests/test_gui.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui.py`:

```python
import pytest
from gui import detect_mode, parse_drop_paths

MODE_SPLIT = "Split + Convert"
MODE_CONVERT = "Convert Only"


# --- detect_mode ---

def test_detect_mode_split():
    mode, flacs, cue, err = detect_mode(["/m/album.flac", "/m/album.cue"])
    assert mode == MODE_SPLIT
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert err is None


def test_detect_mode_convert_single():
    mode, flacs, cue, err = detect_mode(["/m/track01.flac"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track01.flac"]
    assert cue is None
    assert err is None


def test_detect_mode_convert_batch():
    paths = ["/m/t1.flac", "/m/t2.flac", "/m/t3.flac"]
    mode, flacs, cue, err = detect_mode(paths)
    assert mode == MODE_CONVERT
    assert len(flacs) == 3
    assert err is None


def test_detect_mode_cue_without_flac():
    mode, flacs, cue, err = detect_mode(["/m/album.cue"])
    assert mode is None
    assert "FLAC" in err


def test_detect_mode_unsupported_file():
    mode, flacs, cue, err = detect_mode(["/m/track.mp3"])
    assert mode is None
    assert "Unsupported" in err


def test_detect_mode_multiple_cues():
    mode, flacs, cue, err = detect_mode(["/m/a.flac", "/m/a.cue", "/m/b.cue"])
    assert mode is None
    assert err is not None


# --- parse_drop_paths ---

def test_parse_drop_paths_simple():
    assert parse_drop_paths("/path/to/file.flac") == ["/path/to/file.flac"]


def test_parse_drop_paths_multiple():
    result = parse_drop_paths("/path/a.flac /path/b.flac")
    assert result == ["/path/a.flac", "/path/b.flac"]


def test_parse_drop_paths_braces():
    result = parse_drop_paths("{/path/with spaces/file.flac}")
    assert result == ["/path/with spaces/file.flac"]


def test_parse_drop_paths_mixed():
    result = parse_drop_paths("{/path/with spaces/file.flac} /path/b.cue")
    assert result == ["/path/with spaces/file.flac", "/path/b.cue"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
py -m pytest tests/test_gui.py -v
```

Expected: `ImportError` — `gui` not found.

- [ ] **Step 3: Implement gui.py**

Create `gui.py`:

```python
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import List, Optional, Tuple

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from cue_parser import parse_cue
from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs

MODE_SPLIT = "Split + Convert"
MODE_CONVERT = "Convert Only"


def detect_mode(
    paths: List[str],
) -> Tuple[Optional[str], List[str], Optional[str], Optional[str]]:
    """Classify a list of file paths into a conversion mode.

    Returns (mode, flac_paths, cue_path, error_message).
    On error, mode is None and error_message is set.
    """
    flacs = [p for p in paths if p.lower().endswith(".flac")]
    cues = [p for p in paths if p.lower().endswith(".cue")]
    others = [
        p for p in paths
        if not p.lower().endswith(".flac") and not p.lower().endswith(".cue")
    ]

    if others:
        return None, [], None, "Unsupported file type"
    if cues and not flacs:
        return None, [], None, "Please also provide a FLAC file"
    if len(cues) > 1:
        return None, [], None, "Only one CUE file is supported at a time"
    if len(cues) == 1 and len(flacs) == 1:
        return MODE_SPLIT, flacs, cues[0], None
    if len(flacs) >= 1 and not cues:
        return MODE_CONVERT, flacs, None, None
    return None, [], None, "Invalid file selection"


def parse_drop_paths(data: str) -> List[str]:
    """Parse tkinterdnd2 drop data into a list of file paths.

    Paths containing spaces are wrapped in braces by tkinterdnd2:
    e.g.  {/path/with spaces/file.flac} /other/file.cue
    """
    paths = []
    data = data.strip()
    while data:
        if data.startswith("{"):
            end = data.index("}")
            paths.append(data[1:end])
            data = data[end + 1:].strip()
        else:
            parts = data.split(" ", 1)
            paths.append(parts[0])
            data = parts[1].strip() if len(parts) > 1 else ""
    return paths


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("FLAC to MP3 Converter")
        self.geometry("500x410")
        self.resizable(False, False)
        self.configure(bg="#1a1a1a")

        self._flac_paths: List[str] = []
        self._cue_path: Optional[str] = None
        self._mode: Optional[str] = None

        self._build_ui()

    def _build_ui(self) -> None:
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

        # Drag-and-drop targets
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

        # Delete checkbox
        self._delete_var = tk.BooleanVar(value=False)
        self._delete_check = ctk.CTkCheckBox(
            self,
            text="Delete FLAC after conversion",
            variable=self._delete_var,
            font=("Segoe UI", 11),
        )
        self._delete_check.place(x=20, y=245)

        # Convert button
        self._convert_btn = ctk.CTkButton(
            self,
            text="Convert",
            font=("Segoe UI", 13, "bold"),
            state="disabled",
            command=self._start_conversion,
        )
        self._convert_btn.place(x=20, y=295, width=460, height=45)

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
        self._status_label.place(x=20, y=350, width=460, height=40)

    def _on_drop(self, event) -> None:
        paths = parse_drop_paths(event.data)
        self._load_files(paths)

    def _browse(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select FLAC and/or CUE files",
            filetypes=[
                ("Audio/CUE files", "*.flac *.cue"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._load_files(list(paths))

    def _load_files(self, paths: List[str]) -> None:
        mode, flacs, cue, error = detect_mode(paths)
        if error:
            self._info_label.config(text=error, fg="#cc4444")
            self._convert_btn.configure(state="disabled")
            self._flac_paths = []
            self._cue_path = None
            self._mode = None
            return

        self._flac_paths = flacs
        self._cue_path = cue
        self._mode = mode

        names = ", ".join(Path(p).name for p in paths)
        self._info_label.config(
            text=f"{names}\nMode: {mode}",
            fg="#cccccc",
        )
        self._convert_btn.configure(state="normal")
        self._status_label.config(text="", fg="#88cc88")

    def _set_status(self, text: str, color: str = "#88cc88") -> None:
        self._status_label.config(text=text, fg=color)
        self.update_idletasks()

    def _start_conversion(self) -> None:
        if not check_ffmpeg():
            self._set_status(
                "ffmpeg not found. Please install it and ensure it's on your PATH.",
                "#cc4444",
            )
            return

        self._convert_btn.configure(state="disabled")
        self._set_status("Starting...", "#cccccc")

        thread = threading.Thread(target=self._run_conversion, daemon=True)
        thread.start()

    def _run_conversion(self) -> None:
        flacs_to_delete = self._flac_paths[:]
        try:
            if self._mode == MODE_SPLIT:
                tracks = parse_cue(self._cue_path)
                split_and_convert(
                    self._flac_paths[0],
                    tracks,
                    lambda cur, total: self.after(
                        0, self._set_status,
                        f"Converting track {cur} of {total}...", "#cccccc",
                    ),
                )
            else:
                convert_files(
                    self._flac_paths,
                    lambda cur, total: self.after(
                        0, self._set_status,
                        f"Converting file {cur} of {total}...", "#cccccc",
                    ),
                )

            if self._delete_var.get():
                warning = delete_flacs(flacs_to_delete)
                if warning:
                    self.after(0, self._set_status,
                               f"Done. {warning}", "#ccaa44")
                else:
                    self.after(0, self._set_status,
                               "Done. FLAC files deleted.", "#88cc88")
            else:
                self.after(0, self._set_status, "Done.", "#88cc88")

        except ValueError as e:
            self.after(0, self._set_status,
                       f"Could not parse CUE file: {e}", "#cc4444")
        except RuntimeError as e:
            self.after(0, self._set_status, str(e), "#cc4444")
        except Exception as e:
            self.after(0, self._set_status,
                       f"Unexpected error: {e}", "#cc4444")
        finally:
            self.after(0, lambda: self._convert_btn.configure(state="normal"))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
py -m pytest tests/test_gui.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
py -m pytest tests/ -v
```

Expected: all 27 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add gui.py tests/test_gui.py
git commit -m "feat: add GUI module with detect_mode and drop path parsing"
```

---

## Task 5: Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create main.py**

```python
from gui import App


if __name__ == "__main__":
    app = App()
    app.mainloop()
```

- [ ] **Step 2: Smoke test — launch the app**

```bash
py main.py
```

Expected: window opens with dark theme, drop zone visible, Convert button disabled.
Verify:
- Drag a `.flac` file onto the window → file info shows, mode is "Convert Only", Convert button enables
- Drag a `.flac` + `.cue` together → mode shows "Split + Convert"
- Drag an `.mp3` → error shown in red, button stays disabled
- Click the drop zone → file picker opens

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add entry point, app complete"
```

---

## Task 6: Packaging (Optional Convenience)

**Files:**
- Create: `run.bat`

- [ ] **Step 1: Create run.bat for easy launching**

Create `run.bat` in the project root:

```bat
@echo off
py "%~dp0main.py"
```

This lets the user double-click `run.bat` to launch the app without opening a terminal.

- [ ] **Step 2: Commit**

```bash
git add run.bat
git commit -m "chore: add run.bat launcher"
```
