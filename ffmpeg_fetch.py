"""Downloads a static ffmpeg/ffprobe build for Windows on demand.

Hoarder no longer bundles ffmpeg.exe/ffprobe.exe (~100 MB each) in the
installer. Instead, the first conversion that needs them triggers a
download of a static build, cached in %LOCALAPPDATA%\\Hoarder\\bin so every
run after that finds them locally without touching the network again.
"""

import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

# gyan.dev is the Windows build ffmpeg.org's own download page links to.
# This URL always resolves to the current release build (no version to pin
# or track) and contains ffmpeg.exe + ffprobe.exe under a versioned bin/
# subfolder inside the zip.
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

_USER_AGENT = "Hoarder-ffmpeg-fetch/1.0"


def cache_dir() -> Path:
    """Where downloaded ffmpeg/ffprobe live.

    Independent of the app's install location so it survives reinstalls or
    updates to Program Files, and needs no elevated write access.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Hoarder" / "bin"


def cached_ffmpeg() -> Path:
    return cache_dir() / "ffmpeg.exe"


def cached_ffprobe() -> Path:
    return cache_dir() / "ffprobe.exe"


def is_cached() -> bool:
    return cached_ffmpeg().exists() and cached_ffprobe().exists()


def download(on_progress: Optional[Callable[[float], None]] = None) -> None:
    """Download and extract ffmpeg.exe + ffprobe.exe into cache_dir().

    Raises OSError/URLError on a network failure, zipfile.BadZipFile on a
    corrupt download, or RuntimeError if the expected binaries aren't found
    inside the archive — callers decide how to surface these.
    """
    dest_dir = cache_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        _download_file(FFMPEG_DOWNLOAD_URL, zip_path, on_progress)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            ffmpeg_member = _find_member(names, "bin/ffmpeg.exe")
            ffprobe_member = _find_member(names, "bin/ffprobe.exe")
            _extract_atomic(zf, ffmpeg_member, dest_dir / "ffmpeg.exe")
            _extract_atomic(zf, ffprobe_member, dest_dir / "ffprobe.exe")


def _find_member(names: List[str], suffix: str) -> str:
    for name in names:
        if name.replace("\\", "/").endswith(suffix):
            return name
    raise RuntimeError(f"ffmpeg archive did not contain {suffix}")


def _download_file(
    url: str, dest: Path, on_progress: Optional[Callable[[float], None]],
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length", 0))
        read = 0
        last_reported = -1
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            read += len(chunk)
            if on_progress and total > 0:
                pct = int(read * 100 / total)
                if pct != last_reported:
                    last_reported = pct
                    on_progress(pct / 100)


def _extract_atomic(zf: zipfile.ZipFile, member: str, dest: Path) -> None:
    """Extract *member* to *dest*, writing to a sibling temp file first.

    A crash or interrupted extraction mid-copy then never leaves a
    truncated exe under the final name — os.replace() only swaps it in
    once the full contents are on disk.
    """
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    with zf.open(member) as src, open(tmp_path, "wb") as out:
        shutil.copyfileobj(src, out)
    os.replace(tmp_path, dest)
