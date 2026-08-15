"""Library of media Hoarder has already converted.

Without this, every restart re-scans the monitored folder and re-encodes
everything still sitting in it — including the app's own transcodes, since a
finished ``.mp4`` looks exactly like a source ``.mp4`` to the folder scan.

Identity is *content based*: a file counts as done when the digest of its
first few megabytes (salted with its byte size) is recorded, so the same
release converted under a different name or moved to another folder is not
encoded a second time.

Hashing every candidate on every scan would be slow on large video folders,
so digests are cached per (path, size, mtime). A restart scan then costs one
``stat`` per known file and only reads bytes for files it has not seen.
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Bytes read from the head of a file to identify it. Large enough that two
# different releases never collide, small enough to stay cheap on a 20 GB mkv.
_CHUNK = 4 * 1024 * 1024

# Upper bound on remembered files; oldest entries fall off first.
_MAX_ENTRIES = 20000
_MAX_STAMPS = 20000


def _library_path() -> Path:
    """Where library.json lives.

    Next to the executable, like settings.json, so the library travels with a
    portable copy. If that directory is not writable — the usual case for an
    install under ``C:\\Program Files`` — fall back to %LOCALAPPDATA%, since a
    library that cannot be saved would silently do nothing.
    """
    if getattr(sys, "frozen", False):
        beside_exe = Path(sys.executable).parent / "library.json"
        if _is_writable(beside_exe.parent):
            return beside_exe
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Hoarder"
        try:
            local.mkdir(parents=True, exist_ok=True)
        except OSError:
            return beside_exe
        return local / "library.json"
    return Path(__file__).parent / "library.json"


def _is_writable(directory: Path) -> bool:
    probe = directory / ".hoarder_write_test"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


_LIBRARY_PATH = _library_path()


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def digest(path: str) -> Optional[str]:
    """Content digest of *path*, or None if it cannot be read.

    The file size is folded into the hash so two files sharing a first chunk
    (a common container header, say) still differ.
    """
    try:
        size = os.path.getsize(path)
        h = hashlib.sha1(str(size).encode())
        with open(path, "rb") as f:
            h.update(f.read(_CHUNK))
        return h.hexdigest()
    except OSError:
        return None


def _stamp(path: str) -> Optional[List[int]]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, int(st.st_mtime)]


def load() -> Dict[str, dict]:
    """Read the library. Returns an empty library on missing or corrupt file."""
    empty: Dict[str, dict] = {"done": {}, "stamps": {}}
    try:
        raw = json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return empty
    if not isinstance(raw, dict):
        return empty
    done = raw.get("done")
    stamps = raw.get("stamps")
    return {
        "done": done if isinstance(done, dict) else {},
        "stamps": stamps if isinstance(stamps, dict) else {},
    }


def save(data: Dict[str, dict]) -> None:
    """Atomically write the library, trimming the oldest entries past the cap.

    A failure to write is not worth crashing a conversion over — the worst
    case is that the same file is converted again next launch.
    """
    data = {
        "done": _trim(data.get("done", {}), _MAX_ENTRIES),
        "stamps": _trim(data.get("stamps", {}), _MAX_STAMPS),
    }
    try:
        tmp = _LIBRARY_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_LIBRARY_PATH)
    except OSError:
        pass


def _trim(mapping: dict, cap: int) -> dict:
    """Keep the *cap* most recently inserted entries (dicts stay ordered)."""
    if len(mapping) <= cap:
        return dict(mapping)
    keys = list(mapping)[-cap:]
    return {k: mapping[k] for k in keys}


def _digest_cached(path: str, data: Dict[str, dict]) -> Optional[str]:
    """Digest of *path*, reusing the cached value when size and mtime match."""
    stamp = _stamp(path)
    if stamp is None:
        return None
    key = _key(path)
    cached = data["stamps"].get(key)
    if (
        isinstance(cached, list) and len(cached) == 3
        and cached[0] == stamp[0] and cached[1] == stamp[1]
    ):
        return cached[2]
    d = digest(path)
    if d is not None:
        data["stamps"][key] = [stamp[0], stamp[1], d]
    return d


def is_done(path: str, data: Optional[Dict[str, dict]] = None) -> bool:
    """True if this file's content has already been converted."""
    data = load() if data is None else data
    d = _digest_cached(path, data)
    return d is not None and d in data["done"]


def mark(paths: Iterable[str]) -> None:
    """Record *paths* as converted. Missing files are ignored."""
    paths = list(paths)
    if not paths:
        return
    data = load()
    changed = False
    for p in paths:
        d = _digest_cached(p, data)
        if d is None:
            continue
        # Re-insert so recently touched entries survive trimming.
        data["done"].pop(d, None)
        data["done"][d] = {"name": Path(p).name, "size": os.path.getsize(p)}
        changed = True
    if changed or data["stamps"]:
        save(data)


def filter_new(paths: Iterable[str]) -> List[str]:
    """Drop the paths already in the library, keeping order.

    Also drops within-batch duplicates of the same content, so a folder
    holding two copies of one file only converts it once.
    """
    data = load()
    seen: set = set()
    out: List[str] = []
    dirty = False
    for p in paths:
        before = len(data["stamps"])
        d = _digest_cached(p, data)
        dirty = dirty or len(data["stamps"]) != before
        if d is None:
            out.append(p)  # unreadable: let the converter report the failure
            continue
        if d in data["done"] or d in seen:
            continue
        seen.add(d)
        out.append(p)
    if dirty:
        save(data)  # keep the digest cache warm for the next scan
    return out
