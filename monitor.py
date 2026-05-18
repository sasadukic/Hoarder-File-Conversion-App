import threading
import time
from pathlib import Path
from typing import Callable, List, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# How long the file size must be stable before we consider it fully written.
_STABLE_SECS = 0.5
_POLL_INTERVAL = 0.1


def _wait_stable(path: Path) -> bool:
    """Poll until file size is stable for _STABLE_SECS. Returns False if file disappears."""
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
                return True
        else:
            stable_since = None
        prev_size = size
        time.sleep(_POLL_INTERVAL)


class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[List[str]], None], inflight: Set[str], lock: threading.Lock):
        self._callback = callback
        self._inflight = inflight
        self._lock = lock

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() != ".flac":
            return
        key = str(path)
        with self._lock:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(target=self._process, args=(path,), daemon=True).start()

    def _process(self, flac: Path) -> None:
        try:
            if not _wait_stable(flac):
                return
            paths = [str(flac)]
            cue = flac.with_suffix(".cue")
            if cue.exists():
                paths.append(str(cue))
            self._callback(paths)
        finally:
            with self._lock:
                self._inflight.discard(str(flac))


class FolderMonitor:
    """Watch a folder (recursively) for new FLAC files and trigger conversion."""

    def __init__(self, folder: str, on_files: Callable[[List[str]], None]):
        self._folder = folder
        self._on_files = on_files
        self._observer: Observer | None = None
        self._inflight: Set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching. No-op if already running."""
        if self._observer is not None:
            return
        handler = _Handler(self._on_files, self._inflight, self._lock)
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
