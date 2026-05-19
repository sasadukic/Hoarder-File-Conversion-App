# Video Transcoding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Hoarder to transcode MP4/MKV/MOV/WMV/AVI files to H.265 MP4 with AAC audio, skipping files already in H.265 or where the output would be larger than the source.

**Architecture:** Extend `detect_mode` to classify video files alongside audio, add `probe_video` + `transcode_videos` to `converter.py`, update `_run_conversion` in `gui.py` to handle both audio and video batches, and teach the monitor and folder scanner about video extensions.

**Tech Stack:** Python 3.14, ffmpeg/ffprobe (bundled in `bin/`), customtkinter, watchdog

---

## Files Touched

| File | Change |
|------|--------|
| `gui.py` | New constants `MODE_VIDEO`/`MODE_MIXED`/`VIDEO_EXTS`; update `detect_mode` (5-tuple return), `expand_drops`, `_load_files`, `_run_conversion`, `_video_paths` state, `_scan_existing_files` (renamed) |
| `converter.py` | Add `_LOCAL_FFPROBE`, `_ffprobe_exe`, `probe_video`, `transcode_videos` |
| `monitor.py` | `_handle_path` triggers on video extensions too |
| `tests/test_gui.py` | Update all `detect_mode` call sites (4-tuple → 5-tuple); add video tests |
| `tests/test_converter.py` | Add `probe_video` and `transcode_videos` tests |

---

## Task 1: Update `detect_mode` to return 5-tuple and classify video files

**Files:**
- Modify: `gui.py`
- Modify: `tests/test_gui.py`

- [ ] **Step 1: Write failing tests for new detect_mode signature**

Add to `tests/test_gui.py` (replace the import line and add tests at the bottom):

```python
# update import at top of file:
from gui import detect_mode, parse_drop_paths, expand_drops, MODE_SPLIT, MODE_CONVERT, MODE_VIDEO, MODE_MIXED

def test_detect_mode_video_only():
    mode, flacs, cue, videos, err = detect_mode(["/m/movie.mkv"])
    assert mode == MODE_VIDEO
    assert flacs == []
    assert cue is None
    assert videos == ["/m/movie.mkv"]
    assert err is None

def test_detect_mode_video_only_mp4():
    mode, flacs, cue, videos, err = detect_mode(["/m/clip.mp4", "/m/clip2.avi"])
    assert mode == MODE_VIDEO
    assert sorted(videos) == ["/m/clip.mp4", "/m/clip2.avi"]
    assert err is None

def test_detect_mode_mixed_audio_and_video():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/movie.mkv"])
    assert mode == MODE_MIXED
    assert flacs == ["/m/album.flac"]
    assert cue is None
    assert videos == ["/m/movie.mkv"]
    assert err is None

def test_detect_mode_mixed_split_and_video():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/album.cue", "/m/movie.mkv"])
    assert mode == MODE_MIXED
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert videos == ["/m/movie.mkv"]
    assert err is None

def test_detect_mode_video_unsupported_mix():
    mode, flacs, cue, videos, err = detect_mode(["/m/movie.mkv", "/m/audio.mp3"])
    assert mode is None
    assert "Unsupported" in err
```

Also update all existing `detect_mode` tests to unpack 5-tuple:

