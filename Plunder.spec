# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\psilo\\Desktop\\Audio Convert\\main.py'],
    pathex=[],
    binaries=[('C:\\Users\\psilo\\Desktop\\Audio Convert\\bin\\aria2c.exe', 'bin')],
    datas=[('C:\\Users\\psilo\\Desktop\\Audio Convert\\slkscr.ttf', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\Alkhemikal.ttf', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\hoarder.ico', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\skull.png', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\chain.png', '.'), ('C:\\Users\\psilo\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\tkinterdnd2', 'tkinterdnd2'), ('C:\\Users\\psilo\\AppData\\Local\\Programs\\Python\\Python314\\Lib\\site-packages\\customtkinter', 'customtkinter'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\app quit.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\app_startup.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\checkbox.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\click.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\hover.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\torrent downloaded-001.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\torrent downloaded-002.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\torrent downloaded-003.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\torrent downloaded-004.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\transcoding done.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\when torrent added.wav', '.')],
    hiddenimports=['pystray._win32', 'PIL._tkinter_finder', 'watchdog.observers.winapi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Plunder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed sections are one of the strongest generic-heuristic signals
    # Windows Defender has; the few MB saved are not worth a quarantine.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\psilo\\Desktop\\Audio Convert\\hoarder.ico'],
    # An exe with no version resource is another cheap "freshly packed
    # binary" signal — see build.py's docstring.
    version='C:\\Users\\psilo\\Desktop\\Audio Convert\\version_info.txt',
)
