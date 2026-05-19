import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, List, Optional

from cue_parser import Track

# Bundled ffmpeg lives in bin/ffmpeg.exe next to this file.
# Falls back to system PATH if the bundled copy is missing.
_LOCAL_FFMPEG = Path(__file__).parent / "bin" / "ffmpeg.exe"

# Suppress console window on Windows when spawning subprocesses.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Supported lossless / high-quality audio extensions that Hoarder can convert.
# ALAC uses .m4a (and rarely .alac); DSD uses .dsf (Sony) or .dff (Philips).
AUDIO_EXTS: frozenset[str] = frozenset({
    ".flac", ".alac", ".m4a", ".ape", ".aiff", ".aif", ".dsf", ".dff", ".wma",
})


def _ffmpeg_exe() -> str:
    """Return path to ffmpeg: bundled bin/ffmpeg.exe if present, else 'ffmpeg' (PATH)."""
    if _LOCAL_FFMPEG.exists():
        return str(_LOCAL_FFMPEG)
    return "ffmpeg"


_LOCAL_FFPROBE = Path(__file__).parent / "bin" / "ffprobe.exe"


def _ffprobe_exe() -> str:
    """Return path to ffprobe: bundled bin/ffprobe.exe if present, else 'ffprobe' (PATH)."""
    if _LOCAL_FFPROBE.exists():
        return str(_LOCAL_FFPROBE)
    return "ffprobe"


def probe_video(path: str) -> dict:
    """Probe a video file and return {codec, duration, size}.

    codec    — video codec name (e.g. 'h264', 'hevc', 'vp9')
    duration — total duration in seconds (float)
    size     — file size in bytes (int)

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


# ---------------------------------------------------------------------------
# HEVC encoder auto-detection (GPU > CPU fallback)
# ---------------------------------------------------------------------------

_ENCODER_VIDEO_ARGS: dict[str, list[str]] = {
    "hevc_nvenc": ["-c:v", "hevc_nvenc", "-rc:v", "vbr", "-cq:v", "28", "-preset:v", "p4"],
    "hevc_amf":   ["-c:v", "hevc_amf",   "-rc", "cqp", "-qp_i", "28", "-qp_p", "28", "-quality", "balanced"],
    "hevc_qsv":   ["-c:v", "hevc_qsv",   "-global_quality", "28", "-preset", "medium"],
    "libx265":    ["-c:v", "libx265",     "-crf", "28", "-preset", "medium"],
}

_hevc_encoder_cache: Optional[str] = None


def _detect_hevc_encoder() -> str:
    """Try GPU HEVC encoders in order; return first available, else 'libx265'."""
    ffmpeg = _ffmpeg_exe()
    for enc in ("hevc_nvenc", "hevc_amf", "hevc_qsv"):
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-f", "lavfi", "-i", "nullsrc=s=64x64:r=1",
             "-t", "0.1", "-c:v", enc, "-f", "null", "-"],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            return enc
    return "libx265"


def _get_hevc_encoder() -> str:
    """Lazily detect and cache the best available HEVC encoder."""
    global _hevc_encoder_cache
    if _hevc_encoder_cache is None:
        _hevc_encoder_cache = _detect_hevc_encoder()
    return _hevc_encoder_cache


def transcode_videos(
    video_paths: List[str],
    progress_callback: Callable[[float, int], None],
    delete_source: bool = False,
    encoder: Optional[str] = None,
    _run_full_fn: Optional[Callable] = None,
) -> None:
    """Transcode video files to H.265 MP4 with AAC audio.

    encoder: force a specific encoder (e.g. 'libx265', 'hevc_nvenc'); None = auto-detect GPU.
    Skips files already encoded as H.265 MP4.
    Skips files where predicted H.265 output would be larger than source.
    progress_callback(current, total) is called AFTER each file completes (including skips).
      current may be a float (i-1 + within-file fraction) to support sub-file progress.
    _run_full_fn: injectable replacement for _run_ffmpeg_progress (used in tests).
    Raises RuntimeError on ffmpeg failure.
    """
    import tempfile as _tempfile
    ffmpeg = _ffmpeg_exe()
    total = len(video_paths)
    enc = encoder if encoder is not None else _get_hevc_encoder()
    enc_video_args = _ENCODER_VIDEO_ARGS.get(enc, _ENCODER_VIDEO_ARGS["libx265"])

    for i, video_path in enumerate(video_paths, start=1):
        src = Path(video_path)

        info = probe_video(video_path)
        codec       = info["codec"]
        duration    = info["duration"]
        source_size = info["size"]

        # Skip if already H.265 MP4
        if src.suffix.lower() == ".mp4" and codec == "hevc":
            progress_callback(i, total)
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

        skip = False
        try:
            sample_cmd = (
                [ffmpeg, "-y", "-t", str(sample_duration), "-i", str(src)]
                + enc_video_args
                + ["-c:a", "aac", "-movflags", "+faststart", str(sample_path)]
            )
            _run_ffmpeg(sample_cmd, f"Sample transcode failed for {src.name}")

            sample_size = sample_path.stat().st_size
            predicted_size = (sample_size / sample_duration) * duration if duration > 0 else sample_size

            if predicted_size >= source_size:
                skip = True
        finally:
            if sample_path.exists():
                sample_path.unlink(missing_ok=True)

        if skip:
            progress_callback(i, total)
            continue

        # --- Full transcode ---
        full_cmd = (
            [ffmpeg, "-y", "-i", str(src)]
            + enc_video_args
            + ["-c:a", "aac", "-movflags", "+faststart", str(out)]
        )
        run_full = _run_full_fn if _run_full_fn is not None else _run_ffmpeg_progress
        on_pct: Callable[[float], None] = lambda pct: progress_callback(i - 1 + pct, total)
        run_full(full_cmd, duration, on_pct, f"Error transcoding {src.name}")

        if delete_source:
            try:
                src.unlink()
            except OSError:
                pass

        progress_callback(i, total)  # called AFTER work, not before


def _run_ffmpeg(cmd: List[str], error_prefix: str) -> None:
    """Run an ffmpeg command. Raises RuntimeError with error_prefix on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {result.stderr.strip()}")