```python
def test_detect_mode_split():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.flac", "/m/album.cue"])
    assert mode == MODE_SPLIT
    assert flacs == ["/m/album.flac"]
    assert cue == "/m/album.cue"
    assert videos == []
    assert err is None

def test_detect_mode_convert_single():
    mode, flacs, cue, videos, err = detect_mode(["/m/track01.flac"])
    assert mode == MODE_CONVERT
    assert flacs == ["/m/track01.flac"]
    assert cue is None
    assert videos == []
    assert err is None

def test_detect_mode_convert_batch():
    paths = ["/m/t1.flac", "/m/t2.flac", "/m/t3.flac"]
    mode, flacs, cue, videos, err = detect_mode(paths)
    assert mode == MODE_CONVERT
    assert len(flacs) == 3
    assert videos == []
    assert err is None

def test_detect_mode_cue_without_flac():
    mode, flacs, cue, videos, err = detect_mode(["/m/album.cue"])
    assert mode is None
    assert "FLAC" in err

def test_detect_mode_unsupported_file():
    mode, flacs, cue, videos, err = detect_mode(["/m/track.mp3"])
    assert mode is None
    assert "Unsupported" in err

def test_detect_mode_multiple_cues():
    mode, flacs, cue, videos, err = detect_mode(["/m/a.flac", "/m/a.cue", "/m/b.cue"])
    assert mode is None
    assert "CUE" in err

def test_detect_mode_cue_with_multiple_flacs():
    mode, flacs, cue, videos, err = detect_mode(["/m/a.flac", "/m/b.flac", "/m/album.cue"])
    assert mode == MODE_CONVERT
    assert sorted(flacs) == ["/m/a.flac", "/m/b.flac"]
    assert cue is None
    assert videos == []
    assert err is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:\Users\psilo\Desktop\Audio Convert"
py -m pytest tests/test_gui.py -q
```
Expected: multiple failures — `MODE_VIDEO`, `MODE_MIXED` not importable, 4-tuple unpacking errors.

- [ ] **Step 3: Update `detect_mode` in `gui.py`**

Replace the constants and function at the top of `gui.py`:

```python
MODE_SPLIT  = "Split + Convert"
MODE_CONVERT = "Convert Only"
MODE_VIDEO  = "Video Transcode"
MODE_MIXED  = "Mixed"

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".wmv", ".avi"}
```

Replace the `detect_mode` function body:

```python
def detect_mode(
    paths: List[str],
) -> Tuple[Optional[str], List[str], Optional[str], List[str], Optional[str]]:
    """Classify a list of file paths into a conversion mode.

    Returns (mode, flac_paths, cue_path, video_paths, error_message).
    On error, mode is None and error_message is set.
    """
    flacs  = [p for p in paths if p.lower().endswith(".flac")]
    cues   = [p for p in paths if p.lower().endswith(".cue")]
    videos = [p for p in paths if Path(p).suffix.lower() in VIDEO_EXTS]
    others = [
        p for p in paths
        if not p.lower().endswith(".flac")
        and not p.lower().endswith(".cue")
        and Path(p).suffix.lower() not in VIDEO_EXTS
    ]

    if others:
        return None, [], None, [], "Unsupported file type"
    if cues and not flacs and not videos:
        return None, [], None, [], "Please also provide a FLAC file"
    if len(cues) > 1:
        return None, [], None, [], "Only one CUE file is supported at a time"

    # Determine audio mode
    audio_mode: Optional[str] = None
    audio_cue: Optional[str] = None
    if len(cues) == 1 and len(flacs) == 1:
        audio_mode = MODE_SPLIT
        audio_cue = cues[0]
    elif len(cues) == 1 and len(flacs) > 1:
        audio_mode = MODE_CONVERT  # ignore CUE, convert FLACs
    elif flacs:
        audio_mode = MODE_CONVERT

    has_audio = audio_mode is not None
    has_video = len(videos) > 0

    if has_audio and has_video:
        mode = MODE_MIXED
    elif has_audio:
        mode = audio_mode  # type: ignore[assignment]
    elif has_video:
        mode = MODE_VIDEO
    else:
        return None, [], None, [], "Invalid file selection"

    return mode, flacs, audio_cue, videos, None
```

Also update `_load_files` in `gui.py` to unpack the 5-tuple:

```python
def _load_files(self, paths: List[str]) -> None:
    mode, flacs, cue, videos, error = detect_mode(paths)
    if error:
        self._info_label.config(text=error, fg=WARM)
        self._convert_btn.configure(state="disabled")
        self._flac_paths = []
        self._cue_path = None
        self._mode = None
        self._video_paths = []
        return

    self._flac_paths = flacs
    self._cue_path = cue
    self._mode = mode
    self._video_paths = videos

    self._info_label.config(text="Files loaded", fg=SAGE)
    self._convert_btn.configure(state="normal", text="Convert")

    if self._auto_convert_var.get():
        self._start_conversion()
```

Add `self._video_paths: List[str] = []` to `App.__init__` alongside `self._flac_paths`.

- [ ] **Step 4: Run tests to verify they pass**

