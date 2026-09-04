import threading
import time
from pathlib import Path
from typing import Callable, List, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from cue_parser import cue_file_ref
from converter import AUDIO_EXTS as _AUDIO_EXTS, VIDEO_EXTS as _VIDEO_EXTS

# How long the file size must be stable before we consider it fully written.
_STABLE_SECS = 0.5
_POLL_INTERVAL = 0.1


def _wait_stable(path: Path) -> bool:
    """Poll until file size is stable for _STABLE_SECS. Returns False if the
    file disappears or settles at 0 bytes — a stray placeholder (e.g. an
    aria2/torrent artifact) rather than real media, which would otherwise
    reach ffprobe and fail with no usable error."""
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
                return size > 0
        else:
            stable_since = None
        prev_size = size
        time.sleep(_POLL_INTERVAL)


_TORRENT_EXTS = {".torrent", ".magnet"}


class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[List[str]], None],
                 torrent_callback: Callable[[List[str]], None],
                 inflight: Set[str], lock: threading.Lock,
                 exclude_dirname: str | None = None):
        self._callback = callback
        self._torrent_callback = torrent_callback
        self._inflight = inflight
        self._lock = lock
        self._exclude_dirname = exclude_dirname

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle_path(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        self._handle_path(Path(event.dest_path))

    def _handle_path(self, path: Path) -> None:
        if self._exclude_dirname and self._exclude_dirname in path.parts:
            return
        suffix = path.suffix.lower()
        if suffix in _TORRENT_EXTS:
            key = str(path)
            with self._lock:
                if key in self._inflight:
                    return
                self._inflight.add(key)
            threading.Thread(target=self._process_torrent, args=(path,), daemon=True).start()
            return
        if suffix not in _AUDIO_EXTS and suffix not in _VIDEO_EXTS:
            return
        key = str(path)
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(target=self._process, args=(path,), daemon=True).start()

    def _process_torrent(self, src: Path) -> None:
        try:
            if not _wait_stable(src):
                return
            self._torrent_callback([str(src)])
        finally:
            with self._lock:
                self._inflight.discard(str(src))

    def _process(self, src: Path) -> None:
        try:
            if not _wait_stable(src):
                return
            paths = [str(src)]
            # For audio files, include a matching CUE if present.
            # Strategy 1: same-stem  (album.flac / album.ape → album.cue)
            # Strategy 2: FILE directive — scan sibling CUEs whose FILE line
            #             references this audio file by name (handles non-matching stems)
            if src.suffix.lower() in _AUDIO_EXTS:
                cue = src.with_suffix(".cue")
                if not cue.exists():
                    for candidate in sorted(src.parent.glob("*.cue")):
                        ref = cue_file_ref(str(candidate))
                        if ref and Path(ref).stem.lower() == src.stem.lower():
                            cue = candidate
                            break
                if cue.exists():
                    paths.append(str(cue))
            self._callback(paths)
        finally:
            with self._lock:
                self._inflight.discard(str(src))


class FolderMonitor:
    """Watch a folder (recursively) for new FLAC files and trigger conversion."""

    def __init__(self, folder: str,
                 on_files: Callable[[List[str]], None],
                 on_torrents: Callable[[List[str]], None],
                 exclude_dirname: str | None = None):
        self._folder = folder
        self._on_files = on_files
        self._on_torrents = on_torrents
        self._exclude_dirname = exclude_dirname
        self._observer: Observer | None = None
        self._inflight: Set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching. No-op if already running."""
        if self._observer is not None:
            return
        handler = _Handler(
            self._on_files, self._on_torrents, self._inflight, self._lock,
            exclude_dirname=self._exclude_dirname,
        )
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