def _run_ffmpeg_progress(
    cmd: List[str],
    duration: float,
    on_pct: Callable[[float], None],
    error_prefix: str,
) -> None:
    """Run ffmpeg with real-time per-file progress reporting.

    Injects ``-progress pipe:1 -nostats`` before the output argument (last
    element of *cmd*) so ffmpeg writes machine-readable progress to stdout.
    ``on_pct`` is called with a float in [0.0, 1.0] each time a new
    ``out_time_us=`` line is received.  stderr is drained in a daemon thread
    to prevent pipe-buffer deadlock.  Raises RuntimeError on non-zero exit.
    """
    modified_cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]

    proc = subprocess.Popen(
        modified_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=_NO_WINDOW,
    )

    stderr_lines: List[str] = []

    def _drain_stderr() -> None:
        for line in proc.stderr:
            stderr_lines.append(line)

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_us="):
            val = line.split("=", 1)[1].strip()
            try:
                us = int(val)
                if duration > 0:
                    pct = min(1.0, us / (duration * 1_000_000))
                    on_pct(pct)
            except ValueError:
                pass

    proc.wait()
    t.join(timeout=5)

    if proc.returncode != 0:
        stderr_text = "".join(stderr_lines).strip()
        raise RuntimeError(f"{error_prefix}: {stderr_text}")


def check_ffmpeg() -> bool:
    """Return True if ffmpeg is available (bundled bin/ or system PATH)."""
    if _LOCAL_FFMPEG.exists():
        return True
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
    ffmpeg = _ffmpeg_exe()
    flac = Path(flac_path)
    total = len(tracks)

    for i, track in enumerate(tracks, start=1):
        progress_callback(i, total)
        stem = f"{track.number:02d} - {track.title}"
        out = flac.parent / f"{stem}.mp3"

        cmd = [ffmpeg, "-y", "-ss", str(track.start)]
        if track.end is not None:
            cmd += ["-to", str(track.end)]
        cmd += ["-i", str(flac), "-b:a", "320k", str(out)]

        _run_ffmpeg(cmd, f"Error on track {i}")


def convert_files(
    flac_paths: List[str],
    progress_callback: Callable[[int, int], None],
) -> None:
    """Convert one or more FLAC files to 320kbps MP3.

    progress_callback(current, total) is called before each file.
    Raises RuntimeError on ffmpeg failure.
    """
    ffmpeg = _ffmpeg_exe()
    total = len(flac_paths)

    for i, flac_path in enumerate(flac_paths, start=1):
        progress_callback(i, total)
        flac = Path(flac_path)
        out = flac.parent / (flac.stem + ".mp3")

        cmd = [ffmpeg, "-y", "-i", str(flac), "-b:a", "320k", str(out)]
        _run_ffmpeg(cmd, f"Error on file {i} ({flac.name})")


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


def delete_companion_files(
    flac_paths: List[str],
    cue_path: Optional[str] = None,
) -> None:
    """Delete companion files (.cue, .log, .m3u, .txt) left after conversion.

    1. Removes the explicit *cue_path* if provided.
    2. For each audio file, deletes the same-stem .log, .m3u, and .txt
       (e.g. album.flac → album.log, album.m3u, album.txt).
    3. Scans each audio file's parent directory for *orphaned* .log, .m3u,
       and .txt files — those whose corresponding audio file does not exist
       on disk and whose stem was not among the passed files.  These are
       album-level artefacts (rip logs, playlists, notes) that have no
       natural stem partner but should still be cleaned up.

    Crucially, a sibling disc's companions are NOT orphaned while its audio
    file still exists, so multi-disc folders are handled safely.
    """
    _COMPANION_EXTS = (".log", ".m3u", ".txt")

    if cue_path:
        try:
            Path(cue_path).unlink(missing_ok=True)
        except OSError:
            pass

    handled_stems: set[str] = set()
    for flac_path_str in flac_paths:
        flac = Path(flac_path_str)
        handled_stems.add(flac.stem.lower())
        for ext in _COMPANION_EXTS:
            companion = flac.with_suffix(ext)
            if companion.exists():
                try:
                    companion.unlink(missing_ok=True)
                except OSError:
                    pass

    # Delete orphaned companion files — no matching audio file on disk and stem
    # not already handled above (those are gone because delete_flacs ran first).
    dirs: set[Path] = set(Path(p).parent for p in flac_paths)
    for d in dirs:
        for ext in _COMPANION_EXTS:
            for companion in d.glob(f"*{ext}"):
                stem = companion.stem.lower()
                if stem in handled_stems:
                    continue
                # Preserve if any supported audio file with the same stem still
                # exists (e.g. sibling disc's .ape/.flac not yet converted)
                has_counterpart = any(
                    (companion.parent / (companion.stem + a)).exists()
                    for a in AUDIO_EXTS
                )
                if not has_counterpart:
                    try:
                        companion.unlink(missing_ok=True)
                    except OSError:
                        pass
