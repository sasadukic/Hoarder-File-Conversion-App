#!/usr/bin/env python3
r"""Build Plunder as a single portable executable.

Usage:
    py build.py

Output:
    dist/Plunder.exe       <- copy this one file anywhere, it runs standalone

Notes:
    - ffmpeg.exe and ffprobe.exe are NOT bundled (they're ~96 MB each) — the
      app downloads a static build on first use and caches it in
      %LOCALAPPDATA%\Hoarder\bin (see ffmpeg_fetch.py). aria2c.exe is small
      enough to keep bundling directly.
    - settings.json/library.json are written next to Plunder.exe (via
      sys.executable, not the onefile temp-extraction dir) so they persist
      and travel with the exe wherever it's copied.
    - --onefile means every launch self-extracts to a temp dir first, so
      startup is slower than the old --onedir build. Traded deliberately
      for true single-file portability — see build.py's git history if that
      tradeoff ever needs revisiting.
    - PyInstaller is installed automatically if not already present.

Windows Defender:
    A PyInstaller onefile exe is a self-extracting packed binary, which is
    structurally what a dropper looks like — so Defender's generic heuristics
    flag these routinely, with names like "Trojan:Win32/Wacatac.B!ml". Two
    build settings make that materially less likely and cost nothing:

      --noupx         UPX-packed sections are one of the strongest generic
                      heuristic signals there is. The compression saves a few
                      MB and buys a detection.
      --version-file  An executable carrying no version resource at all is
                      another cheap signal — it is what a freshly packed
                      binary looks like. version_info.txt fills it in.

    Neither is a guarantee. The real fix is a code-signing certificate from a
    CA, which accrues SmartScreen reputation over time; short of that, report
    any false positive to Microsoft (see README) so the definition is
    corrected for everyone rather than only on this machine.
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def run(cmd: list) -> None:
    print(">>", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def _pre_build_clean(dist_exe: Path) -> None:
    """Prepare a clean output location before PyInstaller runs.

    Strategy:
    1. Kill any running Plunder.exe (it locks dist/Plunder.exe while running).
    2. Try to delete dist/Plunder.exe outright (works if nothing is locked).
    3. If that fails, RENAME it aside — Windows allows renaming a locked
       file, which unblocks the build path so PyInstaller can create a
       fresh one.
    4. Best-effort delete the renamed-aside old exe after the build.
    """
    for proc in ("Plunder.exe", "Hoarder.exe"):
        result = subprocess.run(
            ["taskkill", "/F", "/IM", proc],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Terminated {proc}.")

    if not dist_exe.exists():
        return

    # Fast path: outright delete
    try:
        dist_exe.unlink()
        print(f"Removed {dist_exe}.")
        return
    except PermissionError:
        pass

    # Rename out of the way so PyInstaller can create a fresh file
    old_exe = dist_exe.with_name(dist_exe.stem + "_old" + dist_exe.suffix)
    old_exe.unlink(missing_ok=True)
    try:
        dist_exe.rename(old_exe)
        print(f"Renamed {dist_exe.name} → {old_exe.name} (file is locked; will delete after build).")
    except Exception as e:
        print(f"Warning: could not rename old exe: {e} — build may fail if AV holds it.")



def main() -> None:
    # ------------------------------------------------------------------ deps
    _pre_build_clean(HERE / "dist" / "Plunder.exe")
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
        f"{HERE / 'Alkhemikal.ttf'}{S}.",
        f"{HERE / 'hoarder.ico'}{S}.",
        f"{HERE / 'skull.png'}{S}.",
        f"{HERE / 'chain.png'}{S}.",
        f"{tnd_dir}{S}tkinterdnd2",
        f"{ctk_dir}{S}customtkinter",
    ]
    for wav in sorted(HERE.glob("*.wav")):
        datas.append(f"{wav}{S}.")

    # aria2c.exe only — ffmpeg.exe/ffprobe.exe are fetched on demand instead
    # of bundled (see module docstring).
    binaries = [
        f"{HERE / 'bin' / 'aria2c.exe'}{S}bin",
    ]

    # ----------------------------------------------------------------- build
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                       # single portable exe
        "--windowed",                      # no console window
        "--name", "Plunder",
        "--icon", str(HERE / "hoarder.ico"),
        # Both of these exist to keep Defender's generic heuristics calm —
        # see the module docstring.
        "--noupx",
        "--version-file", str(HERE / "version_info.txt"),
        "--noconfirm",
        "--clean",
    ]
    for d in datas:
        cmd += ["--add-data", d]
    for b in binaries:
        cmd += ["--add-binary", b]

    cmd += [
        # runtime hooks / hidden imports that PyInstaller misses
        "--hidden-import", "pystray._win32",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "watchdog.observers.winapi",
        str(HERE / "main.py"),
    ]

    # Pre-clean old dist so PyInstaller never trips on an AV-locked exe
    # (already handled by _pre_build_clean above, but kept for explicitness)
    run(cmd)

    # Best-effort cleanup of the renamed-aside old exe (from _pre_build_clean)
    old_exe = HERE / "dist" / "Plunder_old.exe"
    if old_exe.exists():
        try:
            old_exe.unlink()
            print("Removed dist/Plunder_old.exe.")
        except OSError:
            pass

    # Remove the intermediate build/ artefacts.
    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("Removed intermediate build/ directory.")

    out = HERE / "dist" / "Plunder.exe"
    print()
    print("Build complete.")
    print(f"  Portable exe : {out}")
    print()
    print("Copy this one file to distribute.")


if __name__ == "__main__":
    main()
