import array
import io
import math
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
import wave
import winsound
from tkinter import filedialog
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pystray
from PIL import Image, ImageDraw

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from cue_parser import parse_cue
from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs, transcode_videos
import settings as smod
import monitor as mmod

MODE_SPLIT  = "Split + Convert"
MODE_CONVERT = "Convert Only"
MODE_VIDEO  = "Video Transcode"
MODE_MIXED  = "Mixed"

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".wmv", ".avi"}

# ---------------------------------------------------------------------------
# Palette — two colors only
# ---------------------------------------------------------------------------
DARK  = "#222323"
LIGHT = "#f0f6f0"

BG    = DARK    # window / widget backgrounds
PANEL = DARK    # drop zone / panel backgrounds
TEAL  = LIGHT   # borders
TEXT  = LIGHT   # primary text
DIM   = LIGHT   # placeholder / muted text
SAGE  = LIGHT   # file-info / secondary text
GREEN = LIGHT   # success, convert button, done
GOLD  = LIGHT   # in-progress
WARM  = LIGHT   # warnings / errors


def detect_mode(
    paths: List[str],
) -> Tuple[Optional[str], List[str], Optional[str], List[str], Optional[str]]:
    """Classify a list of file paths into a conversion mode.

    Returns (mode, flac_paths, cue_path, video_paths, error_message).
    On error, mode is None and error_message is set.
    """
    flacs  = [p for p in paths if p.lower().endswith(".flac")]
    cues   = [p for p in paths if p.lower().endswith(".cue")]
    videos = [p for p in paths if Path(p).suffix.lower() in VIDEO_EXTS]
    others = [
        p for p in paths
        if not p.lower().endswith(".flac")
        and not p.lower().endswith(".cue")
        and Path(p).suffix.lower() not in VIDEO_EXTS
    ]

    if others:
        return None, [], None, [], "Unsupported file type"
    if cues and not flacs and not videos:
        return None, [], None, [], "Please also provide a FLAC file"
    if len(cues) > 1:
        return None, [], None, [], "Only one CUE file is supported at a time"

    # Determine audio mode
    audio_mode: Optional[str] = None
    audio_cue: Optional[str] = None
    if len(cues) == 1 and len(flacs) == 1:
        audio_mode = MODE_SPLIT
        audio_cue = cues[0]
    elif len(cues) == 1 and len(flacs) > 1:
        audio_mode = MODE_CONVERT  # ignore CUE, convert FLACs
    elif flacs:
        audio_mode = MODE_CONVERT

    has_audio = audio_mode is not None
    has_video = len(videos) > 0

    if has_audio and has_video:
        mode = MODE_MIXED
    elif has_audio:
        mode = audio_mode  # type: ignore[assignment]
    elif has_video:
        mode = MODE_VIDEO
    else:
        return None, [], None, [], "Invalid file selection"

    return mode, flacs, audio_cue, videos, None


def parse_drop_paths(data: str) -> List[str]:
    """Parse tkinterdnd2 drop data into a list of file paths.

    Paths containing spaces are wrapped in braces by tkinterdnd2:
    e.g.  {/path/with spaces/file.flac} /other/file.cue
    """
    paths = []
    data = data.strip()
    while data:
        if data.startswith("{"):
            end = data.index("}")
            paths.append(data[1:end])
            data = data[end + 1:].strip()
        else:
            parts = data.split(" ", 1)
            paths.append(parts[0])
            data = parts[1].strip() if len(parts) > 1 else ""
    return paths


