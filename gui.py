import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import List, Optional, Tuple

import pystray
from PIL import Image, ImageDraw

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from cue_parser import parse_cue
from converter import check_ffmpeg, split_and_convert, convert_files, delete_flacs
import settings as smod
import monitor as mmod

MODE_SPLIT = "Split + Convert"
MODE_CONVERT = "Convert Only"


def detect_mode(
    paths: List[str],
) -> Tuple[Optional[str], List[str], Optional[str], Optional[str]]:
    """Classify a list of file paths into a conversion mode.

    Returns (mode, flac_paths, cue_path, error_message).
    On error, mode is None and error_message is set.
    """
    flacs = [p for p in paths if p.lower().endswith(".flac")]
    cues = [p for p in paths if p.lower().endswith(".cue")]
    others = [
        p for p in paths
        if not p.lower().endswith(".flac") and not p.lower().endswith(".cue")
    ]

    if others:
        return None, [], None, "Unsupported file type"
    if cues and not flacs:
        return None, [], None, "Please also provide a FLAC file"
    if len(cues) > 1:
        return None, [], None, "Only one CUE file is supported at a time"
    if len(cues) == 1 and len(flacs) == 1:
        return MODE_SPLIT, flacs, cues[0], None
    if len(cues) == 1 and len(flacs) > 1:
        return None, [], None, "CUE splitting requires exactly one FLAC file"
    if len(flacs) >= 1 and not cues:
        return MODE_CONVERT, flacs, None, None
    return None, [], None, "Invalid file selection"


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


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("FLAC to MP3 Converter")
        self.geometry("500x530")
        self.resizable(False, False)
        self.configure(bg="#1a1a1a")

        self._flac_paths: List[str] = []
        self._cue_path: Optional[str] = None
        self._mode: Optional[str] = None

        self._settings = smod.load()
        self._monitor: mmod.FolderMonitor | None = None
        self._hiding_to_tray = False
        self._tray_icon = None

        self._build_ui()

    def _build_ui(self) -> None:
        s = self._settings

        # Drop zone frame
        self._drop_frame = tk.Frame(
            self,
            bg="#2b2b2b",
            highlightbackground="#555555",
            highlightthickness=2,
            cursor="hand2",
        )
        self._drop_frame.place(x=20, y=20, width=460, height=150)

        self._drop_label = tk.Label(
            self._drop_frame,
            text="Drop FLAC (+ CUE) here\nor click to browse",
            bg="#2b2b2b",
            fg="#aaaaaa",
            font=("Segoe UI", 12),
            justify="center",
        )
        self._drop_label.place(relx=0.5, rely=0.5, anchor="center")

        for widget in (self._drop_frame, self._drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.bind("<Button-1>", lambda e: self._browse())

        # File info
        self._info_label = tk.Label(
            self,
            text="No files loaded",
            bg="#1a1a1a",
            fg="#888888",
            font=("Segoe UI", 10),
            wraplength=460,
            justify="left",
            anchor="w",
        )
        self._info_label.place(x=20, y=185, width=460, height=50)

        # --- Checkboxes ---
        self._delete_var = tk.BooleanVar(value=s["delete_flac"])
        self._delete_check = ctk.CTkCheckBox(
            self, text="Delete FLAC after conversion",
            variable=self._delete_var, font=("Segoe UI", 11),
        )
        self._delete_check.place(x=20, y=245)

        self._auto_convert_var = tk.BooleanVar(value=s["auto_convert"])
        self._auto_check = ctk.CTkCheckBox(
            self, text="Auto-convert on load",
            variable=self._auto_convert_var, font=("Segoe UI", 11),
        )
        self._auto_check.place(x=20, y=275)

        self._tray_var = tk.BooleanVar(value=s["minimize_to_tray"])
        self._tray_check = ctk.CTkCheckBox(
            self, text="Minimize to tray",
            variable=self._tray_var, font=("Segoe UI", 11),
            command=self._on_tray_toggle,
        )
        self._tray_check.place(x=20, y=305)

        self._startup_var = tk.BooleanVar(value=s["start_on_startup"])
        self._startup_check = ctk.CTkCheckBox(
            self, text="Start on Windows startup",
            variable=self._startup_var, font=("Segoe UI", 11),
            command=self._on_startup_toggle,
        )
        self._startup_check.place(x=20, y=335)

        # --- Folder monitor row ---
        self._monitor_var = tk.BooleanVar(value=False)
        self._monitor_check = ctk.CTkCheckBox(
            self, text="Monitor folder",
            variable=self._monitor_var, font=("Segoe UI", 11),
            command=self._on_monitor_toggle,
        )
        self._monitor_check.place(x=20, y=365)

        self._monitor_browse_btn = ctk.CTkButton(
            self, text="Browse…", font=("Segoe UI", 11),
            width=90, height=26,
            command=self._browse_monitor_folder,
        )
        self._monitor_browse_btn.place(x=390, y=365)

        self._monitor_folder_var = tk.StringVar(
            value=s["monitor_folder"] or ""
        )
        self._monitor_folder_label = tk.Label(
            self,
            textvariable=self._monitor_folder_var,
            bg="#1a1a1a", fg="#888888",
            font=("Segoe UI", 9),
            anchor="w", wraplength=460,
        )
        self._monitor_folder_label.place(x=20, y=393, width=460, height=20)

        # Restore monitor enabled state (only if folder is saved)
        if s["monitor_folder"] and s["monitor_enabled"]:
            self._monitor_var.set(True)
            self._start_monitor(s["monitor_folder"])

        # Convert button
        self._convert_btn = ctk.CTkButton(
            self,
            text="Convert",
            font=("Segoe UI", 13, "bold"),
            state="disabled",
            command=self._start_conversion,
            width=460,
            height=45,
        )
        self._convert_btn.place(x=20, y=423)

        # Status line
        self._status_label = tk.Label(
            self,
            text="",
            bg="#1a1a1a",
            fg="#88cc88",
            font=("Segoe UI", 10),
            wraplength=460,
            anchor="w",
        )
        self._status_label.place(x=20, y=478, width=460, height=40)

        # Settings traces (save on any change)
        for var in (
            self._delete_var, self._auto_convert_var,
            self._tray_var, self._startup_var,
            self._monitor_var, self._monitor_folder_var,
        ):
            var.trace_add("write", lambda *_: self._save_settings())

        # Tray: bind minimize event
        self.bind("<Unmap>", self._on_unmap)

    def _on_drop(self, event) -> None:
        paths = parse_drop_paths(event.data)
        self._load_files(paths)

    def _browse(self) -> None:
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
        mode, flacs, cue, error = detect_mode(paths)
        if error:
            self._info_label.config(text=error, fg="#cc4444")
            self._convert_btn.configure(state="disabled")
            self._flac_paths = []
            self._cue_path = None
            self._mode = None
            return

        self._flac_paths = flacs
        self._cue_path = cue
        self._mode = mode

        names = ", ".join(Path(p).name for p in paths)
        self._info_label.config(
            text=f"{names}\nMode: {mode}",
            fg="#cccccc",
        )
        self._convert_btn.configure(state="normal")
        self._status_label.config(text="", fg="#88cc88")

        if self._auto_convert_var.get():
            self._start_conversion()

    def _set_status(self, text: str, color: str = "#88cc88") -> None:
        """Update the status label. Must be called from the main thread only."""
        self._status_label.config(text=text, fg=color)
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

    def _start_conversion(self) -> None:
        if not check_ffmpeg():
            self._set_status(
                "ffmpeg not found. Please install it and ensure it's on your PATH.",
                "#cc4444",
            )
            return

        self._convert_btn.configure(state="disabled")
        self._set_status("Starting...", "#cccccc")

        thread = threading.Thread(target=self._run_conversion, daemon=True)
        thread.start()

    def _run_conversion(self) -> None:
        flacs_to_delete = self._flac_paths[:]
        try:
            if self._mode == MODE_SPLIT:
                tracks = parse_cue(self._cue_path)
                split_and_convert(
                    self._flac_paths[0],
                    tracks,
                    lambda cur, total: self.after(
                        0, self._set_status,
                        f"Converting track {cur} of {total}...", "#cccccc",
                    ),
                )
            else:
                convert_files(
                    self._flac_paths,
                    lambda cur, total: self.after(
                        0, self._set_status,
                        f"Converting file {cur} of {total}...", "#cccccc",
                    ),
                )

            if self._delete_var.get():
                warning = delete_flacs(flacs_to_delete)
                if warning:
                    self.after(0, self._set_status,
                               f"Done. {warning}", "#ccaa44")
                else:
                    self.after(0, self._set_status,
                               "Done. FLAC files deleted.", "#88cc88")
            else:
                self.after(0, self._set_status, "Done.", "#88cc88")

        except ValueError as e:
            self.after(0, self._set_status,
                       f"Could not parse CUE file: {e}", "#cc4444")
        except RuntimeError as e:
            self.after(0, self._set_status, str(e), "#cc4444")
        except Exception as e:
            self.after(0, self._set_status,
                       f"Unexpected error: {e}", "#cc4444")
        finally:
            self.after(0, lambda: self._convert_btn.configure(state="normal"))

    def _on_tray_toggle(self) -> None:
        """If tray is unchecked while window is hidden, restore immediately."""
        if not self._tray_var.get() and self._tray_icon is not None:
            self._restore_from_tray()

    def _on_startup_toggle(self) -> None:
        pass  # implemented in Task 7

    def _on_monitor_toggle(self) -> None:
        folder = self._monitor_folder_var.get()
        if self._monitor_var.get():
            if not folder:
                self._set_status("Select a folder to monitor first.", "#cc4444")
                self._monitor_var.set(False)
                return
            self._start_monitor(folder)
        else:
            self._stop_monitor()

    def _browse_monitor_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder to monitor")
        if not folder:
            return
        self._monitor_folder_var.set(folder)
        # If monitor checkbox is on, restart with new folder
        if self._monitor_var.get():
            self._stop_monitor()
            self._start_monitor(folder)

    def _start_monitor(self, folder: str) -> None:
        self._stop_monitor()
        self._monitor = mmod.FolderMonitor(folder, self._on_monitor_files)
        try:
            self._monitor.start()
            self._set_status(f"Monitoring: {folder}", "#88cc88")
        except Exception as e:
            self._set_status(f"Monitor error: {e}", "#cc4444")
            self._monitor_var.set(False)
            self._monitor = None

    def _stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _on_monitor_files(self, paths: List[str]) -> None:
        """Called from watchdog thread — marshal to main thread."""
        self.after(0, self._load_and_auto_convert, paths)

    def _load_and_auto_convert(self, paths: List[str]) -> None:
        """Load files from monitor and always start conversion.

        _load_files may already trigger conversion when auto_convert is on.
        Only call _start_conversion here when it hasn't been triggered yet.
        """
        self._load_files(paths)
        # _load_files calls _start_conversion when auto_convert is on.
        # When auto_convert is off we still want to convert (monitor always converts).
        if self._mode is not None and not self._auto_convert_var.get():
            self._start_conversion()

    def destroy(self) -> None:
        self._stop_monitor()
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        super().destroy()

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
            self._set_status(f"Tray error: {e}", "#cc4444")
        finally:
            self._hiding_to_tray = False

    def _build_tray_icon(self) -> pystray.Icon:
        """Create a 64x64 tray icon with 'F→M' text."""
        img = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
        draw = ImageDraw.Draw(img)
        draw.text((8, 20), "F\u2192M", fill=(200, 200, 200, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Open", self._tray_open, default=True),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        return pystray.Icon("FLAC Converter", img, "FLAC Converter", menu)

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
