import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
from pathlib import Path

# Cache pythonw.exe path for run.vbs (silent launcher) — skip when bundled.
if not getattr(sys, "frozen", False):
    try:
        _pythonw = Path(sys.executable).parent / "pythonw.exe"
        if _pythonw.exists():
            (Path(__file__).parent / ".pythonw_cache").write_text(str(_pythonw))
    except Exception:
        pass

# Must be called before any Tk window is created.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from gui import App

kernel32 = ctypes.windll.kernel32
_PIPE_NAME = r"\\.\pipe\HoarderMagnet"
_BUFSIZE = 4096


def _parse_magnet_arg() -> str | None:
    for i, arg in enumerate(sys.argv):
        if arg == "--magnet" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("magnet:?"):
            return arg
    return None


def _start_pipe_server(app: App) -> None:
    """Listen on a named pipe for magnet URIs from other Hoarder instances."""
    def _server():
        while True:
            h = kernel32.CreateNamedPipeW(
                _PIPE_NAME,
                wt.DWORD(0x00000003),  # PIPE_ACCESS_DUPLEX
                wt.DWORD(0x00000004 | 0x00000002 | 0x00000000),  # TYPE_MESSAGE | READMODE_MESSAGE | WAIT
                wt.DWORD(1), wt.DWORD(_BUFSIZE), wt.DWORD(_BUFSIZE),
                wt.DWORD(0), None,
            )
            if h == wt.HANDLE(-1).value:
                break
            if kernel32.ConnectNamedPipe(h, None) or ctypes.GetLastError() == 535:  # ERROR_PIPE_CONNECTED
                buf = ctypes.create_string_buffer(_BUFSIZE)
                read = wt.DWORD(0)
                kernel32.ReadFile(h, buf, _BUFSIZE, ctypes.byref(read), None)
                kernel32.CloseHandle(h)
                uri = buf.value.decode("utf-8", errors="replace").rstrip("\x00")
                if uri.startswith("magnet:?"):
                    app.after(0, app._handle_magnet_link, uri)
            else:
                kernel32.CloseHandle(h)

    threading.Thread(target=_server, daemon=True).start()


def _try_send_to_existing(magnet_uri: str | None) -> bool:
    """Send magnet URI to the running Hoarder instance. Returns True if sent."""
    h = kernel32.CreateFileW(
        _PIPE_NAME,
        wt.DWORD(0xC0000000),  # GENERIC_READ | GENERIC_WRITE
        wt.DWORD(0), None,
        wt.DWORD(3),  # OPEN_EXISTING
        wt.DWORD(0), None,
    )
    if h == wt.HANDLE(-1).value:
        return False
    payload = (magnet_uri or "").encode("utf-8")
    written = wt.DWORD(0)
    ok = kernel32.WriteFile(h, payload, len(payload), ctypes.byref(written), None)
    kernel32.CloseHandle(h)
    return bool(ok)


def _register_font(ttf_path: Path) -> None:
    if not ttf_path.exists():
        return
    FR_PRIVATE = 0x10
    ctypes.windll.gdi32.AddFontResourceExW(str(ttf_path), FR_PRIVATE, 0)


if __name__ == "__main__":
    _bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    _register_font(_bundle_dir / "slkscr.ttf")
    start_in_tray = "--tray" in sys.argv

    magnet_uri = _parse_magnet_arg()

    # If another instance is running, send it the magnet and exit
    if _try_send_to_existing(magnet_uri):
        sys.exit(0)

    app = App(start_in_tray=start_in_tray)
    _start_pipe_server(app)

    if magnet_uri:
        app.after(100, app._handle_magnet_link, magnet_uri)

    app.mainloop()
