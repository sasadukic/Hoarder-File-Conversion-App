"""What Plunder was in the middle of when it last shut down.

Closing the app kills every aria2c child and every ffmpeg run with it. Without
a record, a torrent that was 90% done is simply forgotten — the partial data
sits in the staging folder with nobody left to finish it — and a batch of files
that was midway through encoding is only ever picked up again by luck, if it
happened to live inside the monitored folder where the startup scan looks.

So each kind of unfinished work is written down as it is queued and cleared as
it completes:

``downloads``
    ``{"tid", "target", "name"}`` per unfinished transfer, where the target is
    the magnet URI or the staged .torrent copy aria2c was handed. Re-adding
    that target resumes rather than restarts — aria2c picks up from its own
    ".aria2" control file in the staging folder.

``encodes``
    ``{"paths": [...]}`` per queued conversion batch. ffmpeg has no notion of
    resuming a half-written file, so an interrupted batch is re-run from the
    start; its partial output is deleted first (see the GUI's restore) so the
    rerun is not confused by a truncated file left behind.

Losing this file costs a resume, never data, so every failure here is
swallowed — the same tradeoff library.py makes.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


def _state_path() -> Path:
    """Where session.json lives — next to the exe, else %LOCALAPPDATA%.

    Same reasoning as library.py's _library_path: a portable copy should carry
    its state with it, but an install under ``C:\\Program Files`` is usually
    not writable, and state that cannot be saved would silently do nothing.
    """
    if getattr(sys, "frozen", False):
        beside_exe = Path(sys.executable).parent / "session.json"
        if _is_writable(beside_exe.parent):
            return beside_exe
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Hoarder"
        try:
            local.mkdir(parents=True, exist_ok=True)
        except OSError:
            return beside_exe
        return local / "session.json"
    return Path(__file__).parent / "session.json"


def _is_writable(directory: Path) -> bool:
    probe = directory / ".hoarder_write_test"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


_STATE_PATH = _state_path()


def _empty() -> Dict[str, List[dict]]:
    return {"downloads": [], "encodes": []}


def load() -> Dict[str, List[dict]]:
    """Read the saved session. Returns an empty one on missing or corrupt file."""
    try:
        raw = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    return {
        "downloads": _clean_downloads(raw.get("downloads")),
        "encodes": _clean_encodes(raw.get("encodes")),
    }


def _clean_downloads(value: Any) -> List[dict]:
    """Keep only entries a resume could actually act on."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        if not isinstance(target, str) or not target:
            continue
        out.append({
            "tid": str(item.get("tid") or ""),
            "target": target,
            "name": str(item.get("name") or ""),
        })
    return out


def _clean_encodes(value: Any) -> List[dict]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        paths = item.get("paths")
        if not isinstance(paths, list):
            continue
        paths = [p for p in paths if isinstance(p, str) and p]
        if paths:
            out.append({"paths": paths})
    return out


def save(downloads: List[dict], encodes: List[dict]) -> None:
    """Atomically record the unfinished work. Failures are ignored."""
    data = {
        "downloads": _clean_downloads(downloads),
        "encodes": _clean_encodes(encodes),
    }
    try:
        tmp = _STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_STATE_PATH)
    except OSError:
        pass


def clear() -> None:
    save([], [])
