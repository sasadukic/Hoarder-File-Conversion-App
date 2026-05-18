import dataclasses
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
                tracks[-1] = dataclasses.replace(tracks[-1], end=start)
            tracks.append(Track(
                number=current_num,
                title=current_title or f"Track {current_num:02d}",
                start=start,
                end=None,
            ))

    if not tracks:
        raise ValueError("No tracks found in CUE file")

    return tracks
