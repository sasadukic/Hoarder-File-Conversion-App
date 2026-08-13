import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

def _try_import_libtorrent():
    try:
        import libtorrent as lt
        return lt
    except ImportError:
        return None

_LOCAL_ARIA2C = Path(__file__).parent / "bin" / "aria2c.exe"

# aria2c summary lines look like:  [#2089b0 400KiB/33MiB(1%) CN:1 DL:115KiB ETA:4m51s]
# followed by:                     FILE: C:\downloads\movie.mkv
_ARIA2_PCT_RE = re.compile(r"\((\d{1,3}(?:\.\d+)?)%\)")
_ARIA2_FILE_RE = re.compile(r"^FILE:\s*(.+?)\s*$")

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

def _find_aria2c() -> Optional[str]:
    if _LOCAL_ARIA2C.exists():
        return str(_LOCAL_ARIA2C)
    return shutil.which("aria2c")

def _extract_magnet_name(uri: str) -> Optional[str]:
    match = re.search(r"dn=([^&]+)", uri)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1).replace("+", " "))
    return None

class TorrentDownloader:
    def __init__(
        self,
        download_dir: str,
        on_progress: Callable[[str, str, float], None],
        on_complete: Callable[[str, str], None],
    ):
        self.download_dir = str(Path(download_dir))
        self.on_progress = on_progress
        self.on_complete = on_complete

        self._lt: Any = _try_import_libtorrent()
        self._session: Any = None
        self._handles: Dict[str, Any] = {}
        self._aria2c_procs: Dict[str, subprocess.Popen] = {}
        self._progress: Dict[str, float] = {}
        self._names: Dict[str, str] = {}
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._lt is not None:
            self._session = self._lt.session()
            try:
                # libtorrent 2.x way
                self._session.apply_settings(
                    {"listen_interfaces": "0.0.0.0:6881,[::]:6881"}
                )
            except Exception:
                try:
                    self._session.listen_on(6881, 6891)  # legacy 1.x fallback
                except Exception:
                    pass
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
        if self._session is not None:
            for handle in list(self._handles.values()):
                self._session.remove_torrent(handle)
            self._session = None
        for proc in list(self._aria2c_procs.values()):
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        with self._lock:
            self._handles.clear()
            self._aria2c_procs.clear()
            self._progress.clear()
            self._names.clear()

    def add(self, path: str) -> Optional[str]:
        if not self._running:
            return None

        p = Path(path)

        if p.suffix.lower() == ".torrent":
            if self._lt is None and _find_aria2c() is None:
                return None
            name = p.stem
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            if self._lt is not None:
                try:
                    info = self._lt.torrent_info(str(p))
                    params = self._lt.add_torrent_params()
                    params.ti = info
                    params.save_path = self.download_dir
                    params.storage_mode = self._lt.storage_mode_t.storage_mode_sparse
                    handle = self._session.add_torrent(params)
                    with self._lock:
                        self._handles[tid] = handle
                    return tid
                except Exception:
                    self._names.pop(tid, None)
                    self._progress.pop(tid, None)
                    return None
            else:
                return self._start_aria2c(tid, str(p), name)

        elif p.suffix.lower() == ".magnet":
            try:
                uri = p.read_text(encoding="utf-8").strip()
            except Exception:
                return None
            if not uri.startswith("magnet:?"):
                return None
            if self._lt is None and _find_aria2c() is None:
                return None
            name = _extract_magnet_name(uri) or p.stem
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            return self._add_magnet(tid, uri, name)

        elif path.startswith("magnet:?"):
            if self._lt is None and _find_aria2c() is None:
                return None
            name = _extract_magnet_name(path) or "magnet"
            tid = str(uuid.uuid4())
            self._names[tid] = name
            self._progress[tid] = 0.0
            return self._add_magnet(tid, path, name)

        return None

    def _add_magnet(self, tid: str, uri: str, name: str) -> Optional[str]:
        if self._lt is not None:
            try:
                params = self._lt.parse_magnet_uri(uri)
                params.save_path = self.download_dir
                params.storage_mode = self._lt.storage_mode_t.storage_mode_sparse
                handle = self._session.add_torrent(params)
                with self._lock:
                    self._handles[tid] = handle
                return tid
            except Exception:
                self._names.pop(tid, None)
                self._progress.pop(tid, None)
                return None
        else:
            return self._start_aria2c(tid, uri, name)

    def _start_aria2c(self, tid: str, target: str, name: str) -> Optional[str]:
        aria2c = _find_aria2c()
        if aria2c is None:
            self._names.pop(tid, None)
            self._progress.pop(tid, None)
            self.on_progress(tid, name, -1.0)
            return None
        cmd = [
            aria2c, "--seed-time=0", "--summary-interval=1",
            "-d", self.download_dir, target,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
        with self._lock:
            self._aria2c_procs[tid] = proc
        self.on_progress(tid, name, 0.0)
        self._spawn_aria2c_monitor(tid, proc, name)
        return tid

    def _spawn_aria2c_monitor(self, tid: str, proc: subprocess.Popen, name: str) -> None:
        def _monitor():
            rc = -1
            file_path: Optional[str] = None
            try:
                # Drain stdout (progress summaries). Without this the pipe
                # buffer fills up and aria2c stalls on larger downloads.
                if proc.stdout is not None:
                    last_pct = -1.0
                    for raw in proc.stdout:
                        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                        line = line.strip()
                        m = _ARIA2_FILE_RE.match(line)
                        if m:
                            file_path = m.group(1)
                            continue
                        m = _ARIA2_PCT_RE.search(line)
                        if m:
                            pct = min(float(m.group(1)) / 100.0, 1.0)
                            if pct != last_pct:
                                last_pct = pct
                                self._progress[tid] = pct
                                self.on_progress(tid, name, pct)
                rc = proc.wait()
            except Exception:
                pass
            with self._lock:
                self._aria2c_procs.pop(tid, None)
            if rc == 0:
                self._progress[tid] = 1.0
                self.on_progress(tid, name, 1.0)
                # Prefer the actual path aria2c reported; fall back to a guess.
                download_path = file_path or os.path.join(self.download_dir, name)
                self.on_complete(tid, download_path)
            else:
                self._progress[tid] = -1.0
                self.on_progress(tid, name, -1.0)

        t = threading.Thread(target=_monitor, daemon=True)
        t.start()

    def _poll_once(self) -> None:
        if self._lt is not None and self._session is not None:
            with self._lock:
                handles = list(self._handles.items())
            for tid, handle in handles:
                if handle.is_valid():
                    status = handle.status()
                    progress = status.progress
                    name = status.name or self._names.get(tid, "")
                    self._progress[tid] = progress
                    self.on_progress(tid, name, progress)
                    if status.is_seeding or status.is_finished:
                        download_path = os.path.join(self.download_dir, name)
                        self.on_complete(tid, download_path)
                        with self._lock:
                            self._handles.pop(tid, None)
                        self._progress.pop(tid, None)
                        self._names.pop(tid, None)

    def _poll_loop(self) -> None:
        while self._running:
            self._poll_once()
            time.sleep(1)

    def get_progress(self, tid: str) -> float:
        return self._progress.get(tid, 0.0)

    def remove(self, tid: str) -> None:
        with self._lock:
            if tid in self._handles:
                if self._session is not None:
                    self._session.remove_torrent(self._handles[tid])
                del self._handles[tid]
            if tid in self._aria2c_procs:
                try:
                    self._aria2c_procs[tid].terminate()
                except Exception:
                    pass
                del self._aria2c_procs[tid]
            self._progress.pop(tid, None)
            self._names.pop(tid, None)