```
py -m pytest tests/test_gui.py -q
```
Expected: all gui tests pass.

- [ ] **Step 5: Run full suite**

```
py -m pytest tests/ -q
```
Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```
git add gui.py tests/test_gui.py
git commit -m "feat: extend detect_mode to classify video files (5-tuple return)"
```

---

## Task 2: Update `expand_drops` to include video extensions

**Files:**
- Modify: `gui.py`
- Modify: `tests/test_gui.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_gui.py`:

```python
def test_expand_drops_includes_video_extensions(tmp_path):
    (tmp_path / "movie.mp4").touch()
    (tmp_path / "clip.mkv").touch()
    (tmp_path / "audio.flac").touch()
    (tmp_path / "cover.jpg").touch()  # ignored
    result = expand_drops([str(tmp_path)])
    assert str(tmp_path / "movie.mp4") in result
    assert str(tmp_path / "clip.mkv") in result
    assert str(tmp_path / "audio.flac") in result
    assert not any("cover.jpg" in r for r in result)
```

- [ ] **Step 2: Run test to verify it fails**

```
py -m pytest tests/test_gui.py::test_expand_drops_includes_video_extensions -v
```
Expected: FAIL — video files not included.

- [ ] **Step 3: Update `expand_drops` in `gui.py`**

```python
def expand_drops(paths: List[str]) -> List[str]:
    """Expand any dropped folders into their contained FLAC, CUE, and video files."""
    _video_globs = ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi")
    result = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            result.extend(str(f) for f in sorted(path.glob("*.flac")))
            result.extend(str(f) for f in sorted(path.glob("*.cue")))
            for pat in _video_globs:
                result.extend(str(f) for f in sorted(path.glob(pat)))
        else:
            result.append(p)
    return result
```

- [ ] **Step 4: Run tests**

```
py -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add gui.py tests/test_gui.py
git commit -m "feat: expand_drops includes video file extensions"
```

---

## Task 3: Add `probe_video` to `converter.py`

**Files:**
- Modify: `converter.py`
- Modify: `tests/test_converter.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_converter.py`:

```python
import json
from converter import probe_video

def test_probe_video_returns_codec_duration_size():
    fake_output = json.dumps({
        "streams": [
            {"codec_type": "audio", "codec_name": "aac"},
            {"codec_type": "video", "codec_name": "h264"},
        ],
        "format": {
            "duration": "120.5",
            "size": "50000000",
        }
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_output

    with patch("converter.subprocess.run", return_value=mock_result):
        info = probe_video("/m/video.mp4")

    assert info["codec"] == "h264"
    assert info["duration"] == pytest.approx(120.5)
    assert info["size"] == 50_000_000

def test_probe_video_hevc_codec():
    fake_output = json.dumps({
        "streams": [{"codec_type": "video", "codec_name": "hevc"}],
        "format": {"duration": "60.0", "size": "20000000"},
    })
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_output

    with patch("converter.subprocess.run", return_value=mock_result):
        info = probe_video("/m/video.mp4")

    assert info["codec"] == "hevc"

def test_probe_video_raises_on_ffprobe_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "no such file"

    with patch("converter.subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="ffprobe failed"):
            probe_video("/m/missing.mp4")
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -m pytest tests/test_converter.py::test_probe_video_returns_codec_duration_size -v
```
Expected: FAIL — `probe_video` not defined.

- [ ] **Step 3: Implement `probe_video` in `converter.py`**

Add after the existing imports at the top:

```python
import json
```

Add after `_LOCAL_FFMPEG` and `_ffmpeg_exe`:

```python
_LOCAL_FFPROBE = Path(__file__).parent / "bin" / "ffprobe.exe"


def _ffprobe_exe() -> str:
    """Return path to ffprobe: bundled bin/ffprobe.exe if present, else 'ffprobe' (PATH)."""
    if _LOCAL_FFPROBE.exists():
        return str(_LOCAL_FFPROBE)
    return "ffprobe"


def probe_video(path: str) -> dict:
    """Probe a video file and return {codec, duration, size}.

    codec   — video codec name (e.g. 'h264', 'hevc', 'vp9')
    duration — total duration in seconds (float)
    size    — file size in bytes (int)

    Raises RuntimeError if ffprobe fails.
    """
    cmd = [
        _ffprobe_exe(), "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

    data = json.loads(result.stdout)

    codec = "unknown"
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            codec = stream.get("codec_name", "unknown")
            break

    duration = float(data.get("format", {}).get("duration", 0))
    size = int(data.get("format", {}).get("size", 0))

    return {"codec": codec, "duration": duration, "size": size}
```