def expand_drops(paths: List[str]) -> List[str]:
    """Expand any dropped folders into their contained FLAC, CUE, and video files."""
    _video_globs = ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi")
    result = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            result.extend(str(f) for f in sorted(path.glob("*.flac")))
            result.extend(str(f) for f in sorted(path.glob("*.cue")))
            for pat in _video_globs:
                result.extend(str(f) for f in sorted(path.glob(pat)))
        else:
            result.append(p)
    return result


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()  # hide until fully built — prevents blank-window flash
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        ctk.deactivate_automatic_dpi_awareness()
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)

        self.title("Hoarder")
        self.geometry("500x440")
        self.resizable(False, False)
        self.configure(bg=BG)

        _ico = Path(__file__).parent / "hoarder.ico"
        if _ico.exists():
            self.iconbitmap(str(_ico))

        self._flac_paths: List[str] = []
        self._cue_path: Optional[str] = None
        self._mode: Optional[str] = None
        self._video_paths: List[str] = []

        self._settings = smod.load()
        self._monitor: mmod.FolderMonitor | None = None
        self._hiding_to_tray = False
        self._tray_icon = None
        self._is_converting = False

        self._preload_sounds()
        self._build_ui()
        self._check_stale_startup_shortcut()
        self.deiconify()  # show now that UI is fully ready

    def _build_ui(self) -> None:
        s = self._settings

        # Wave animation state
        self._wave_phase: float = 0.0
        self._wave_btn_text: str = "Convert"
        self._wave_btn_visible: bool = False
        self._wave_font_drop = tkfont.Font(family="Silkscreen", size=16)
        self._wave_font_btn  = tkfont.Font(family="Silkscreen", size=28)

        # ------------------------------------------------------------------
        # Drop zone
        # ------------------------------------------------------------------
        self._drop_frame = tk.Frame(
            self,
            bg=PANEL,
            highlightbackground=TEAL,
            highlightthickness=2,
            cursor="hand2",
        )
        self._drop_frame.place(x=16, y=12, width=468, height=76)

        self._drop_canvas = tk.Canvas(
            self._drop_frame,
            bg=PANEL,
            highlightthickness=0,
            cursor="hand2",
        )
        self._drop_canvas.pack(fill="both", expand=True)

        for widget in (self._drop_frame, self._drop_canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.bind("<Button-1>", lambda e: self._browse())

        # ------------------------------------------------------------------
        # File info
        # ------------------------------------------------------------------
        self._info_label = tk.Label(
            self,
            text="No files loaded",
            bg=BG,
            fg=DIM,
            font=("Silkscreen", 16),
            wraplength=468,
            justify="left",
            anchor="w",
        )
        self._info_label.place(x=16, y=98, width=468, height=36)

        # ------------------------------------------------------------------
        # Checkboxes
        # ------------------------------------------------------------------
        _ck = dict(
            font=("Silkscreen", 16),
            text_color=LIGHT,
            fg_color=LIGHT,
            border_color=LIGHT,
            hover_color=LIGHT,
            checkmark_color=DARK,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=0,
        )

        self._delete_var = tk.BooleanVar(value=s["delete_flac"])
        self._delete_check = ctk.CTkCheckBox(
            self, text="Delete file after conversion",
            variable=self._delete_var, command=self._play_click, **_ck,
        )
        self._delete_check.place(x=16, y=144)

        self._auto_convert_var = tk.BooleanVar(value=s["auto_convert"])
        self._auto_check = ctk.CTkCheckBox(
            self, text="Auto-convert on load",
            variable=self._auto_convert_var, command=self._play_click, **_ck,
        )
        self._auto_check.place(x=16, y=182)

        self._tray_var = tk.BooleanVar(value=s["minimize_to_tray"])
        self._tray_check = ctk.CTkCheckBox(
            self, text="Minimize to tray",
            variable=self._tray_var, command=self._on_tray_toggle, **_ck,
        )
        self._tray_check.place(x=16, y=220)

        self._startup_var = tk.BooleanVar(value=s["start_on_startup"])
        self._startup_check = ctk.CTkCheckBox(
            self, text="Start on Windows startup",
            variable=self._startup_var, command=self._on_startup_toggle, **_ck,
        )
        self._startup_check.place(x=16, y=258)

        # ------------------------------------------------------------------
        # Folder monitor row
        # ------------------------------------------------------------------
        self._monitor_var = tk.BooleanVar(value=False)
        self._monitor_check = ctk.CTkCheckBox(
            self, text="Monitor folder",
            variable=self._monitor_var, command=self._on_monitor_toggle, **_ck,
        )
        self._monitor_check.place(x=16, y=296)

        self._monitor_browse_btn = ctk.CTkButton(
            self, text="Browse…", font=("Silkscreen", 16),
            width=94, height=28,
            fg_color=DARK, hover_color=DARK,
            text_color=LIGHT,
            border_color=LIGHT, border_width=2,
            corner_radius=0,
            command=self._browse_monitor_folder,
        )
        self._monitor_browse_btn.place(x=390, y=296)

        saved_folder = s["monitor_folder"] or ""
        if saved_folder and not Path(saved_folder).is_dir():
            saved_folder = ""
        self._monitor_folder_var = tk.StringVar(value=saved_folder)
        self._monitor_folder_label = tk.Label(
            self,
            text="",
            bg=BG, fg=DIM,
            font=("Silkscreen", 8),
            anchor="w", wraplength=0,
        )
        self._monitor_folder_label.place(x=16, y=334, width=468, height=30)
        self._monitor_folder_var.trace_add(
            "write",
            lambda *_: self._update_folder_display(),
        )
        self._update_folder_display()

        # ------------------------------------------------------------------
        # Convert button
        # ------------------------------------------------------------------
        self._convert_btn = ctk.CTkButton(
            self,
            text="Convert",
            font=("Silkscreen", 28),
            state="disabled",
            command=self._start_conversion,
            width=468, height=56,
            fg_color=LIGHT, hover_color=LIGHT,
            text_color=DARK,
            text_color_disabled=DARK,
            corner_radius=0,
        )
        self._convert_btn.place(x=16, y=374)

        # Button wave overlay (hidden until conversion starts)
        self._wave_canvas_btn = tk.Canvas(
            self,
            bg=LIGHT,
            highlightthickness=0,
        )
        # not placed yet — shown by _start_conversion

        # Settings traces
        for var in (
            self._delete_var, self._auto_convert_var,
            self._tray_var, self._startup_var,
            self._monitor_var, self._monitor_folder_var,
        ):
            var.trace_add("write", lambda *_: self._save_settings())

        self.bind("<Unmap>", self._on_unmap)

        # Restore monitor state (must be after _status_label is created)
        if s["monitor_folder"] and s["monitor_enabled"]:
            self._monitor_var.set(True)
            self._start_monitor(s["monitor_folder"])

        # Start animation loop
        self.after(40, self._wave_tick)

    # ------------------------------------------------------------------
    # Sound
    # ------------------------------------------------------------------
    @staticmethod
    def _load_wav_at_volume(path: str, factor: float = 0.5) -> bytes:
        """Read a WAV file and return its bytes with samples scaled by factor."""
        with wave.open(path, "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(params.nframes)
        if params.sampwidth == 2:  # 16-bit PCM
            samples = array.array("h", frames)
            for i in range(len(samples)):
                samples[i] = int(samples[i] * factor)
            frames = samples.tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setparams(params)
            wf.writeframes(frames)
        return buf.getvalue()

    def _preload_sounds(self) -> None:
        self._sound_paths: Dict[str, str] = {}
        self._sound_tmp_dir = tempfile.mkdtemp(prefix="hoarder_snd_")
        for name in ("Click.wav", "Done.wav"):
            p = Path(__file__).parent / name
            if p.exists():
                try:
                    data = self._load_wav_at_volume(str(p), 1.0)
                    tmp = str(Path(self._sound_tmp_dir) / name)
                    with open(tmp, "wb") as f:
                        f.write(data)
                    self._sound_paths[name] = tmp
                except Exception:
                    pass

    def _play(self, filename: str) -> None:
        path = self._sound_paths.get(filename)
        if not path:
            return
        threading.Thread(
            target=winsound.PlaySound,
            args=(path, winsound.SND_FILENAME),
            daemon=True,
        ).start()

    def _play_click(self) -> None:
        self._play("Click.wav")

    def _play_done(self) -> None:
        self._play("Done.wav")

    # ------------------------------------------------------------------
    # Drop / browse
    # ------------------------------------------------------------------
    def _update_folder_display(self) -> None:
        folder = self._monitor_folder_var.get()
        name = Path(folder).name if folder else "No folder monitored"
        self._monitor_folder_label.config(text=name)

    def _on_drop(self, event) -> None:
        paths = expand_drops(parse_drop_paths(event.data))
        self._load_files(paths)

    def _browse(self) -> None:
        self._play_click()
        paths = filedialog.askopenfilenames(
            title="Select FLAC and/or CUE files",
            filetypes=[
                ("Audio/CUE files", "*.flac *.cue"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._load_files(list(paths))

    def _load_files(self, paths: List[str]) -> None:
        mode, flacs, cue, videos, error = detect_mode(paths)
        if error:
            self._info_label.config(text=error, fg=WARM)
            self._convert_btn.configure(state="disabled")
            self._flac_paths = []
            self._cue_path = None
            self._mode = None
            self._video_paths = []
            return

        self._flac_paths = flacs
        self._cue_path = cue
        self._mode = mode
        self._video_paths = videos

        names = ", ".join(Path(p).name for p in paths)  # noqa: F841
        self._info_label.config(text="Files loaded", fg=SAGE)
        self._convert_btn.configure(state="normal", text="Convert")

        if self._auto_convert_var.get():
            self._start_conversion()

    # ------------------------------------------------------------------
    # Status / settings
    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = GREEN) -> None:
        """Update the convert button text with a status message."""
        self._convert_btn.configure(text=text)
        self.update_idletasks()

    def _save_settings(self) -> None:
        smod.save({
            "delete_flac": self._delete_var.get(),
            "auto_convert": self._auto_convert_var.get(),
            "minimize_to_tray": self._tray_var.get(),
            "start_on_startup": self._startup_var.get(),
            "monitor_enabled": self._monitor_var.get(),
            "monitor_folder": self._monitor_folder_var.get() or None,
        })

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _start_conversion(self) -> None:
        self._play_click()
        if self._is_converting:
            return
        if not check_ffmpeg():
            self._set_status(
                "ffmpeg not found. Please install it and ensure it's on your PATH.",
                WARM,
            )
            return

        self._is_converting = True
        self._convert_btn.configure(state="disabled")
        self._set_status("Conversion Running", SAGE)

        thread = threading.Thread(target=self._run_conversion, daemon=True)
        thread.start()

    def _run_conversion(self) -> None:
        # Capture all mutable state now to avoid races with _load_files
        flacs     = self._flac_paths[:]
        cue       = self._cue_path
        mode      = self._mode
        videos    = self._video_paths[:]
        do_delete = self._delete_var.get()

        # Compute grand total for unified progress
        audio_units = 0
        if flacs:
            if cue:
                try:
                    from cue_parser import parse_cue as _pc
                    audio_units = len(_pc(cue))
                except Exception:
                    audio_units = 1
            else:
                audio_units = len(flacs)
        video_units = len(videos)
        grand_total = max(audio_units + video_units, 1)
        completed = [0]

        def on_audio_progress(cur: int, total: int) -> None:
            completed[0] = cur
            pct = int(completed[0] / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")

        def on_video_progress(cur: int, total: int) -> None:
            pct = int((audio_units + cur) / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")

        try:
            # --- Audio ---
            if flacs:
                if cue:
                    tracks = parse_cue(cue)
                    split_and_convert(flacs[0], tracks, on_audio_progress)
                else:
                    convert_files(flacs, on_audio_progress)
                if do_delete:
                    delete_flacs(flacs)

            # --- Video ---
            if videos:
                transcode_videos(videos, on_video_progress, delete_source=do_delete)

            # Done message
            self.after(0, self._play_done)
            self.after(0, self._set_status, "Done.")
            if do_delete:
                self.after(3000, self._reset_ui)

        except ValueError as e:
            self.after(0, self._set_status, f"Could not parse CUE file: {e}")
        except RuntimeError as e:
            self.after(0, self._set_status, str(e))
        except Exception as e:
            self.after(0, self._set_status, f"Unexpected error: {e}")
        finally:
            self._is_converting = False
            self.after(0, lambda: self._convert_btn.configure(state="normal"))

    def _reset_btn_text(self) -> None:
        """Restore button text to Convert without touching file state."""
        self._convert_btn.configure(text="Convert")

    def _reset_ui(self) -> None:
        """Reset the UI to idle state after a completed conversion."""
        self._flac_paths = []
        self._cue_path = None
        self._mode = None
        self._video_paths = []
        self._info_label.config(text="No files loaded", fg=DIM)
        self._convert_btn.configure(state="disabled", text="Convert")

    def _draw_wave_drop(self) -> None:
        """Redraw the drop-zone canvas with a waving 'Drag & Drop' text."""
        c = self._drop_canvas
        c.delete("all")
        text = "Drag & Drop"
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 2 or h < 2:
            return  # canvas not yet realized
        total_w = sum(self._wave_font_drop.measure(ch) for ch in text)
        x = (w - total_w) / 2
        cy = h / 2
        for i, ch in enumerate(text):
            cw = self._wave_font_drop.measure(ch)
            y = cy + 4 * math.sin(self._wave_phase + i * 0.6)
            c.create_text(x + cw / 2, y, text=ch,
                          font=self._wave_font_drop, fill=DIM, anchor="center")
            x += cw

    def _draw_wave_btn(self) -> None:
        """Redraw the button-overlay canvas with waving status text."""
        c = self._wave_canvas_btn
        c.delete("all")
        text = self._wave_btn_text or ""
        if not text:
            return
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 2 or h < 2:
            return
        total_w = sum(self._wave_font_btn.measure(ch) for ch in text)
        x = (w - total_w) / 2
        cy = h / 2
        for i, ch in enumerate(text):
            cw = self._wave_font_btn.measure(ch)
            y = cy + 5 * math.sin(self._wave_phase + i * 0.6)
            c.create_text(x + cw / 2, y, text=ch,
                          font=self._wave_font_btn, fill=DARK, anchor="center")
            x += cw

    def _wave_tick(self) -> None:
        """Periodic animation tick — runs every 40 ms for the lifetime of the app."""
        self._wave_phase += 0.25
        self._draw_wave_drop()
        if self._wave_btn_visible:
            self._draw_wave_btn()
        self.after(40, self._wave_tick)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _on_tray_toggle(self) -> None:
        self._play_click()
        """If tray is unchecked while window is hidden, restore immediately."""
        if not self._tray_var.get() and self._tray_icon is not None:
            self._restore_from_tray()

    def _on_unmap(self, event) -> None:
        """Called when window is minimized (or hidden). Route to tray if enabled."""
        if event.widget is not self:
            return
        if self._hiding_to_tray:
            return
        if not self._tray_var.get():
            return
        self._hiding_to_tray = True
        try:
            self._tray_icon = self._build_tray_icon()
            self.withdraw()
            self._tray_icon.run_detached()
        except Exception as e:
            self._tray_var.set(False)
            self._set_status(f"Tray error: {e}", WARM)
        finally:
            self._hiding_to_tray = False

    def _build_tray_icon(self) -> pystray.Icon:
        """Create a tray icon, using hoarder.ico if available."""
        _ico = Path(__file__).parent / "hoarder.ico"
        if _ico.exists():
            img = Image.open(str(_ico))
        else:
            # Fallback: generated icon using app palette
            img = Image.new("RGBA", (64, 64), (34, 35, 35, 255))
            draw = ImageDraw.Draw(img)
            draw.text((8, 20), "F\u2192M", fill=(240, 246, 240, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._tray_open, default=True),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        return pystray.Icon("Hoarder", img, "Hoarder", menu)

    def _tray_open(self, icon=None, item=None) -> None:
        self.after(0, self._restore_from_tray)

    def _tray_quit(self, icon=None, item=None) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.after(0, self.destroy)

    def _restore_from_tray(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    # ------------------------------------------------------------------
    # Windows startup shortcut
    # ------------------------------------------------------------------
    def _on_startup_toggle(self) -> None:
        self._play_click()
        try:
            if self._startup_var.get():
                self._create_startup_shortcut()
                self._set_status("Windows Startup On")
            else:
                self._remove_startup_shortcut()
                self._set_status("Windows Startup Off")
            self.after(3000, self._reset_btn_text)
        except Exception as e:
            self._set_status(f"Startup shortcut error: {e}")
            self._startup_var.set(not self._startup_var.get())  # revert

    @staticmethod
    def _startup_lnk_path() -> Path:
        import os
        startup = (
            Path(os.environ["APPDATA"])
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )
        return startup / "Hoarder.lnk"

    @staticmethod
    def _run_bat_path() -> Path:
        return Path(__file__).parent / "run.vbs"

    def _create_startup_shortcut(self) -> None:
        """Create a .lnk in the Windows Startup folder pointing to run.bat."""
        import subprocess
        lnk = str(self._startup_lnk_path())
        target = str(self._run_bat_path().resolve())
        ps = (
            f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
            f'$s.TargetPath="{target}";'
            f'$s.Save()'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "PowerShell error")

    def _remove_startup_shortcut(self) -> None:
        self._startup_lnk_path().unlink(missing_ok=True)

    def _check_stale_startup_shortcut(self) -> None:
        """Recreate startup shortcut if it exists but points to wrong path."""
        if not self._startup_var.get():
            return
        lnk = self._startup_lnk_path()
        if not lnk.exists():
            try:
                self._create_startup_shortcut()
            except Exception:
                pass
            return
        import subprocess
        target_expected = str(self._run_bat_path().resolve())
        ps = f'(New-Object -COM WScript.Shell).CreateShortcut("{lnk}").TargetPath'
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            current_target = result.stdout.strip()
            if current_target != target_expected:
                try:
                    self._create_startup_shortcut()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Folder monitor
    # ------------------------------------------------------------------
    def _on_monitor_toggle(self) -> None:
        self._play_click()
        folder = self._monitor_folder_var.get()
        if self._monitor_var.get():
            if not folder:
                self._set_status("Select a folder")
                self.after(3000, self._reset_btn_text)
                self._monitor_var.set(False)
                return
            self._start_monitor(folder)
        else:
            self._stop_monitor()
            self._monitor_folder_var.set("")

    def _browse_monitor_folder(self) -> None:
        self._play_click()
        folder = filedialog.askdirectory(title="Select folder to monitor")
        if not folder:
            return
        self._monitor_folder_var.set(folder)
        if self._monitor_var.get():
            self._stop_monitor()
            self._start_monitor(folder)

    def _start_monitor(self, folder: str) -> None:
        self._stop_monitor()
        if not Path(folder).is_dir():
            self._monitor_folder_var.set("")
            self._monitor_var.set(False)
            return
        self._monitor = mmod.FolderMonitor(folder, self._on_monitor_files)
        try:
            self._monitor.start()
            self._scan_existing_files(folder)
        except Exception as e:
            self._set_status(f"Monitor error: {e}", WARM)
            self._monitor_var.set(False)
            self._monitor = None

    def _scan_existing_files(self, folder: str) -> None:
        """Trigger conversion for FLAC and video files already in the monitored folder."""
        folder_path = Path(folder)

        # --- Audio ---
        all_flacs = sorted(folder_path.rglob("*.flac"))
        paired: set[Path] = set()
        for flac in all_flacs:
            cue = flac.with_suffix(".cue")
            if cue.exists():
                self.after(0, self._load_and_auto_convert, [str(flac), str(cue)])
                paired.add(flac)
        lone_audio = [str(f) for f in all_flacs if f not in paired]
        if lone_audio:
            self.after(0, self._load_and_auto_convert, lone_audio)

        # --- Video ---
        video_exts = ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi")
        all_videos: list[Path] = []
        for pat in video_exts:
            all_videos.extend(sorted(folder_path.rglob(pat)))
        if all_videos:
            self.after(0, self._load_and_auto_convert, [str(v) for v in all_videos])

    def _stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _on_monitor_files(self, paths: List[str]) -> None:
        """Called from watchdog thread — marshal to main thread."""
        self.after(0, self._load_and_auto_convert, paths)

    def _load_and_auto_convert(self, paths: List[str]) -> None:
        """Load files from monitor and always start conversion."""
        self._load_files(paths)
        if self._mode is not None and not self._auto_convert_var.get():
            self._start_conversion()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def destroy(self) -> None:
        self._stop_monitor()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        try:
            import shutil
            shutil.rmtree(self._sound_tmp_dir, ignore_errors=True)
        except Exception:
            pass
        super().destroy()
