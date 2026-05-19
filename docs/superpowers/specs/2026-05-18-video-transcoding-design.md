# Video Transcoding Feature — Design Spec
**Date:** 2026-05-18  
**Project:** Hoarder (Audio Convert)

---

## Overview

Extend the app to transcode video files to MP4/H.265 (HEVC) with AAC audio, using the same drop-zone, monitor, auto-convert, and delete-after-conversion workflow already in place for audio.

---

## Supported Input Formats

`.mp4`, `.mkv`, `.mov`, `.wmv`, `.avi`

---

## Output

- Container: MP4
- Video codec: H.265 (libx265), CRF 28
- Audio codec: AAC
- ffmpeg flags: `-c:v libx265 -crf 28 -c:a aac -movflags +faststart`
- Output location: same folder as source
- Output filename: `<stem>.mp4`
  - If source is already `.mp4`: `<stem>.hevc.mp4` (avoids collision)

---

## Skip Conditions

Both checks use `ffprobe` (bundled with ffmpeg at `bin/ffprobe.exe` or system PATH).

### 1. Already H.265 MP4
If `container == .mp4` AND `codec_name == hevc` → skip, no transcode.

### 2. Predicted Output Larger Than Source
- Transcode first 30 seconds (or full file if shorter) to a temp file
- Measure temp file size; extrapolate: `predicted = (temp_size / min(duration, 30)) * duration`
- If `predicted >= source_size` → delete temp file, skip
- If `predicted < source_size` → keep temp file as the start of the real output, continue transcoding the remainder by seeking to 30s and appending — OR simply re-transcode the full file discarding the sample (simpler, no ffmpeg concat complexity)

**Decision:** Re-transcode the full file if the sample passes. The 30s sample is used only for the size check and then discarded. This avoids ffmpeg concat complexity and edge cases.

---

## File Classification

### `detect_mode` (updated)
- Audio-only (FLAC ± CUE): unchanged behaviour
- Video-only: returns `MODE_VIDEO`
- Mixed audio + video: classifies each independently; returns `MODE_MIXED`
- `detect_mode` returns `(mode, flac_paths, cue_path, video_paths, error)`

### `expand_drops` (updated)
Folders are expanded to include video extensions alongside `.flac` and `.cue`.

### New constant
```python
MODE_VIDEO = "Video Transcode"
MODE_MIXED = "Mixed"
```

---

## App State (gui.py)

New field: `self._video_paths: List[str]`

`_load_files` populates both `_flac_paths` / `_cue_path` and `_video_paths` from `detect_mode`.

---

## Conversion Pipeline (converter.py)

### `probe_video(path) -> dict`
Runs `ffprobe -v quiet -print_format json -show_streams -show_format <path>`.  
Returns `{codec: str, duration: float, size: int}`.  
`ffprobe` is resolved from `bin/ffprobe.exe` if present, otherwise falls back to system PATH. The implementation plan must include downloading/bundling `ffprobe.exe` alongside `ffmpeg.exe`.

### `transcode_videos(paths, progress_callback, delete_source) -> None`
For each video file:
1. `probe_video` → get codec, duration, size
2. If already H.265 MP4 → skip (call `progress_callback(i, total)`, continue)
3. Transcode first `min(duration, 30)` seconds to `<stem>.sample.mp4` in system temp
4. Extrapolate predicted size
5. If predicted >= source size → delete sample, skip
6. Delete sample; transcode full file to final output path
7. If `delete_source` → delete source file

Progress callback: `(current_file_index, total_files)` — same signature as audio callbacks.

---

## `_run_conversion` (gui.py)

```
1. If audio files present → run audio conversion (split or convert)
2. If video files present → run transcode_videos(...)
3. Progress counts all files across both batches as one total
```

---

## Monitor

`_scan_existing_files` (renamed from `_scan_existing_flacs`) scans for both FLAC/CUE and video files.  
`_Handler._handle_path` in `monitor.py` also triggers on video extensions.

---

## UI Changes

- `expand_drops`: add video extensions to folder expansion
- Info label: "Files loaded" (no change)
- Button progress: `Conversion Running X%` counts all files (audio + video)
- "Delete file after conversion" applies to video source files (label already correct)
- No new checkboxes or settings

---

## Testing

New tests in `test_converter.py`:
- `test_probe_video_returns_codec_duration_size` (mocked ffprobe)
- `test_transcode_skips_hevc_mp4`
- `test_transcode_skips_when_predicted_larger`
- `test_transcode_runs_full_when_sample_passes`

New tests in `test_gui.py`:
- `test_detect_mode_video_only`
- `test_detect_mode_mixed_audio_and_video`
- `test_expand_drops_includes_video_extensions`

---

## Out of Scope

- Subtitle handling
- Hardware acceleration (NVENC, QuickSync)
- Custom CRF / bitrate settings UI
- Batch queue with per-file status
