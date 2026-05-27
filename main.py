import ctypes
import os
import sys
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
# PROCESS_PER_MONITOR_DPI_AWARE (2) prevents Windows from bitmap-scaling the
# window, which blurs pixel/bitmap fonts like Silkscreen.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from gui import App


def _register_font(ttf_path: Path) -> None:
    """Register a TTF font for this process via the Windows GDI API."""
    if not ttf_path.exists():
        return
    FR_PRIVATE = 0x10
    ctypes.windll.gdi32.AddFontResourceExW(str(ttf_path), FR_PRIVATE, 0)


if __name__ == "__main__":
    # When frozen by PyInstaller, sys._MEIPASS holds the extracted bundle dir.
    _bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    _register_font(_bundle_dir / "slkscr.ttf")
    start_in_tray = "--tray" in sys.argv

    # Parse magnet URI passed from browser protocol handler
    magnet_uri: str | None = None
    for i, arg in enumerate(sys.argv):
        if arg == "--magnet" and i + 1 < len(sys.argv):
            magnet_uri = sys.argv[i + 1]
            break
        elif arg.startswith("magnet:?"):
            magnet_uri = arg
            break

    app = App(start_in_tray=start_in_tray)
    if magnet_uri:
        app.after(100, lambda uri=magnet_uri: app._handle_magnet_link(uri))
    app.mainloop()