- [ ] **Step 4: Run tests**

```
py -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add converter.py tests/test_converter.py
git commit -m "feat: add probe_video using ffprobe"
```

---

## Task 4: Add `transcode_videos` to `converter.py`

**Files:**
- Modify: `converter.py`
- Modify: `tests/test_converter.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_converter.py`:

```python
from converter import transcode_videos

def _make_probe(codec="h264", duration=120.0, size=50_000_000):
    return {"codec": codec, "duration": duration, "size": size}

def test_transcode_skips_hevc_mp4(tmp_path):
    """Already H.265 MP4 must be skipped — ffmpeg never called."""
    video = tmp_path / "already.mp4"
    video.touch()
    progress_calls = []

    with patch("converter.probe_video", return_value=_make_probe(codec="hevc")):
        with patch("converter.subprocess.run") as mock_run:
            transcode_videos(
                [str(video)],
                lambda cur, total: progress_calls.append((cur, total)),
                delete_source=False,
            )

    mock_run.assert_not_called()
    assert progress_calls == [(1, 1)]

def test_transcode_skips_when_predicted_larger(tmp_path):
    """Sample output is larger than source — skip full transcode."""
    video = tmp_path / "big.mkv"
    video.write_bytes(b"x" * 10_000_000)  # 10 MB source

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    # sample file will be written to temp dir; we make it appear large
    def fake_run(cmd, **kwargs):
        # write a large sample file if -t flag is present (sample transcode)
        if "-t" in cmd:
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"x" * 12_000_000)  # > source
        return mock_ok

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=10_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run) as mock_run:
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
            )

    # Only the sample transcode ran, not the full transcode
    full_transcode_calls = [c for c in mock_run.call_args_list if "-t" not in c[0][0]]
    assert len(full_transcode_calls) == 0

def test_transcode_runs_full_when_sample_passes(tmp_path):
    """Sample output is smaller — full transcode runs, output file is created."""
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x" * 50_000_000)  # 50 MB source
    out_path = tmp_path / "movie.mp4"

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1])
        if "-t" in cmd:
            out.write_bytes(b"x" * 1_000_000)   # small sample = will pass
        else:
            out.write_bytes(b"x" * 20_000_000)  # full output
        return mock_ok

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
            )

    assert out_path.exists()

def test_transcode_deletes_source_when_flag_set(tmp_path):
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x" * 50_000_000)

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"x" * 1_000_000)
        return mock_ok

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=True,
            )

    assert not video.exists()

def test_transcode_mp4_source_gets_hevc_suffix(tmp_path):
    """MP4 source → output is <stem>.hevc.mp4 to avoid collision."""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 50_000_000)
    expected_out = tmp_path / "clip.hevc.mp4"

    mock_ok = MagicMock()
    mock_ok.returncode = 0

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"x" * 1_000_000)
        return mock_ok

    with patch("converter.probe_video", return_value=_make_probe(codec="h264", duration=120.0, size=50_000_000)):
        with patch("converter.subprocess.run", side_effect=fake_run):
            transcode_videos(
                [str(video)],
                lambda cur, total: None,
                delete_source=False,
            )

    assert expected_out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
py -m pytest tests/test_converter.py::test_transcode_skips_hevc_mp4 -v
```
Expected: FAIL — `transcode_videos` not defined.

- [ ] **Step 3: Implement `transcode_videos` in `converter.py`**

Add after `probe_video`:

```python
def transcode_videos(
    video_paths: List[str],
    progress_callback: Callable[[int, int], None],
    delete_source: bool = False,
) -> None:
    """Transcode video files to H.265 MP4 with AAC audio.

    Skips files already encoded as H.265 MP4.
    Skips files where the predicted H.265 output would be larger than the source.
    progress_callback(current, total) is called for each file (including skipped ones).
    Raises RuntimeError on ffmpeg failure.
    """
    import tempfile as _tempfile
    ffmpeg = _ffmpeg_exe()
    total = len(video_paths)

    for i, video_path in enumerate(video_paths, start=1):
        progress_callback(i, total)
        src = Path(video_path)

        info = probe_video(video_path)
        codec    = info["codec"]
        duration = info["duration"]
        source_size = info["size"]

        # Skip if already H.265 MP4
        if src.suffix.lower() == ".mp4" and codec == "hevc":
            continue

        # Determine output path (avoid overwriting source if already .mp4)
        if src.suffix.lower() == ".mp4":
            out = src.parent / (src.stem + ".hevc.mp4")
        else:
            out = src.parent / (src.stem + ".mp4")

        # --- Size check: transcode a short sample ---
        sample_duration = min(duration, 30.0) if duration > 0 else 30.0
        tmp_dir = Path(_tempfile.gettempdir())
        sample_path = tmp_dir / f"hoarder_sample_{src.stem}.mp4"

        try:
            sample_cmd = [
                ffmpeg, "-y",
                "-t", str(sample_duration),
                "-i", str(src),
                "-c:v", "libx265", "-crf", "28",
                "-c:a", "aac", "-movflags", "+faststart",
                str(sample_path),
            ]
            _run_ffmpeg(sample_cmd, f"Sample transcode failed for {src.name}")

            sample_size = sample_path.stat().st_size
            predicted_size = (sample_size / sample_duration) * duration if duration > 0 else sample_size

            if predicted_size >= source_size:
                continue  # output would be larger — skip
        finally:
            if sample_path.exists():
                sample_path.unlink(missing_ok=True)

        # --- Full transcode ---
        full_cmd = [
            ffmpeg, "-y",
            "-i", str(src),
            "-c:v", "libx265", "-crf", "28",
            "-c:a", "aac", "-movflags", "+faststart",
            str(out),
        ]
        _run_ffmpeg(full_cmd, f"Error transcoding {src.name}")

        if delete_source:
            try:
                src.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Run tests**

```
py -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add converter.py tests/test_converter.py
git commit -m "feat: add transcode_videos with skip logic"
```

---

## Task 5: Wire video transcoding into `gui.py` `_run_conversion`

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Update import in `gui.py`**

Change the converter import line:

```python
from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs, transcode_videos
```

- [ ] **Step 2: Update `_run_conversion` in `gui.py`**

Replace the entire `_run_conversion` method:

```python
def _run_conversion(self) -> None:
    # Capture all mutable state now to avoid races with _load_files
    flacs     = self._flac_paths[:]
    cue       = self._cue_path
    mode      = self._mode
    videos    = self._video_paths[:]
    do_delete = self._delete_var.get()

    # Compute grand total for unified progress
    audio_units = 0
    if flacs:
        if cue:
            try:
                from cue_parser import parse_cue as _pc
                audio_units = len(_pc(cue))
            except Exception:
                audio_units = 1
        else:
            audio_units = len(flacs)
    video_units = len(videos)
    grand_total = max(audio_units + video_units, 1)
    completed = [0]

    def on_audio_progress(cur: int, total: int) -> None:
        completed[0] = cur
        pct = int(completed[0] / grand_total * 100)
        self.after(0, self._set_status, f"Conversion Running {pct}%")

    def on_video_progress(cur: int, total: int) -> None:
        pct = int((audio_units + cur) / grand_total * 100)
        self.after(0, self._set_status, f"Conversion Running {pct}%")

    try:
        # --- Audio ---
        if flacs:
            if cue:
                tracks = parse_cue(cue)
                split_and_convert(flacs[0], tracks, on_audio_progress)
            else:
                convert_files(flacs, on_audio_progress)
            if do_delete:
                delete_flacs(flacs)

        # --- Video ---
        if videos:
            transcode_videos(videos, on_video_progress, delete_source=do_delete)

        # Done message
        self.after(0, self._play_done)
        self.after(0, self._set_status, "Done.")
        if do_delete:
            self.after(3000, self._reset_ui)

    except ValueError as e:
        self.after(0, self._set_status, f"Could not parse CUE file: {e}")
    except RuntimeError as e:
        self.after(0, self._set_status, str(e))
    except Exception as e:
        self.after(0, self._set_status, f"Unexpected error: {e}")
    finally:
        self._is_converting = False
        self.after(0, lambda: self._convert_btn.configure(state="normal"))
