import array
import io
import math
import sys
import tempfile
import winreg
import threading
import tkinter as tk
import tkinter.font as tkfont
import wave
import winsound
from tkinter import filedialog
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import shutil
from torrent_downloader import TorrentDownloader

import pystray
from PIL import Image, ImageDraw

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from cue_parser import parse_cue, cue_file_ref
from converter import (
    AUDIO_EXTS, check_ffmpeg, split_and_convert, convert_files,
    delete_flacs, delete_companion_files, transcode_videos,
)
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
    flacs  = [p for p in paths if Path(p).suffix.lower() in AUDIO_EXTS]
    cues   = [p for p in paths if p.lower().endswith(".cue")]
    videos = [p for p in paths if Path(p).suffix.lower() in VIDEO_EXTS]
    others = [
        p for p in paths
        if Path(p).suffix.lower() not in AUDIO_EXTS
        and not p.lower().endswith(".cue")
        and Path(p).suffix.lower() not in VIDEO_EXTS
    ]

    if others:
        return None, [], None, [], "Unsupported file type"
    if cues and not flacs and not videos:
        return None, [], None, [], "Please also provide an audio file"
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
    """Expand any dropped folders into their contained audio, CUE, and video files.

    Searches recursively so dropping a discography/parent folder picks up files
    in all sub-albums.
    """
    _video_globs = ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi")
    result = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in sorted(AUDIO_EXTS):
                result.extend(str(f) for f in sorted(path.rglob(f"*{ext}")))
            result.extend(str(f) for f in sorted(path.rglob("*.cue")))
            for pat in _video_globs:
                result.extend(str(f) for f in sorted(path.rglob(pat)))
        else:
            result.append(p)
    return result


