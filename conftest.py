"""Cross-platform test shim: stubs Windows-only modules (winreg, winsound,
pystray's GUI backend) so the suite can also run on Linux/macOS/CI.

On Windows this file does nothing — the real modules are used.
"""
import sys
import types

if sys.platform != "win32":
    # --- winreg stub ---
    winreg = types.ModuleType("winreg")
    winreg.HKEY_CURRENT_USER = 0
    winreg.KEY_ALL_ACCESS = 0xF003F
    winreg.REG_SZ = 1

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _create_key(*a, **k):
        return _Key()

    def _raise_fnf(*a, **k):
        raise FileNotFoundError

    winreg.CreateKey = _create_key
    winreg.OpenKey = _raise_fnf
    winreg.SetValueEx = lambda *a, **k: None
    winreg.DeleteValue = lambda *a, **k: None
    winreg.DeleteKey = lambda *a, **k: None
    winreg.QueryValueEx = _raise_fnf
    sys.modules.setdefault("winreg", winreg)

    # --- winsound stub ---
    winsound = types.ModuleType("winsound")
    winsound.SND_FILENAME = 0x20000
    winsound.SND_ASYNC = 0x0001
    winsound.PlaySound = lambda *a, **k: None
    sys.modules.setdefault("winsound", winsound)

    # --- pystray stub (needs a GUI backend on Linux) ---
    pystray = types.ModuleType("pystray")

    class _Icon:
        def __init__(self, *a, **k):
            pass

        def run_detached(self):
            pass

        def stop(self):
            pass

    class _Menu:
        def __init__(self, *a, **k):
            pass

    class _MenuItem:
        def __init__(self, *a, **k):
            pass

    pystray.Icon = _Icon
    pystray.Menu = _Menu
    pystray.MenuItem = _MenuItem
    sys.modules.setdefault("pystray", pystray)