```

- [ ] **Step 3: Run full test suite**

```
py -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 4: Commit**

```
git add gui.py
git commit -m "feat: wire transcode_videos into _run_conversion with unified progress"
```

---

## Task 6: Update monitor to watch for video files

**Files:**
- Modify: `monitor.py`
- Modify: `gui.py` (`_scan_existing_files`)

- [ ] **Step 1: Update `_handle_path` in `monitor.py`**

Replace the `_handle_path` method to also trigger on video extensions:

```python
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".wmv", ".avi"}

class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[List[str]], None], inflight: Set[str], lock: threading.Lock):
        self._callback = callback
        self._inflight = inflight
        self._lock = lock

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_path(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle_path(Path(event.dest_path))

    def _handle_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix != ".flac" and suffix not in _VIDEO_EXTS:
            return
        key = str(path)
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(target=self._process, args=(path,), daemon=True).start()

    def _process(self, src: Path) -> None:
        try:
            if not _wait_stable(src):
                return
            paths = [str(src)]
            # For FLAC files, also include a same-stem CUE if present
            if src.suffix.lower() == ".flac":
                cue = src.with_suffix(".cue")
                if cue.exists():
                    paths.append(str(cue))
            self._callback(paths)
        finally:
            with self._lock:
                self._inflight.discard(str(src))
```

- [ ] **Step 2: Rename and update `_scan_existing_flacs` in `gui.py`**

Rename `_scan_existing_flacs` to `_scan_existing_files` and extend it to scan for video files:

```python
def _scan_existing_files(self, folder: str) -> None:
    """Trigger conversion for FLAC and video files already in the monitored folder."""
    folder_path = Path(folder)

    # --- Audio ---
    all_flacs = sorted(folder_path.rglob("*.flac"))
    paired: set[Path] = set()
    for flac in all_flacs:
        cue = flac.with_suffix(".cue")
        if cue.exists():
            self.after(0, self._load_and_auto_convert, [str(flac), str(cue)])
            paired.add(flac)
    lone_audio = [str(f) for f in all_flacs if f not in paired]
    if lone_audio:
        self.after(0, self._load_and_auto_convert, lone_audio)

    # --- Video ---
    video_exts = ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi")
    all_videos: list[Path] = []
    for pat in video_exts:
        all_videos.extend(sorted(folder_path.rglob(pat)))
    if all_videos:
        self.after(0, self._load_and_auto_convert, [str(v) for v in all_videos])
```

- [ ] **Step 3: Update the call site** — `_start_monitor` calls `_scan_existing_flacs`; rename it:

```python
def _start_monitor(self, folder: str) -> None:
    self._stop_monitor()
    if not Path(folder).is_dir():
        self._monitor_folder_var.set("")
        self._monitor_var.set(False)
        return
    self._monitor = mmod.FolderMonitor(folder, self._on_monitor_files)
    try:
        self._monitor.start()
        self._scan_existing_files(folder)   # <-- renamed
    except Exception as e:
        self._set_status(f"Monitor error: {e}")
        self._monitor_var.set(False)
        self._monitor = None
```

- [ ] **Step 4: Run full test suite**

```
py -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```
git add monitor.py gui.py
git commit -m "feat: monitor watches video files; scan_existing_files includes video"
```

---

## Task 7: Final smoke-test

- [ ] **Step 1: Run full test suite one last time**

```
py -m pytest tests/ -q
```
Expected: all tests pass (should be 60+).

- [ ] **Step 2: Launch the app**

```
py main.py
```

Verify:
- Drop a `.mkv` → button enables, "Files loaded" shown
- Click Convert → "Conversion Running X%" updates, "Done." on finish
- Drop a `.flac` + `.mkv` together → both converted in sequence
- Drop a folder containing mixed files → all converted

- [ ] **Step 3: Final commit**

```
git add -A
git commit -m "feat: video transcoding to H.265 MP4 complete"
```
