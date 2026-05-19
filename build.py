#!/usr/bin/env python3
"""Build Hoarder as a self-contained portable directory.

Usage:
    py build.py

Output:
    dist/Hoarder/          <- copy this folder anywhere, it runs standalone
    dist/Hoarder/Hoarder.exe

Notes:
    - ffmpeg.exe and ffprobe.exe (~96 MB each) are bundled inside the folder.
    - settings.json is written next to Hoarder.exe so settings persist and
      travel with the folder.
    - PyInstaller is installed automatically if not already present.
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(cmd: list) -> None:
    print(">>", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def _pre_build_clean(dist_dir: Path) -> None:
    """Prepare a clean output location before PyInstaller runs.

    Strategy:
    1. Kill any running Hoarder.exe and ffmpeg.exe (they lock files in dist/).
    2. Try to delete dist/Hoarder outright (works if nothing is locked).
    3. If that fails, RENAME dist/Hoarder → dist/Hoarder_old — Windows allows
       renaming a directory that contains locked files, which unblocks the
       build path so PyInstaller can create a fresh dist/Hoarder.
    4. Schedule a best-effort background deletion of dist/Hoarder_old.
    """
    for proc in ("Hoarder.exe", "ffmpeg.exe", "ffprobe.exe"):
        result = subprocess.run(
            ["taskkill", "/F", "/IM", proc],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Terminated {proc}.")

    if not dist_dir.exists():
        return

    # Fast path: outright delete
    try:
        shutil.rmtree(dist_dir)
        print(f"Removed {dist_dir}.")
        return
    except PermissionError:
        pass

    # Rename out of the way so PyInstaller can create a fresh directory
    old_dir = dist_dir.parent / (dist_dir.name + "_old")
    shutil.rmtree(old_dir, ignore_errors=True)
    try:
        dist_dir.rename(old_dir)
        print(f"Renamed {dist_dir.name} → {old_dir.name} (files are locked; will delete after build).")
    except Exception as e:
        print(f"Warning: could not rename old dist dir: {e} — build may fail if AV holds ffmpeg.exe.")



def main() -> None:
    # ------------------------------------------------------------------ deps
    _pre_build_clean(HERE / "dist" / "Hoarder")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found — installing…")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    import tkinterdnd2
    import customtkinter

    tnd_dir = Path(tkinterdnd2.__file__).parent
    ctk_dir = Path(customtkinter.__file__).parent

    # ------------------------------------------------------------------ data
    # Format: "source;dest_folder_inside_bundle"
    S = ";"
    datas = [
        f"{HERE / 'slkscr.ttf'}{S}.",
        f"{HERE / 'hoarder.ico'}{S}.",
        f"{HERE / 'bin'}{S}bin",
        f"{tnd_dir}{S}tkinterdnd2",
        f"{ctk_dir}{S}customtkinter",
    ]
    for wav in sorted(HERE.glob("*.wav")):
        datas.append(f"{wav}{S}.")

    # ----------------------------------------------------------------- build
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                        # portable folder, fast startup
        "--windowed",                      # no console window
        "--name", "Hoarder",
        "--icon", str(HERE / "hoarder.ico"),
        "--noconfirm",
        "--clean",
    ]
    for d in datas:
        cmd += ["--add-data", d]

    cmd += [
        # runtime hooks / hidden imports that PyInstaller misses
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "watchdog.observers.winapi",
        str(HERE / "main.py"),
    ]

    # Pre-clean old dist so PyInstaller never trips on AV-locked ffmpeg/ffprobe
    # (already handled by _pre_build_clean above, but kept for explicitness)
    run(cmd)

    # Best-effort cleanup of the renamed-aside old dist (from _pre_build_clean)
    old_dir = HERE / "dist" / "Hoarder_old"
    if old_dir.exists():
        shutil.rmtree(old_dir, ignore_errors=True)
        if not old_dir.exists():
            print("Removed dist/Hoarder_old.")

    # Remove the intermediate build/ artefacts so the incomplete exe inside
    # build/Hoarder/ can't be run by mistake (it fails with a DLL error).
    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("Removed intermediate build/ directory.")

    out = HERE / "dist" / "Hoarder"
    print()
    print("Build complete.")
    print(f"  Portable folder : {out}")
    print(f"  Launcher        : {out / 'Hoarder.exe'}")
    print()
    print("Copy the entire 'dist/Hoarder/' folder to distribute.")


if __name__ == "__main__":
    main()
