import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from cue_parser import Track

# Bundled ffmpeg lives in bin/ffmpeg.exe next to this file.
# Falls back to system PATH if the bundled copy is missing.
_LOCAL_FFMPEG = Path(__file__).parent / "bin" / "ffmpeg.exe"


def _ffmpeg_exe() -> str:
    """Return path to ffmpeg: bundled bin/ffmpeg.exe if present, else 'ffmpeg' (PATH)."""
    if _LOCAL_FFMPEG.exists():
        return str(_LOCAL_FFMPEG)
    return "ffmpeg"


def _run_ffmpeg(cmd: List[str], error_prefix: str) -> None:
    """Run an ffmpeg command. Raises RuntimeError with error_prefix on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {result.stderr.strip()}")


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
