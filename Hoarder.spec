# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\psilo\\Desktop\\Audio Convert\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\psilo\\Desktop\\Audio Convert\\slkscr.ttf', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\hoarder.ico', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\bin', 'bin'), ('C:\\StabilityMatrix-win-x64\\Data\\Assets\\Python\\cpython-3.13.12-windows-x86_64-none\\Lib\\site-packages\\tkinterdnd2', 'tkinterdnd2'), ('C:\\StabilityMatrix-win-x64\\Data\\Assets\\Python\\cpython-3.13.12-windows-x86_64-none\\Lib\\site-packages\\customtkinter', 'customtkinter'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\Click.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\Done.wav', '.'), ('C:\\Users\\psilo\\Desktop\\Audio Convert\\Starting.wav', '.')],
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
    [],
    exclude_binaries=True,
    name='Hoarder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\psilo\\Desktop\\Audio Convert\\hoarder.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Hoarder',
)