class App(TkinterDnD.Tk):
    def __init__(self, start_in_tray: bool = False):
        super().__init__()
        self._start_in_tray = start_in_tray
        self.withdraw()  # hide until fully built — prevents blank-window flash
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        ctk.deactivate_automatic_dpi_awareness()
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)

        self.title("Hoarder")
        self.geometry("500x620")
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
        self._conversion_queue: List[List[str]] = []
        self._torrent_downloader: Optional[TorrentDownloader] = None

        self._preload_sounds()
        self._build_ui()
        self._check_stale_startup_shortcut()
        if self._start_in_tray:
            self._go_to_tray()
        else:
            self.deiconify()  # show now that UI is fully ready

    def _build_ui(self) -> None:
        s = self._settings

        # Wave animation state (drop zone only)
        self._wave_phase: float = 0.0
        self._wave_font_drop = tkfont.Font(family="Silkscreen", size=16)
        self._wave_font_btn = tkfont.Font(family="Silkscreen", size=28)
        self._btn_fonts = [
            tkfont.Font(family="Silkscreen", size=s) for s in (28, 24, 20, 16, 12)
        ]
        self._btn_max_w = 428

        # ------------------------------------------------------------------
        # Tab view
        # ------------------------------------------------------------------
        self._tabview = ctk.CTkTabview(
            self, width=468, height=478,
            fg_color=BG,
            segmented_button_fg_color=DARK,
            segmented_button_selected_color=LIGHT,
            segmented_button_unselected_color=DARK,
            segmented_button_selected_hover_color=LIGHT,
            segmented_button_unselected_hover_color=DARK,
            segmented_button_selected_text_color=DARK,
            segmented_button_unselected_text_color=LIGHT,
            text_color=LIGHT,
            corner_radius=0,
        )
        self._tabview.place(x=16, y=8)
        self._tabview._segmented_button.configure(
            font=("Silkscreen", 16),
            border_width=2,
            border_color=LIGHT,
            corner_radius=0,
        )

        main_tab = self._tabview.add("Main")
        self._tabview.add("Downloads")
        self._tabview.add("Encoding")
        self._tabview.add("Setup")

        # ------------------------------------------------------------------
        # Main tab — drop zone + file info + convert button
        # ------------------------------------------------------------------
        self._drop_frame = tk.Frame(
            main_tab, bg=PANEL,
            highlightbackground=TEAL, highlightthickness=2, cursor="hand2",
        )
        self._drop_frame.place(x=0, y=12, width=452, height=76)

        self._drop_canvas = tk.Canvas(
            self._drop_frame, bg=PANEL, highlightthickness=0, cursor="hand2",
        )
        self._drop_canvas.pack(fill="both", expand=True)

        for widget in (self._drop_frame, self._drop_canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.bind("<Button-1>", lambda e: self._browse())

        self._scroll_text: str = ""
        self._scroll_color: str = DIM
        self._scroll_x: float = 0.0
        self._scroll_active: bool = False

        self._info_canvas = tk.Canvas(main_tab, bg=BG, highlightthickness=0)
        self._info_canvas.place(x=0, y=98, width=452, height=36)
        self._set_info("No files loaded", DIM)

        self._convert_btn = ctk.CTkButton(
            main_tab, text="Convert", font=("Silkscreen", 28), state="disabled",
            command=self._start_conversion, width=452, height=56,
            fg_color=LIGHT, hover_color=LIGHT,
            text_color=DARK, text_color_disabled=DARK, corner_radius=0,
        )
        self._convert_btn.place(x=0, y=148)
        self._set_btn_text("Convert")

        # ------------------------------------------------------------------
        # Downloads tab — torrent progress list
        # ------------------------------------------------------------------
        dl_tab = self._tabview.tab("Downloads")
        self._torrent_progress_frame = tk.Frame(dl_tab, bg=BG)
        self._torrent_progress_frame.place(x=0, y=0, width=452, height=440)
        self._torrent_progress_widgets: Dict[str, dict] = {}

        # ------------------------------------------------------------------
        # Encoding tab — conversion progress list
        # ------------------------------------------------------------------
        enc_tab = self._tabview.tab("Encoding")
        self._encoding_progress_frame = tk.Frame(enc_tab, bg=BG)
        self._encoding_progress_frame.place(x=0, y=0, width=452, height=440)
        self._encoding_progress_widgets: Dict[str, dict] = {}

        # ------------------------------------------------------------------
        # Setup tab — all settings
        # ------------------------------------------------------------------
        _ck = dict(
            font=("Silkscreen", 16), text_color=LIGHT, fg_color=LIGHT,
            border_color=LIGHT, hover_color=LIGHT, checkmark_color=DARK,
            checkbox_width=20, checkbox_height=20, corner_radius=0,
        )

        setup_tab = self._tabview.tab("Setup")

        self._delete_var = tk.BooleanVar(value=s["delete_flac"])
        self._delete_check = ctk.CTkCheckBox(
            setup_tab, text="Delete file after conversion",
            variable=self._delete_var, command=self._play_click, **_ck,
        )
        self._delete_check.place(x=0, y=8)

        self._auto_convert_var = tk.BooleanVar(value=s["auto_convert"])
        self._auto_check = ctk.CTkCheckBox(
            setup_tab, text="Auto-convert on load",
            variable=self._auto_convert_var, command=self._play_click, **_ck,
        )
        self._auto_check.place(x=0, y=40)

        self._tray_var = tk.BooleanVar(value=s["minimize_to_tray"])
        self._tray_check = ctk.CTkCheckBox(
            setup_tab, text="Minimize to tray",
            variable=self._tray_var, command=self._on_tray_toggle, **_ck,
        )
        self._tray_check.place(x=0, y=72)

        self._startup_var = tk.BooleanVar(value=s["start_on_startup"])
        self._startup_check = ctk.CTkCheckBox(
            setup_tab, text="Start on Windows startup",
            variable=self._startup_var, command=self._on_startup_toggle, **_ck,
        )
        self._startup_check.place(x=0, y=104)

        # --- Monitor folder row ---
        self._monitor_var = tk.BooleanVar(value=False)
        self._monitor_check = ctk.CTkCheckBox(
            setup_tab, text="Monitor folder",
            variable=self._monitor_var, command=self._on_monitor_toggle, **_ck,
        )
        self._monitor_check.place(x=0, y=136)

        self._monitor_browse_btn = ctk.CTkButton(
            setup_tab, text="Browse…", font=("Silkscreen", 16),
            width=94, height=28, fg_color=DARK, hover_color=DARK,
            text_color=LIGHT, border_color=LIGHT, border_width=2,
            corner_radius=0, command=self._browse_monitor_folder,
        )
        self._monitor_browse_btn.place(x=350, y=136)

        saved_folder = s["monitor_folder"] or ""
        if saved_folder and not Path(saved_folder).is_dir():
            saved_folder = ""
        self._monitor_folder_var = tk.StringVar(value=saved_folder)
        self._monitor_folder_label = tk.Label(
            setup_tab, text="", bg=BG, fg=DIM,
            font=("Silkscreen", 8), anchor="w", wraplength=0,
        )
        self._monitor_folder_label.place(x=0, y=168, width=452, height=30)
        self._monitor_folder_var.trace_add("write", lambda *_: self._update_folder_display())
        self._update_folder_display()

        # --- Torrent settings ---
        self._torrent_var = tk.BooleanVar(value=s.get("torrent_enabled", False))
        self._torrent_check = ctk.CTkCheckBox(
            setup_tab, text="Auto-download torrents",
            variable=self._torrent_var, command=self._on_torrent_toggle, **_ck,
        )
        self._torrent_check.place(x=0, y=204)

        self._torrent_download_browse_btn = ctk.CTkButton(
            setup_tab, text="Download…", font=("Silkscreen", 16),
            width=94, height=28, fg_color=DARK, hover_color=DARK,
            text_color=LIGHT, border_color=LIGHT, border_width=2,
            corner_radius=0, command=self._browse_torrent_download_folder,
        )
        self._torrent_download_browse_btn.place(x=200, y=204)

        self._torrent_finished_browse_btn = ctk.CTkButton(
            setup_tab, text="Finished…", font=("Silkscreen", 16),
            width=94, height=28, fg_color=DARK, hover_color=DARK,
            text_color=LIGHT, border_color=LIGHT, border_width=2,
            corner_radius=0, command=self._browse_torrent_finished_folder,
        )
        self._torrent_finished_browse_btn.place(x=300, y=204)

        saved_dl = s.get("torrent_download_folder") or ""
        saved_fin = s.get("torrent_finished_folder") or ""
        self._torrent_download_var = tk.StringVar(value=saved_dl)
        self._torrent_finished_var = tk.StringVar(value=saved_fin)

        self._torrent_delete_var = tk.BooleanVar(value=s.get("torrent_delete_source", False))
        self._torrent_delete_check = ctk.CTkCheckBox(
            setup_tab, text="Delete torrent file after adding",
            variable=self._torrent_delete_var, **_ck,
        )
        self._torrent_delete_check.place(x=0, y=236)

        self._magnet_handler_var = tk.BooleanVar(value=self._is_magnet_handler_registered())
        self._magnet_handler_check = ctk.CTkCheckBox(
            setup_tab, text="Open magnet links in Hoarder",
            variable=self._magnet_handler_var, command=self._on_magnet_handler_toggle, **_ck,
        )
        self._magnet_handler_check.place(x=0, y=268)

        # --- Settings traces ---
        for var in (
            self._delete_var, self._auto_convert_var,
            self._tray_var, self._startup_var,
            self._monitor_var, self._monitor_folder_var,
            self._torrent_var, self._torrent_download_var,
            self._torrent_finished_var, self._torrent_delete_var,
            self._magnet_handler_var,
        ):
            var.trace_add("write", lambda *_: self._save_settings())

        self.bind("<Unmap>", self._on_unmap)

        # Restore monitor state
        if s["monitor_folder"] and s["monitor_enabled"]:
            self._monitor_var.set(True)
            self._start_monitor(s["monitor_folder"])

        # Start animation loop
        self.after(40, self._wave_tick)

    # ------------------------------------------------------------------
    # Text truncation helpers — prevent UI overflow on status/info
    # ------------------------------------------------------------------
    @staticmethod
    def _elide(text: str, font, max_px: int) -> str:
        if not text or font.measure(text) <= max_px:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid] + "\u2026") <= max_px:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "\u2026"

    def _set_btn_text(self, text: str) -> None:
        """Set convert button text, shrinking font until it fits."""
        for font in self._btn_fonts:
            if font.measure(text) <= self._btn_max_w:
                size = font.cget("size")
                self._convert_btn.configure(text=text, font=("Silkscreen", size))
                return
        small = self._btn_fonts[-1]
        truncated = self._elide(text, small, self._btn_max_w)
        self._convert_btn.configure(
            text=truncated, font=("Silkscreen", small.cget("size"))
        )

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
        self._handle_paths(paths)

    def _browse(self) -> None:
        self._play_click()
        paths = filedialog.askopenfilenames(
            title="Select audio and/or CUE files",
            filetypes=[
                ("Audio/CUE files",
                 "*.flac *.alac *.m4a *.ape *.aiff *.aif *.dsf *.dff *.wma *.cue"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._handle_paths(list(paths))

    def _handle_paths(self, paths: List[str]) -> None:
        """Route a list of dropped or browsed paths to conversion.

        For single-disc drops (0 or 1 CUE), delegates straight to _load_files
        so the user sees the files immediately and can click Convert manually.

        For multi-disc drops (2+ CUE files), splits into per-disc batches and
        enqueues them so they run sequentially without blocking the UI.
        """
        flacs = [p for p in paths if Path(p).suffix.lower() in AUDIO_EXTS]
        cues = [p for p in paths if p.lower().endswith(".cue")]
        videos = [p for p in paths if Path(p).suffix.lower() in VIDEO_EXTS]

        if len(cues) <= 1:
            # Standard path — let detect_mode decide; show result in UI
            self._load_files(paths)
            return

        # Multi-disc: pair each CUE with its FLAC, enqueue per-disc
        cue_paths = [Path(c) for c in cues]
        flac_paths = [Path(f) for f in flacs]
        pairs = self._pair_cues_flacs(cue_paths, flac_paths)
        paired_flac_strs = {str(flac) for flac, _ in pairs}

        for flac, cue in pairs:
            self._enqueue_conversion([str(flac), str(cue)])

        # Remaining unpaired FLACs batched together
        lone = [f for f in flacs if f not in paired_flac_strs]
        if lone:
            self._enqueue_conversion(lone)

        # Videos (rare with multi-disc audio, but handle gracefully)
        if videos:
            self._enqueue_conversion(videos)

    def _load_files(self, paths: List[str]) -> None:
        mode, flacs, cue, videos, error = detect_mode(paths)
        if error:
            self._set_info(error, WARM)
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
        self._set_info("Files loaded", SAGE)
        self._convert_btn.configure(state="normal", text="Convert")

        if self._auto_convert_var.get():
            self._start_conversion()

    # ------------------------------------------------------------------
    # Status / settings
    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = GREEN) -> None:
        """Update the convert button text."""
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
            "torrent_enabled": self._torrent_var.get(),
            "torrent_download_folder": self._torrent_download_var.get() or None,
            "torrent_finished_folder": self._torrent_finished_var.get() or None,
            "torrent_delete_source": self._torrent_delete_var.get(),
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
        self._convert_btn.configure(state="disabled", text="Converting...")

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

        # Register encoding tasks in the Encoding tab
        self.after(0, self._clear_encoding_progress)
        for f in flacs:
            self.after(0, self._add_encoding_progress, f, Path(f).name)
        for v in videos:
            self.after(0, self._add_encoding_progress, v, Path(v).name)

        def on_audio_progress(cur: int, total: int) -> None:
            completed[0] = cur
            if flacs and 0 <= cur - 1 < len(flacs):
                self.after(0, self._set_converting_file, flacs[cur - 1])
                self.after(0, self._update_encoding_progress, flacs[cur - 1], 1.0)
            pct = int(completed[0] / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")

        _last_video_idx = [-1]

        def on_video_progress(cur: float, total: int) -> None:
            idx = min(int(cur), total - 1)
            if idx != _last_video_idx[0] and 0 <= idx < len(videos):
                _last_video_idx[0] = idx
                self.after(0, self._set_converting_file, videos[idx])
            if 0 <= idx < len(videos):
                frac = cur - int(cur) if cur > 0 else 0.0
                self.after(0, self._update_encoding_progress, videos[idx], min(frac, 1.0))
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
                    delete_companion_files(flacs, cue)

            # --- Video ---
            if videos:
                transcode_videos(videos, on_video_progress, delete_source=do_delete)

            # Copy converted files to finished folder
            finished = self._torrent_finished_var.get()
            if finished and Path(finished).is_dir():
                outputs = []
                if flacs:
                    if cue:
                        for track in parse_cue(cue):
                            outputs.append(str(Path(flacs[0]).parent / f"{track.number:02d} - {track.title}.mp3"))
                    else:
                        for f in flacs:
                            outputs.append(str(Path(f).parent / (Path(f).stem + ".mp3")))
                for v in videos:
                    src = Path(v)
                    if src.suffix.lower() == ".mp4":
                        outputs.append(str(src.parent / (src.stem + ".hevc.mp4")))
                    else:
                        outputs.append(str(src.parent / (src.stem + ".mp4")))
                from converter import copy_to_finished
                copy_to_finished(outputs, finished)

            # Done
            self.after(0, self._play_done)
            self.after(0, self._show_done)
            self.after(3000, self._clear_encoding_progress)
            if do_delete:
                self.after(3000, self._reset_ui)

        except ValueError as e:
            self.after(0, self._hide_wave_btn, f"Could not parse CUE file: {e}")
        except RuntimeError as e:
            self.after(0, self._hide_wave_btn, str(e))
        except Exception as e:
            self.after(0, self._hide_wave_btn, f"Unexpected error: {e}")
        finally:
            self._is_converting = False
            self.after(0, lambda: self._convert_btn.configure(state="normal"))
            self.after(0, self._process_next_queue_item)

    def _reset_btn_text(self) -> None:
        """Restore button text to Convert without touching file state."""
        self._convert_btn.configure(text="Convert")

    def _reset_ui(self) -> None:
        """Reset the UI to idle state after a completed conversion.

        Guarded: does nothing if another conversion is in progress or the
        queue still has items waiting (e.g. disc 2 of a multi-disc set).
        """
        if self._is_converting or self._conversion_queue:
            return
        self._flac_paths = []
        self._cue_path = None
        self._mode = None
        self._video_paths = []
        self._set_info("No files loaded", DIM)
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

    def _wave_tick(self) -> None:
        """Periodic animation tick — runs every 40 ms for the lifetime of the app."""
        self._wave_phase += 0.25
        self._draw_wave_drop()
        self.after(40, self._wave_tick)

    def _hide_wave_btn(self, text: str) -> None:
        """Restore normal button text after conversion and freeze any info scroll."""
        self._convert_btn.configure(text=text)
        # Stop marquee and show the last filename as static text
        if self._scroll_active and self._scroll_text:
            self._set_info(self._scroll_text, self._scroll_color)

    def _set_info(self, text: str, color: str) -> None:
        """Draw static text in the info area and stop any active scroll."""
        self._scroll_active = False
        c = self._info_canvas
        c.delete("all")
        c.create_text(4, 18, text=text, font=self._wave_font_drop,
                      fill=color, anchor="w")

    def _start_scroll(self, text: str, color: str) -> None:
        """Scroll text left in the info area; falls back to static if it fits.

        Uses a dual threshold so long filenames always scroll even when the
        Silkscreen font fails to register in the bundled exe and tkinter
        substitutes a narrower fallback (which would otherwise give a false
        'it fits' measurement).
        """
        font = self._wave_font_drop
        # Scroll if the text is measurably wide OR simply has many characters.
        # The character-count guard catches the font-substitution case where
        # font.measure() under-reports width.
        if font.measure(text) <= 440 and len(text) <= 35:
            self._set_info(text, color)
            return
        was_active = self._scroll_active
        self._scroll_active = True
        self._scroll_text = text
        self._scroll_color = color
        self._scroll_x = 0.0                  # start with text flush to left edge
        if not was_active:
            self._scroll_tick()               # kick off the loop only once

    def _scroll_tick(self) -> None:
        """Advance the info-area marquee by one step (self-scheduling, 40 ms)."""
        if not self._scroll_active:
            return
        font = self._wave_font_drop
        text = self._scroll_text
        color = self._scroll_color
        text_w = font.measure(text)
        gap = 48                              # pixel gap before the repeated copy

        self._scroll_x -= 1.5
        if self._scroll_x <= -(text_w + gap):
            self._scroll_x = 0.0             # seamless loop: reset to start

        c = self._info_canvas
        c.delete("all")
        x = self._scroll_x + 4
        # primary instance
        c.create_text(x, 18, text=text, font=font, fill=color, anchor="w")
        # lookahead copy so the repeat appears before the primary exits
        c.create_text(x + text_w + gap, 18, text=text, font=font,
                      fill=color, anchor="w")
        self.after(40, self._scroll_tick)

    def _set_converting_file(self, path: str) -> None:
        """Scroll (or show) the currently converting file name in the info area."""
        self._start_scroll(Path(path).name, SAGE)

    def _show_done(self) -> None:
        """Called on successful conversion completion."""
        self._hide_wave_btn("Done.")
        # Leave the info label showing the last converted filename so the user
        # can see what was processed. _reset_ui (auto-called 3 s later when
        # delete_flac is on, or on next file load) will clear it.

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

    def _go_to_tray(self) -> None:
        """Hide window and start tray icon immediately (used for --tray launch)."""
        self._tray_icon = self._build_tray_icon()
        try:
            self._tray_icon.run_detached()
        except Exception as e:
            self._tray_var.set(False)
            self._set_status(f"Tray error: {e}", WARM)

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
        # When running as a PyInstaller bundle, point the startup shortcut at
        # the exe itself rather than the dev-only run.vbs script.
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        return Path(__file__).parent / "run.vbs"

    def _create_startup_shortcut(self) -> None:
        """Create a .lnk in the Windows Startup folder with --tray argument."""
        import subprocess
        lnk = str(self._startup_lnk_path())
        target = str(self._run_bat_path().resolve())
        ps = (
            f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{lnk}");'
            f'$s.TargetPath="{target}";'
            f'$s.Arguments="--tray";'
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

    def _on_torrent_toggle(self) -> None:
        self._play_click()
        if self._torrent_var.get():
            self._start_torrent_downloader()
        else:
            self._stop_torrent_downloader()

    # ------------------------------------------------------------------
    # Magnet protocol handler (Windows registry)
    # ------------------------------------------------------------------
    def _on_magnet_handler_toggle(self) -> None:
        self._play_click()
        try:
            if self._magnet_handler_var.get():
                self._register_magnet_handler()
            else:
                self._unregister_magnet_handler()
        except OSError as e:
            self._set_status(f"Magnet handler error: {e}", WARM)
            self._magnet_handler_var.set(not self._magnet_handler_var.get())

    @staticmethod
    def _magnet_handler_exe_cmd() -> str:
        """Return the command string for the magnet protocol handler."""
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable)
            return f'"{exe}" --magnet "%1"'
        # Development mode: python.exe main.py --magnet "%1"
        exe = Path(sys.executable)
        script = Path(__file__).parent / "main.py"
        return f'"{exe}" "{script}" --magnet "%1"'

    def _register_magnet_handler(self) -> None:
        """Register Hoarder as the magnet: URI handler for the current user."""
        cmd = self._magnet_handler_exe_cmd()
        # 1. Protocol class entry
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Magnet protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet\shell\open\command"
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd)
        # 2. Capabilities entry (what Chrome/Edge look for)
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\Hoarder\Capabilities"
        ) as key:
            winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, "Hoarder")
            winreg.SetValueEx(
                key, "ApplicationDescription", 0, winreg.REG_SZ,
                "Torrent and media converter",
            )
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\Hoarder\Capabilities\URLAssociations",
        ) as key:
            winreg.SetValueEx(key, "magnet", 0, winreg.REG_SZ, "magnet")
        # 3. Registered applications entry
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications"
        ) as key:
            winreg.SetValueEx(
                key, "Hoarder", 0, winreg.REG_SZ,
                r"Software\Classes\Hoarder\Capabilities",
            )

    def _unregister_magnet_handler(self) -> None:
        """Remove Hoarder as the magnet: URI handler."""
        # Remove RegisteredApplications entry
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications",
                0, winreg.KEY_ALL_ACCESS,
            ) as key:
                winreg.DeleteValue(key, "Hoarder")
        except FileNotFoundError:
            pass
        except OSError:
            pass
        # Remove Capabilities/URLAssociations
        for subkey in [
            r"Software\Classes\Hoarder\Capabilities\URLAssociations",
            r"Software\Classes\Hoarder\Capabilities",
            r"Software\Classes\Hoarder",
        ]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        # Remove protocol class
        for subkey in [
            r"Software\Classes\magnet\shell\open\command",
            r"Software\Classes\magnet\shell\open",
            r"Software\Classes\magnet\shell",
            r"Software\Classes\magnet",
        ]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _is_magnet_handler_registered() -> bool:
        """Check if Hoarder is currently registered as the magnet handler."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\Hoarder\Capabilities\URLAssociations",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "magnet")
                return val == "magnet"
        except FileNotFoundError:
            return False

    def _handle_magnet_link(self, magnet_uri: str) -> None:
        """Handle a magnet URI passed via command line or browser."""
        if not self._torrent_var.get():
            self._torrent_var.set(True)
            self._start_torrent_downloader()
        if self._torrent_downloader:
            self._torrent_downloader.add(magnet_uri)
            self._set_status(f"Added magnet link")

    def _browse_torrent_download_folder(self) -> None:
        self._play_click()
        folder = filedialog.askdirectory(title="Select torrent download folder")
        if folder:
            self._torrent_download_var.set(folder)
            if self._torrent_var.get():
                self._stop_torrent_downloader()
                self._start_torrent_downloader()

    def _browse_torrent_finished_folder(self) -> None:
        self._play_click()
        folder = filedialog.askdirectory(title="Select finished folder")
        if folder:
            self._torrent_finished_var.set(folder)

    def _start_torrent_downloader(self) -> None:
        self._stop_torrent_downloader()
        dl = self._torrent_download_var.get()
        if not dl:
            self._set_status("Select a download folder", WARM)
            self._torrent_var.set(False)
            return
        self._torrent_downloader = TorrentDownloader(
            dl,
            on_progress=self._on_torrent_progress,
            on_complete=self._on_torrent_complete,
        )
        self._torrent_downloader.start()

    def _stop_torrent_downloader(self) -> None:
        if self._torrent_downloader:
            self._torrent_downloader.stop()
            self._torrent_downloader = None
        for tid in list(self._torrent_progress_widgets):
            self._remove_torrent_progress(tid)

    def _on_torrent_progress(self, tid: str, name: str, progress: float) -> None:
        self.after(0, self._update_torrent_progress, tid, name, progress)

    def _update_torrent_progress(self, tid: str, name: str, progress: float) -> None:
        if progress < 0:
            if tid not in self._torrent_progress_widgets:
                self._add_torrent_progress_row(tid, name)
            widgets = self._torrent_progress_widgets[tid]
            widgets["bar"].set(0)
            widgets["label"].config(text="Error", fg=WARM)
            widgets["name_lbl"].config(fg=WARM)
            self.after(5000, self._remove_torrent_progress, tid)
            return
        if tid not in self._torrent_progress_widgets:
            self._add_torrent_progress_row(tid, name)
        widgets = self._torrent_progress_widgets[tid]
        pct = int(progress * 100)
        widgets["bar"].set(progress)
        widgets["label"].config(text=f"{pct}%")

    def _add_torrent_progress_row(self, tid: str, name: str) -> None:
        frame = tk.Frame(self._torrent_progress_frame, bg=DARK)
        frame.pack(fill="x", padx=2, pady=1)
        short_name = name if len(name) <= 25 else name[:22] + "..."
        name_lbl = tk.Label(frame, text=short_name, bg=DARK, fg=SAGE,
                            font=("Silkscreen", 8), anchor="w", width=200)
        name_lbl.pack(side="left")
        bar = ctk.CTkProgressBar(frame, width=180, height=14)
        bar.set(0)
        bar.pack(side="left", padx=(4, 4))
        pct = tk.Label(frame, text="0%", bg=DARK, fg=TEXT,
                        font=("Silkscreen", 8), width=4)
        pct.pack(side="left")
        self._torrent_progress_widgets[tid] = {
            "frame": frame, "bar": bar, "label": pct, "name_lbl": name_lbl,
        }

    def _remove_torrent_progress(self, tid: str) -> None:
        widgets = self._torrent_progress_widgets.pop(tid, None)
        if widgets:
            widgets["frame"].destroy()

    def _on_torrent_complete(self, tid: str, download_path: str) -> None:
        self.after(0, self._on_torrent_complete_gui, tid, download_path)

    def _on_torrent_complete_gui(self, tid: str, download_path: str) -> None:
        self._remove_torrent_progress(tid)
        monitor_folder = self._monitor_folder_var.get()
        if monitor_folder and Path(monitor_folder).is_dir():
            self._copy_downloaded_to_monitor(download_path, monitor_folder)
        self._scan_and_convert_downloaded(download_path)

    # ------------------------------------------------------------------
    # Encoding progress (Encoding tab)
    # ------------------------------------------------------------------
    def _add_encoding_progress(self, task_id: str, name: str) -> None:
        frame = tk.Frame(self._encoding_progress_frame, bg=BG)
        frame.pack(fill="x", padx=2, pady=1)
        short_name = name if len(name) <= 25 else name[:22] + "..."
        name_lbl = tk.Label(frame, text=short_name, bg=BG, fg=SAGE,
                            font=("Silkscreen", 8), anchor="w", width=200)
        name_lbl.pack(side="left")
        bar = ctk.CTkProgressBar(frame, width=180, height=14)
        bar.set(0)
        bar.pack(side="left", padx=(4, 4))
        pct = tk.Label(frame, text="0%", bg=BG, fg=TEXT,
                        font=("Silkscreen", 8), width=4)
        pct.pack(side="left")
        self._encoding_progress_widgets[task_id] = {
            "frame": frame, "bar": bar, "label": pct, "name_lbl": name_lbl,
        }

    def _update_encoding_progress(self, task_id: str, progress: float) -> None:
        widgets = self._encoding_progress_widgets.get(task_id)
        if not widgets:
            return
        pct = int(progress * 100)
        widgets["bar"].set(progress)
        widgets["label"].config(text=f"{pct}%")

    def _remove_encoding_progress(self, task_id: str) -> None:
        widgets = self._encoding_progress_widgets.pop(task_id, None)
        if widgets:
            widgets["frame"].destroy()

    def _clear_encoding_progress(self) -> None:
        for task_id in list(self._encoding_progress_widgets):
            self._remove_encoding_progress(task_id)

    def _copy_downloaded_to_monitor(self, download_path: str, monitor_folder: str) -> None:
        src = Path(download_path)
        dst = Path(monitor_folder)
        if not src.exists():
            return
        for ext in list(AUDIO_EXTS) + list(VIDEO_EXTS):
            for f in src.rglob(f"*{ext}"):
                try:
                    shutil.copy2(str(f), str(dst / f.name))
                except OSError:
                    pass

    def _scan_and_convert_downloaded(self, download_path: str) -> None:
        paths = []
        p = Path(download_path)
        for ext in AUDIO_EXTS:
            paths.extend(str(f) for f in p.rglob(f"*{ext}"))
        for pat in ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi"):
            paths.extend(str(f) for f in p.rglob(pat))
        if paths:
            self._enqueue_conversion(paths)

    def _start_monitor(self, folder: str) -> None:
        self._stop_monitor()
        if not Path(folder).is_dir():
            self._monitor_folder_var.set("")
            self._monitor_var.set(False)
            return
        self._monitor = mmod.FolderMonitor(
            folder, 
            self._on_monitor_files,
            self._on_torrent_files,
        )
        try:
            self._monitor.start()
            self._scan_existing_files(folder)
        except Exception as e:
            self._set_status(f"Monitor error: {e}", WARM)
            self._monitor_var.set(False)
            self._monitor = None

    def _scan_existing_files(self, folder: str) -> None:
        """Queue conversion jobs for all audio and video files in the monitored folder.

        Files are grouped by parent directory so each subfolder becomes its own
        job and all jobs run sequentially via _conversion_queue.
        """
        folder_path = Path(folder)

        # --- Audio: collect all supported formats, group by parent directory ---
        audio_by_dir: dict[Path, list[Path]] = {}
        for ext in AUDIO_EXTS:
            for audio in sorted(folder_path.rglob(f"*{ext}")):
                audio_by_dir.setdefault(audio.parent, []).append(audio)
        for d in audio_by_dir:
            audio_by_dir[d].sort()

        for dir_path, dir_audio in sorted(audio_by_dir.items()):
            cue_files = sorted(dir_path.glob("*.cue"))
            if not cue_files:
                # No CUEs — batch all audio files together
                self.after(0, self._enqueue_conversion,
                           [str(f) for f in dir_audio])
            else:
                # Pair CUEs with audio via stem-match + FILE directive fallback
                pairs = self._pair_cues_flacs(cue_files, dir_audio)
                paired_audio_set = {audio for audio, _ in pairs}
                for audio, cue in pairs:
                    self.after(0, self._enqueue_conversion,
                               [str(audio), str(cue)])
                lone = [str(f) for f in dir_audio if f not in paired_audio_set]
                if lone:
                    self.after(0, self._enqueue_conversion, lone)

        # --- Video: group by parent directory ---
        videos_by_dir: dict[Path, list[str]] = {}
        for pat in ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi"):
            for vid in sorted(folder_path.rglob(pat)):
                videos_by_dir.setdefault(vid.parent, []).append(str(vid))
        for dir_path in sorted(videos_by_dir):
            self.after(0, self._enqueue_conversion, videos_by_dir[dir_path])

    @staticmethod
    def _pair_cues_flacs(
        cue_paths: List[Path], flac_paths: List[Path]
    ) -> List[Tuple[Path, Path]]:
        """Pair CUE files with audio files, returning a list of (audio, cue) tuples.

        Matching strategy (in order):
        1. Stem match — ``album.cue`` pairs with ``album.flac`` / ``album.ape`` etc.
        2. FILE directive fallback — reads the ``FILE "..."`` line from the CUE
           and matches its stem against the available audio files.

        Each audio file and CUE is used at most once.
        """
        flac_by_stem: Dict[str, Path] = {f.stem.lower(): f for f in flac_paths}
        used_flacs: set[str] = set()
        pairs: List[Tuple[Path, Path]] = []
        unmatched_cues: List[Path] = []

        # Pass 1: stem match
        for cue in cue_paths:
            key = cue.stem.lower()
            flac = flac_by_stem.get(key)
            if flac is not None and key not in used_flacs:
                pairs.append((flac, cue))
                used_flacs.add(key)
            else:
                unmatched_cues.append(cue)

        # Pass 2: FILE directive fallback for unmatched CUEs
        for cue in unmatched_cues:
            ref = cue_file_ref(str(cue))
            if ref:
                ref_stem = Path(ref).stem.lower()
                flac = flac_by_stem.get(ref_stem)
                if flac is not None and ref_stem not in used_flacs:
                    pairs.append((flac, cue))
                    used_flacs.add(ref_stem)

        return pairs

    def _enqueue_conversion(self, paths: List[str]) -> None:
        """Validate *paths* and add them to the conversion queue.

        Silently ignores batches that detect_mode rejects (e.g. unsupported
        types arriving from the file-system watcher).  If nothing is currently
        converting, starts processing immediately.
        """
        _, _, _, _, error = detect_mode(paths)
        if error:
            return
        self._conversion_queue.append(paths)
        self._process_next_queue_item()

    def _process_next_queue_item(self) -> None:
        """Pop and start the next batch from the queue if the app is idle.

        Called both when a new item is enqueued and at the end of every
        conversion (via the finally block in _run_conversion).
        """
        if self._is_converting or not self._conversion_queue:
            return
        paths = self._conversion_queue.pop(0)
        self._load_files(paths)
        # Start even when auto_convert is off (monitor items always convert).
        # If _load_files already started it (auto_convert=True) this is a no-op
        # because _is_converting will already be True.
        if self._mode is not None and not self._is_converting:
            self._start_conversion()

    def _stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _on_monitor_files(self, paths: List[str]) -> None:
        """Called from watchdog thread when new files arrive - marshal to main thread."""
        self.after(0, self._enqueue_conversion, paths)

    def _on_torrent_files(self, paths: List[str]) -> None:
        """Called from watchdog thread when torrent files arrive."""
        if not self._torrent_var.get() or not self._torrent_downloader:
            return
        self.after(0, self._process_torrent_files, paths)

    def _process_torrent_files(self, paths: List[str]) -> None:
        for path in paths:
            self._torrent_downloader.add(path)
            if self._torrent_delete_var.get():
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_and_auto_convert(self, paths: List[str]) -> None:
        """Queue files for conversion (kept for compatibility; delegates to queue)."""
        self._enqueue_conversion(paths)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def destroy(self) -> None:
        self._stop_monitor()
        self._stop_torrent_downloader()
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
