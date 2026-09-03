import array
import io
import math
import os
import random
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
from torrent_downloader import (
    TorrentDownloader, STAGING_DIRNAME, PROGRESS_QUEUED,
    MIN_MAX_ACTIVE, MAX_MAX_ACTIVE, clamp_max_active,
    ARIA2_CONTROL_SUFFIX, has_incomplete_download,
    sweep_stale_staged_torrents,
)

import pystray
from PIL import Image, ImageDraw, ImageFont, ImageTk

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from cue_parser import parse_cue, cue_file_ref
from converter import (
    AUDIO_EXTS, check_ffmpeg, split_and_convert, convert_files,
    delete_flacs, delete_companion_files, transcode_videos, video_output_path,
)
import settings as smod
import monitor as mmod
import library as libmod
import session as sess

MODE_SPLIT  = "Split + Convert"
MODE_CONVERT = "Convert Only"
MODE_VIDEO  = "Video Transcode"
MODE_MIXED  = "Mixed"

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".wmv", ".avi"}
TORRENT_EXTS = {".torrent", ".magnet"}


def split_torrent_paths(paths: List[str]) -> Tuple[List[str], List[str]]:
    """Split *paths* into (torrent_paths, other_paths).

    Torrent paths are .torrent/.magnet files and raw magnet:? URIs.
    """
    torrents: List[str] = []
    others: List[str] = []
    for p in paths:
        if p.startswith("magnet:?") or Path(p).suffix.lower() in TORRENT_EXTS:
            torrents.append(p)
        else:
            others.append(p)
    return torrents, others

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

# Overall UI scale — everything pixel-sized in this file is defined in terms
# of this, so the whole app can be resized as one proportional unit.
SCALE = 1

# Progress bars: white fill on the dark track, hard corners, 1 px white outline
BAR_W = 190 * SCALE
BAR_H = 18 * SCALE
BAR_FONT_PX = 16 * SCALE   # Silkscreen renders crisp at its design sizes (8, 16, …)

# ---------------------------------------------------------------------------
# Layout — every white box keeps the same margin from the tab outline
# ---------------------------------------------------------------------------
PAD      = 8 * SCALE     # gap between the tab outline and a box, and between boxes
INNER    = 10 * SCALE    # gap between a box outline and its contents
TAB_W    = 468 * SCALE   # tabview width
DROP_H   = 72 * SCALE
# The drop zone grows upward into its own top margin: it gets taller without
# pushing the downloads/encoding boxes down, so PAGE_H stays as computed below.
DROP_RISE = 8 * SCALE
# The drop zone ran out of room at the page's top edge — ctk pins the page to
# 2px below the tab chips, and the chips' height is driven by the 32px tab
# font, not by any height setting. The last 2px therefore come from thinning
# the chips' border (3px -> BORDER), which lifts the page by exactly this
# much. Every page-relative y BELOW the drop zone is pushed back down by the
# same amount, so only the drop zone's top edge actually moves on screen.
PAGE_LIFT = 2 * SCALE
# The Setup tab's content box tracks the drop zone: it rises by the same total
# the drop zone gained, growing upward from a fixed bottom edge so the two
# tabs' boxes still end level with each other.
SETUP_RISE = DROP_RISE + PAGE_LIFT
LIST_H   = 148 * SCALE   # downloads box and encoding box
CORNER_R = 4 * SCALE     # corner radius of the white boxes and the tab chips

# customtkinter's tabview spends a fixed 36px on its tab strip regardless of
# widget scaling (that's baked into CTkTabview's own class constants, not
# something a border_width/font choice can resize) — only the border-driven
# padding around the page content actually scales with BORDER below.
BORDER = 2 * SCALE
# Measured against the 36px-tall segmented button (32px tab font): 10px of
# top padding + 46px rendered button (ctk adds its own internal padding to
# the configured 36) + 2px gap before the page. Too small a value here
# CLIPS the page's bottom — the encoding box's lower outline simply doesn't
# render — because the pages get TAB_H minus this chrome to draw in.
_TAB_CHROME_H = 58 * SCALE
_TAB_CHROME_W = 2 * BORDER
SCROLL_INSET = 8 * SCALE   # gap between a scroll box's outline and its CTkScrollableFrame

PAGE_W   = TAB_W - _TAB_CHROME_W
PAGE_H   = PAD + DROP_H + PAD + LIST_H + PAD + LIST_H + PAD
BOX_W    = PAGE_W - 2 * PAD
TAB_H    = PAGE_H + _TAB_CHROME_H
# Side margin between the window edge and the tabview — wide enough for
# the 48px corner skulls straddling the border line to fit unclipped.
SIDE_M = 24 * SCALE
WINDOW_W = TAB_W + 2 * SIDE_M
# Extra bottom room so the bottom chain run and corner skulls — dropped
# 16px below the tabview edge to clear the encoding box — aren't clipped
# by the window edge.
WINDOW_H = TAB_H + 2 * PAD + 30 * SCALE


def _corner_steps(radius: int) -> tuple:
    """Pixel-art quarter circle: how many pixels to knock out of each row,
    working inward from a box corner, to round it at `radius`.

    radius 4 -> (4, 2, 1, 1); radius 2 -> (2, 1). Symmetric in x/y, so the
    same tuple describes both the rows and the columns of the corner.
    """
    r = max(int(radius), 0)
    return tuple(
        sum(1 for dx in range(r) if (r - dx) ** 2 + (r - dy) ** 2 > r * r)
        for dy in range(r)
    )


class PixelBar(tk.Label):
    """Progress bar with the percentage printed inside it.

    Rendered as an image rather than assembled from widgets: that is the only
    way to invert the digits *exactly* where the fill passes under them —
    dark text on the filled part, light text on the rest — instead of flipping
    a whole character at a time.
    """

    _fonts: Dict[int, "ImageFont.FreeTypeFont"] = {}

    def __init__(self, master, width: int = BAR_W, height: int = BAR_H):
        super().__init__(master, bd=0, highlightthickness=0, bg=BG)
        # Not _w/_h: tkinter.Misc uses _w for the widget's Tcl path name.
        self._bar_w = width
        self._bar_h = height
        self._value = 0.0
        self._text = "0%"
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._render()

    # -- geometry ------------------------------------------------------
    @staticmethod
    def _fill_px(value: float, width: int) -> int:
        """Filled width in pixels, inside the 1 px border on each side."""
        value = min(max(value, 0.0), 1.0)
        return int(round((width - 2) * value))

    @classmethod
    def _font(cls, size: int) -> "ImageFont.FreeTypeFont":
        font = cls._fonts.get(size)
        if font is None:
            ttf = Path(__file__).parent / "slkscr.ttf"
            try:
                font = ImageFont.truetype(str(ttf), size)
            except OSError:
                font = ImageFont.load_default()
            cls._fonts[size] = font
        return font

    # -- public --------------------------------------------------------
    def set(self, value: float, text: Optional[str] = None) -> None:
        value = min(max(value, 0.0), 1.0)
        text = f"{int(value * 100)}%" if text is None else text
        if value == self._value and text == self._text:
            return
        self._value = value
        self._text = text
        self._render()

    # -- drawing -------------------------------------------------------
    def _render(self) -> None:
        w, h = self._bar_w, self._bar_h
        base = Image.new("RGB", (w, h), DARK)
        draw = ImageDraw.Draw(base)
        draw.rectangle((0, 0, w - 1, h - 1), outline=LIGHT)
        fill = self._fill_px(self._value, w)
        if fill:
            draw.rectangle((1, 1, fill, h - 2), fill=LIGHT)

        # 1-bit layer keeps the pixel font free of anti-aliasing
        mask = Image.new("1", (w, h), 0)
        ImageDraw.Draw(mask).text(
            (w / 2, h / 2), self._text, fill=1,
            font=self._font(BAR_FONT_PX), anchor="mm",
        )
        img = base.copy()
        img.paste(LIGHT, (0, 0, w, h), mask)
        if fill:
            over = base.copy()
            over.paste(DARK, (0, 0, w, h), mask)
            img.paste(over.crop((1, 1, fill + 1, h - 1)), (1, 1))

        self._photo = ImageTk.PhotoImage(img)
        self.configure(image=self._photo)


class PixelSlider(PixelBar):
    """PixelBar the user can drag: click anywhere on the track to set the
    value. Same hard-cornered, inverted-digits look as the progress bars."""

    def __init__(self, master, on_change=None, on_commit=None,
                 width: int = BAR_W, height: int = BAR_H,
                 steps: int = 10, fmt=None):
        super().__init__(master, width=width, height=height)
        self._on_change = on_change
        self._on_commit = on_commit
        # Number of gaps between stops: 10 gives the volume slider's 10%
        # detents, 19 puts a stop on each of 20 discrete values.
        self._steps = max(1, steps)
        # How the value reads inside the bar. Default is PixelBar's percentage.
        self._fmt = fmt
        self.configure(cursor="hand2")
        self.bind("<Button-1>", self._on_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set(self, value: float, text: Optional[str] = None) -> None:
        if text is None and self._fmt is not None:
            text = self._fmt(min(max(value, 0.0), 1.0))
        super().set(value, text)

    def _value_from_event(self, event) -> float:
        raw = min(max((event.x - 1) / (self._bar_w - 2), 0.0), 1.0)
        return round(raw * self._steps) / self._steps

    def _on_drag(self, event) -> None:
        value = self._value_from_event(event)
        self.set(value)
        if self._on_change:
            self._on_change(value)

    def _on_release(self, event) -> None:
        if self._on_commit:
            self._on_commit(self._value)


# The active-download slider carries one stop per allowed value rather than
# the volume slider's 10% detents, so every position is a whole number of
# downloads and there is nothing in between to land on.
DL_SLIDER_STEPS = MAX_MAX_ACTIVE - MIN_MAX_ACTIVE


def dl_count_to_fraction(count) -> float:
    """Slider position (0.0–1.0) for a download limit."""
    return (clamp_max_active(count) - MIN_MAX_ACTIVE) / DL_SLIDER_STEPS


def dl_fraction_to_count(fraction: float) -> int:
    """Download limit for a slider position."""
    fraction = min(max(fraction, 0.0), 1.0)
    return clamp_max_active(round(fraction * DL_SLIDER_STEPS) + MIN_MAX_ACTIVE)


def format_torrent_name(name: str, limit: int = 20) -> str:
    cleaned = name.replace(".", "").replace("-", "")
    return cleaned[:limit]


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

        self.title("Plunder")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
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
        self._staging_sweep_after_id: Optional[str] = None
        self._hiding_to_tray = False
        self._tray_icon = None
        self._is_converting = False
        self._conversion_queue: List[List[str]] = []
        # The batch currently being encoded, once popped off the queue. Kept
        # separately so a session record covers work in flight, not just work
        # still waiting.
        self._active_batch: Optional[List[str]] = None
        self._torrent_downloader: Optional[TorrentDownloader] = None
        # Download records a restore could not act on (torrents disabled, or
        # the staged .torrent gone). Written back out by _save_session so they
        # are not lost along with the partial data they refer to.
        self._unresumed_downloads: List[dict] = []
        # Files this app is about to write into the monitored folder. The
        # watcher skips them so a transcode does not re-enter the queue.
        self._ignore_paths: set[str] = set()
        self._ignore_lock = threading.Lock()

        self._preload_sounds()
        self._build_ui()
        # Both of these repair registrations an earlier build left pointing
        # somewhere else. Neither is worth a crash: they run before the window
        # exists, so anything escaping here dies as a bare traceback with no UI
        # to report it — which is exactly how a refused PowerShell spawn used
        # to take the whole app down at launch.
        for _repair in (self._check_stale_startup_entry, self._check_stale_handlers):
            try:
                _repair()
            except Exception:
                pass
        # After _build_ui, so the monitor and downloader it restores are
        # already up and the startup folder scan has had its say.
        self.after(200, self._restore_session)
        if self._start_in_tray:
            self._go_to_tray()
        else:
            self.deiconify()  # show now that UI is fully ready
            self.after(600, self._maybe_prompt_torrent_association)
        self._play_startup()

    def _build_ui(self) -> None:
        s = self._settings
        self._torrent_ext_asked = s.get("torrent_ext_association_asked", False)

        # Wave animation state (drop zone only)
        self._wave_phase: float = 0.0
        # Alkhemikal has a much smaller x-height than Silkscreen, so the
        # sizes here are roughly double the old Silkscreen ones for the
        # same visual weight.
        self._wave_font_drop = tkfont.Font(family="Alkhemikal", size=32 * SCALE)
        # Smaller steps so a long status message shrinks instead of eliding.
        self._wave_fonts = [self._wave_font_drop] + [
            tkfont.Font(family="Alkhemikal", size=n * SCALE) for n in (24, 20, 16)
        ]
        # The drop zone doubles as the status line: messages replace the
        # "Drag & Drop" text for a few seconds, then it reverts.
        self._drop_text: str = "Drag & Drop"
        self._drop_color: str = DIM
        self._drop_font = self._wave_font_drop
        self._drop_revert_id: Optional[str] = None

        # ------------------------------------------------------------------
        # Tab view
        # ------------------------------------------------------------------
        self._tabview = ctk.CTkTabview(
            self, width=TAB_W, height=TAB_H,
            fg_color=BG,
            corner_radius=0,
            border_width=BORDER,
            border_color=BG,  # the chain replaces the visible outline
            segmented_button_fg_color=DARK,
            segmented_button_selected_color=LIGHT,
            segmented_button_unselected_color=DARK,
            # Hover visuals are handled by _poll_tab_hover, which drives
            # BOTH the box fill and the text color from one place. ctk's
            # own event-driven hover is neutralized (hover color == base
            # color) — when its events misfired, it repainted only the
            # fill, producing dark-text-on-dark-box mismatches.
            segmented_button_selected_hover_color=LIGHT,
            segmented_button_unselected_hover_color=DARK,
            text_color=LIGHT,
        )
        self._tabview.place(x=SIDE_M, y=PAD)
        self._tabview.configure(command=self._on_tab_changed)
        # The segmented button's default height (~26px) would clip a 32px
        # font, so raise its height along with the font size.
        # corner_radius stays 0: ctk rounds all four corners uniformly, but a
        # tab chip wants square shoulders where it meets the outline, so the
        # top corners are rounded by hand in _round_tab_corners instead.
        self._tabview._segmented_button.configure(
            font=("Alkhemikal", 32), height=36, corner_radius=0,
            border_width=BORDER,
        )

        main_tab = self._tabview.add("Main")
        self._tabview.add("Setup")
        self._tabview.add("Quit")
        self._hovered_tab: Optional[str] = None
        self._hover_misses = 0
        self._update_tab_colors()

        # Hover handling is deliberately NOT event-driven: a CTk tab
        # button is composite (a canvas plus a text label), so one mouse
        # pass fires Enter/Leave storms as the pointer crosses its internal
        # parts — every event-based attempt at "play the sound once per
        # hover" broke on some crossing pattern. Instead a lightweight
        # poll checks which tab is under the pointer and reacts only to
        # actual transitions: enter a different tab → restyle + one sound;
        # leave the bar → restore colors, no sound. CTkButton's own
        # background-hover stays event-driven inside ctk, which is fine —
        # only the text color and the sound need transition accuracy.
        self.after(200, self._poll_tab_hover)

        # ------------------------------------------------------------------
        # Decorative chain border running along the tabview's gray outline.
        # Created AFTER the tabview so it draws on top of the outline
        # itself (the tabview would otherwise paint over it). The outline's
        # top edge passes through the vertical center of the tab selector
        # row, so the top run is split into two segments that stop short of
        # the menu tabs — the tabs always stay clear of the chain. The
        # corner skulls are created after this block, so they sit on top.
        # ------------------------------------------------------------------
        # The outline's top edge passes through the vertical center of the
        # segmented button — measure it rather than deriving it from the
        # fixed chrome constant, since the button's height was raised to
        # fit the 32px tab font and no longer matches that constant.
        self.update_idletasks()
        _seg_btn = self._tabview._segmented_button
        tab_row_center_y = PAD + _seg_btn.winfo_y() + _seg_btn.winfo_height() // 2
        # Bottom run sits fully below the encoding box's bottom outline:
        # 5px clearance (matching the side runs' gap to the boxes) plus
        # half the 10px chain thickness. The page's y inside the window is
        # found by walking winfo_y() up the widget tree — winfo_rooty() is
        # not reliable here because the window is still withdrawn during
        # _build_ui.
        _page_y, _w = 0, main_tab
        while _w is not self:
            _page_y += _w.winfo_y()
            _w = _w.master
        if _page_y <= 0:  # geometry not yet computed — conservative fallback
            _page_y = PAD + _TAB_CHROME_H
        bottom_line_y = _page_y + PAGE_H - PAD + 20 * SCALE

        self._chain_photos: List[ImageTk.PhotoImage] = []
        chain_path = Path(__file__).parent / "chain.png"
        if chain_path.exists():
            chain_scale = 2 * SCALE
            tile_h = Image.open(str(chain_path)).convert("RGBA")
            tile_h = tile_h.resize(
                (tile_h.width * chain_scale, tile_h.height * chain_scale), Image.NEAREST,
            )
            tile_v = tile_h.transpose(Image.ROTATE_90)

            left_border_x = SIDE_M
            right_border_x = SIDE_M + TAB_W
            bottom_border_y = bottom_line_y

            def _tiled_strip(tile_img: Image.Image, length: int, horizontal: bool) -> Image.Image:
                tw, th = tile_img.size
                if horizontal:
                    strip = Image.new("RGBA", (length, th), (0, 0, 0, 0))
                    for x in range(0, length, tw):
                        strip.paste(tile_img, (x, 0), tile_img)
                else:
                    strip = Image.new("RGBA", (tw, length), (0, 0, 0, 0))
                    for y in range(0, length, th):
                        strip.paste(tile_img, (0, y), tile_img)
                return strip

            def _place_chain(strip_img: Image.Image, x: int, y: int) -> tk.Label:
                photo = ImageTk.PhotoImage(strip_img)
                self._chain_photos.append(photo)
                lbl = tk.Label(self, image=photo, bg=BG, borderwidth=0)
                lbl.place(x=x, y=y)
                return lbl

            # Verticals run from the top outline (tab-row center) down to
            # the bottom outline; bottom run spans the full width.
            v_len = bottom_border_y - tab_row_center_y
            _place_chain(
                _tiled_strip(tile_v, v_len, False),
                left_border_x - tile_v.width // 2, tab_row_center_y,
            )
            _place_chain(
                _tiled_strip(tile_v, v_len, False),
                right_border_x - tile_v.width // 2, tab_row_center_y,
            )
            self._bottom_chain_label = _place_chain(
                _tiled_strip(tile_h, right_border_x - left_border_x, True),
                left_border_x, bottom_border_y - tile_h.height // 2,
            )

            # Top run: two segments flanking the tab selector.
            self.update_idletasks()
            seg_w = self._tabview._segmented_button.winfo_reqwidth()
            center_x = SIDE_M + TAB_W // 2
            tab_gap = 6 * SCALE
            top_y = tab_row_center_y - tile_h.height // 2
            left_len = center_x - seg_w // 2 - tab_gap - left_border_x
            if left_len > 0:
                _place_chain(_tiled_strip(tile_h, left_len, True), left_border_x, top_y)
            right_start = center_x + seg_w // 2 + tab_gap
            right_len = right_border_x - right_start
            if right_len > 0:
                _place_chain(_tiled_strip(tile_h, right_len, True), right_start, top_y)

        # Decorative skull icons on all four corners of the outline: the
        # top pair level with the tab bar, the bottom pair on the bottom
        # outline corners, each centered on the left/right border line.
        # The right-side ones are the same image mirrored horizontally.
        self._skull_photo_left: Optional[ImageTk.PhotoImage] = None
        self._skull_photo_right: Optional[ImageTk.PhotoImage] = None
        skull_path = Path(__file__).parent / "skull.png"
        if skull_path.exists():
            skull_size = 48 * SCALE
            # tab_row_center_y measured above, from the segmented button;
            # bottom pair matches the chain's lowered bottom run.
            bottom_border_y = bottom_line_y
            left_border_x = SIDE_M
            right_border_x = SIDE_M + TAB_W
            left_x = left_border_x - skull_size // 2 + 4
            right_x = right_border_x - skull_size // 2 - 4

            skull_img = Image.open(str(skull_path)).convert("RGBA")
            skull_img = skull_img.resize((skull_size, skull_size), Image.NEAREST)
            self._skull_photo_left = ImageTk.PhotoImage(skull_img)
            skull_img_flipped = skull_img.transpose(Image.FLIP_LEFT_RIGHT)
            self._skull_photo_right = ImageTk.PhotoImage(skull_img_flipped)

            self._bottom_skull_labels: List[tk.Label] = []
            for photo, x, y_center, is_bottom in (
                (self._skull_photo_left, left_x, tab_row_center_y, False),
                (self._skull_photo_right, right_x, tab_row_center_y, False),
                (self._skull_photo_left, left_x, bottom_border_y, True),
                (self._skull_photo_right, right_x, bottom_border_y, True),
            ):
                lbl = tk.Label(self, image=photo, bg=BG, borderwidth=0)
                lbl.place(x=x, y=y_center - skull_size // 2)
                if is_bottom:
                    self._bottom_skull_labels.append(lbl)

        # The bottom run's position is re-measured against the encoding
        # box's REAL bottom edge once the window is first mapped — the
        # build-time estimate above can be off in the frozen build, where
        # page geometry may not have propagated yet while the window is
        # still withdrawn. Any mismatch in the vertical runs' length that
        # this correction leaves behind hides under the corner skulls.
        self.bind("<Map>", self._position_bottom_decor, add="+")

        # ------------------------------------------------------------------
        # Main tab — drop zone, downloads box, encoding box
        # ------------------------------------------------------------------
        self._drop_frame = tk.Frame(
            main_tab, bg=PANEL,
            highlightbackground=TEAL, highlightthickness=BORDER, cursor="hand2",
        )
        drop_y, drop_h = 0, DROP_H + DROP_RISE + PAGE_LIFT
        self._drop_frame.place(x=PAD, y=drop_y, width=BOX_W, height=drop_h)
        self._notch_corners(main_tab, PAD, drop_y, BOX_W, drop_h)
        self._weather_outline(main_tab, PAD, drop_y, BOX_W, drop_h, seed=7)

        self._drop_canvas = tk.Canvas(
            self._drop_frame, bg=PANEL, highlightthickness=0, cursor="hand2",
        )
        self._drop_canvas.pack(fill="both", expand=True)

        for widget in (self._drop_frame, self._drop_canvas):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.bind("<Button-1>", lambda e: self._browse())

        # Both progress lists scroll: a large monitored folder registers one
        # row per file, which would otherwise render off the bottom of the box.
        dl_y = PAGE_LIFT + PAD + DROP_H + PAD
        self._torrent_progress_frame = self._make_scroll_box(
            main_tab, PAD, dl_y, BOX_W, LIST_H,
        )
        self._torrent_progress_widgets: Dict[str, dict] = {}

        self._encoding_progress_frame = self._make_scroll_box(
            main_tab, PAD, dl_y + LIST_H + PAD, BOX_W, LIST_H,
        )
        self._encoding_progress_widgets: Dict[str, dict] = {}

        # ------------------------------------------------------------------
        # Setup tab — all settings
        # ------------------------------------------------------------------
        _ck = dict(
            font=("Silkscreen", 16 * SCALE), text_color=LIGHT, fg_color=LIGHT,
            border_color=LIGHT, hover_color=LIGHT, checkmark_color=DARK,
            checkbox_width=20 * SCALE, checkbox_height=20 * SCALE, corner_radius=0,
        )

        # A white box like the ones on the main page, filling the same visible
        # area — but scrollable (hidden scrollbar, same trick as the Main
        # tab's progress boxes), since the proxy section below pushes the
        # content taller than the box.
        setup_tab = self._tabview.tab("Setup")
        setup_box = self._make_scroll_box(
            setup_tab, PAD, PAGE_LIFT + PAD - SETUP_RISE, BOX_W,
            PAGE_H - 2 * PAD + SETUP_RISE,
        )

        row_w = BOX_W - SCROLL_INSET   # matches _make_scroll_box's own inner inset

        # Four groups, each a plain 32px pitch, with a wider gap between
        # groups: general app behavior, then folder-watching + what happens
        # to converted output, then torrent-specific settings, then proxy.
        ROW_PITCH = 32 * SCALE
        GAP = 16 * SCALE
        y = INNER
        rows = {}
        for name in ("tray", "startup", "sounds"):
            rows[name] = y
            y += ROW_PITCH
        y += GAP
        for name in ("monitor", "delete", "move_music", "move_video"):
            rows[name] = y
            y += ROW_PITCH
        y += GAP
        for name in ("torrent", "max_downloads", "torrent_delete", "magnet", "torrent_ext"):
            rows[name] = y
            y += ROW_PITCH
        y += GAP
        for name in ("proxy_enabled", "proxy_host", "proxy_port", "proxy_user", "proxy_pass"):
            rows[name] = y
            y += ROW_PITCH
        content_h = y + INNER

        # No Convert button any more — loaded files always convert, so the
        # old "Auto-convert on load" toggle has no off state to offer.
        self._auto_convert_var = tk.BooleanVar(value=True)

        self._tray_var = tk.BooleanVar(value=s["minimize_to_tray"])
        self._tray_check = ctk.CTkCheckBox(
            setup_box, text="Minimize to tray",
            variable=self._tray_var, command=self._on_tray_toggle, **_ck,
        )
        self._tray_check.place(x=INNER, y=rows["tray"])

        self._startup_var = tk.BooleanVar(value=s["start_on_startup"])
        self._startup_check = ctk.CTkCheckBox(
            setup_box, text="Start on Windows startup",
            variable=self._startup_var, command=self._on_startup_toggle, **_ck,
        )
        self._startup_check.place(x=INNER, y=rows["startup"])

        self._sounds_var = tk.BooleanVar(value=s.get("sounds_enabled", True))
        self._sounds_check = ctk.CTkCheckBox(
            setup_box, text="Sounds",
            variable=self._sounds_var, command=self._play_checkbox, **_ck,
        )
        self._sounds_check.place(x=INNER, y=rows["sounds"])

        # Volume slider, same look as the progress bars. Live drag only
        # re-renders the percent display; the (comparatively expensive)
        # re-render of every wav at the new volume runs once on release,
        # followed by a sample sound at the new level as feedback.
        self._sound_volume = int(s.get("sound_volume", 100))

        def _volume_commit(value: float) -> None:
            self._sound_volume = int(round(value * 100))
            self._preload_sounds(volume=value)
            self._save_settings()
            self._play_checkbox()

        self._volume_slider = PixelSlider(
            setup_box, on_commit=_volume_commit,
        )
        self._volume_slider.set(self._sound_volume / 100)
        self._volume_slider.place(
            x=row_w - BAR_W - INNER, y=rows["sounds"] + 2 * SCALE,
        )

        # --- Monitor folder + what happens to converted output ---
        saved_folder = s["monitor_folder"] or ""
        if saved_folder and not Path(saved_folder).is_dir():
            saved_folder = ""
        self._monitor_folder_var = tk.StringVar(value=saved_folder)
        self._monitor_var = tk.BooleanVar(value=False)
        self._make_folder_row(
            setup_box, rows["monitor"], "Monitor folder",
            self._monitor_var, self._monitor_folder_var,
            self._on_monitor_toggle, self._browse_monitor_folder, row_w,
        )

        self._delete_var = tk.BooleanVar(value=s["delete_flac"])
        self._delete_check = ctk.CTkCheckBox(
            setup_box, text="Delete file after conversion",
            variable=self._delete_var, command=self._play_checkbox, **_ck,
        )
        self._delete_check.place(x=INNER, y=rows["delete"])

        self._move_music_folder_var = tk.StringVar(value=s.get("move_music_folder") or "")
        self._move_music_var = tk.BooleanVar(value=s.get("move_music_enabled", False))
        self._make_folder_row(
            setup_box, rows["move_music"], "Move music to",
            self._move_music_var, self._move_music_folder_var,
            self._on_move_music_toggle, self._browse_move_music_folder, row_w,
        )

        self._move_video_folder_var = tk.StringVar(value=s.get("move_video_folder") or "")
        self._move_video_var = tk.BooleanVar(value=s.get("move_video_enabled", False))
        self._make_folder_row(
            setup_box, rows["move_video"], "Move video to",
            self._move_video_var, self._move_video_folder_var,
            self._on_move_video_toggle, self._browse_move_video_folder, row_w,
        )

        # --- Torrent settings ---
        # No separate download/finished folders any more — torrents land
        # straight in the monitored folder above and convert the same way
        # anything else dropped in there would.
        self._torrent_var = tk.BooleanVar(value=s.get("torrent_enabled", False))
        self._torrent_check = ctk.CTkCheckBox(
            setup_box, text="Auto-download torrents",
            variable=self._torrent_var, command=self._on_torrent_toggle, **_ck,
        )
        self._torrent_check.place(x=INNER, y=rows["torrent"])

        # How many torrents may transfer at once; the rest wait their turn and
        # show as QUEUED. Committed on release like the volume slider, and
        # applied to a running downloader without restarting it, so raising
        # the limit starts waiting torrents immediately.
        self._max_downloads = clamp_max_active(s.get("max_active_downloads"))
        # Indented to the checkbox *text* column, not the checkbox itself —
        # this row has no checkbox of its own, and sitting flush left would
        # break the column the rest of the torrent group reads down.
        tk.Label(
            setup_box, text="Active downloads", bg=BG, fg=LIGHT,
            font=tkfont.Font(family="Silkscreen", size=-16 * SCALE), anchor="w",
        ).place(
            x=INNER + 28 * SCALE, y=rows["max_downloads"] + 4 * SCALE,
            height=24 * SCALE,
        )

        def _max_downloads_commit(value: float) -> None:
            self._max_downloads = dl_fraction_to_count(value)
            if self._torrent_downloader is not None:
                self._torrent_downloader.set_max_active(self._max_downloads)
            self._save_settings()
            self._play_checkbox()

        self._max_downloads_slider = PixelSlider(
            setup_box, on_commit=_max_downloads_commit,
            steps=DL_SLIDER_STEPS, fmt=lambda v: str(dl_fraction_to_count(v)),
        )
        self._max_downloads_slider.set(dl_count_to_fraction(self._max_downloads))
        self._max_downloads_slider.place(
            x=row_w - BAR_W - INNER, y=rows["max_downloads"] + 7 * SCALE,
        )

        self._torrent_delete_var = tk.BooleanVar(value=s.get("torrent_delete_source", False))
        self._torrent_delete_check = ctk.CTkCheckBox(
            setup_box, text="Delete torrent file after adding",
            variable=self._torrent_delete_var, command=self._play_checkbox, **_ck,
        )
        self._torrent_delete_check.place(x=INNER, y=rows["torrent_delete"])

        self._magnet_handler_var = tk.BooleanVar(value=self._is_magnet_handler_registered())
        self._magnet_handler_check = ctk.CTkCheckBox(
            setup_box, text="Open magnet links in Plunder",
            variable=self._magnet_handler_var, command=self._on_magnet_handler_toggle, **_ck,
        )
        self._magnet_handler_check.place(x=INNER, y=rows["magnet"])

        self._torrent_ext_var = tk.BooleanVar(value=self._is_torrent_ext_handler_registered())
        self._torrent_ext_check = ctk.CTkCheckBox(
            setup_box, text="Open .torrent files in Plunder",
            variable=self._torrent_ext_var, command=self._on_torrent_ext_handler_toggle, **_ck,
        )
        self._torrent_ext_check.place(x=INNER, y=rows["torrent_ext"])

        # --- SOCKS5 proxy ---
        self._proxy_host_var = tk.StringVar(value=s.get("proxy_host") or "")
        self._proxy_port_var = tk.StringVar(
            value=str(s.get("proxy_port")) if s.get("proxy_port") else ""
        )
        self._proxy_username_var = tk.StringVar(value=s.get("proxy_username") or "")
        self._proxy_password_var = tk.StringVar(value=s.get("proxy_password") or "")
        self._proxy_var = tk.BooleanVar(value=s.get("proxy_enabled", False))

        self._proxy_check = ctk.CTkCheckBox(
            setup_box, text="Enable SOCKS5 proxy",
            variable=self._proxy_var, command=self._on_proxy_toggle, **_ck,
        )
        self._proxy_check.place(x=INNER, y=rows["proxy_enabled"])
        # One shared entry column: without it each field's width would be
        # dictated by its own label, leaving Host/Port longer than
        # Username/Password.
        _entry_font = tkfont.Font(family="Silkscreen", size=-16 * SCALE)
        proxy_entry_x = INNER + max(
            _entry_font.measure(t) for t in ("Host", "Port", "Username", "Password")
        ) + 10 * SCALE
        self._make_entry_row(
            setup_box, rows["proxy_host"], "Host", self._proxy_host_var, row_w,
            entry_x=proxy_entry_x,
        )
        self._make_entry_row(
            setup_box, rows["proxy_port"], "Port", self._proxy_port_var, row_w,
            entry_x=proxy_entry_x,
        )
        self._make_entry_row(
            setup_box, rows["proxy_user"], "Username", self._proxy_username_var, row_w,
            entry_x=proxy_entry_x,
        )
        self._make_entry_row(
            setup_box, rows["proxy_pass"], "Password", self._proxy_password_var, row_w,
            show="*", entry_x=proxy_entry_x,
        )

        # --- Settings traces ---
        for var in (
            self._delete_var, self._auto_convert_var,
            self._tray_var, self._startup_var, self._sounds_var,
            self._monitor_var, self._monitor_folder_var,
            self._torrent_var, self._torrent_delete_var,
            self._move_music_var, self._move_music_folder_var,
            self._move_video_var, self._move_video_folder_var,
            self._magnet_handler_var, self._torrent_ext_var,
            self._proxy_var, self._proxy_host_var, self._proxy_port_var,
            self._proxy_username_var, self._proxy_password_var,
        ):
            var.trace_add("write", lambda *_: self._save_settings())

        # Bypasses CTkScrollableFrame's own configure() override, which
        # resizes the visible viewport instead of the scrollable content —
        # .place()'d children (everything above) don't propagate a size
        # request to their parent the way pack()/grid() children would, so
        # the content height has to be set explicitly for scrolling to work.
        tk.Frame.configure(setup_box, height=content_h)

        self.bind("<Unmap>", self._on_unmap)
        self.protocol("WM_DELETE_WINDOW", self._on_close_button)

        # Restore monitor state
        if s["monitor_folder"] and s["monitor_enabled"]:
            self._monitor_var.set(True)
            self._start_monitor(s["monitor_folder"])

        # Restore torrent downloader state — needs monitoring active, since
        # torrents now download into the monitored folder itself.
        if s.get("torrent_enabled") and self._monitor_var.get():
            self._start_torrent_downloader()

        # Start animation loop
        self.after(40, self._wave_tick)

    # ------------------------------------------------------------------
    # Scrollable, outlined progress boxes
    # ------------------------------------------------------------------
    def _position_bottom_decor(self, _event=None) -> None:
        """Pin the bottom chain run and skulls just below the encoding
        box's real bottom outline (5px clearance, like the side runs)."""
        box = getattr(self._encoding_progress_frame, "_outer_box", None)
        if box is None or not getattr(self, "_bottom_chain_label", None):
            return
        try:
            self.update_idletasks()
            box_bottom = box.winfo_rooty() - self.winfo_rooty() + box.winfo_height()
        except Exception:
            return
        if box_bottom <= 0:
            return
        line_y = box_bottom + 15 * SCALE
        chain_h = self._bottom_chain_label.winfo_reqheight()
        self._bottom_chain_label.place_configure(y=line_y - chain_h // 2)
        for lbl in getattr(self, "_bottom_skull_labels", []):
            lbl.place_configure(y=line_y - lbl.winfo_reqheight() // 2)

    @staticmethod
    def _notch_corners(
        parent, x: int, y: int, w: int, h: int, radius: int = CORNER_R,
    ) -> None:
        """Knock a pixel-art quarter circle out of each corner of a box
        outline so the hard rectangle reads as rounded at `radius`.

        One background-colored strip per row of the quarter circle, mirrored
        into all four corners.
        """
        for row, run in enumerate(_corner_steps(radius)):
            for cx in (x, x + w - run):
                for cy in (y + row, y + h - row - 1):
                    tk.Frame(parent, bg=BG, width=run, height=1).place(x=cx, y=cy)

    @staticmethod
    def _weather_outline(
        parent, x: int, y: int, w: int, h: int, seed: int,
        drops_only: bool = False, step_lo: int = 40, step_hi: int = 90,
    ) -> None:
        """Hand-worn box outline: knock out the odd pixel, nudge another.

        Deterministic per box (seeded RNG) so the wear pattern is part of
        the design rather than reshuffling every launch. A "pixel" here is
        BORDER-sized to match the chunky outline width.
        """
        rng = random.Random(seed)
        n = BORDER
        edges = (
            ("h", x + 6 * SCALE, x + w - 6 * SCALE, y),           # top
            ("h", x + 6 * SCALE, x + w - 6 * SCALE, y + h - n),   # bottom
            ("v", y + 6 * SCALE, y + h - 6 * SCALE, x),           # left
            ("v", y + 6 * SCALE, y + h - 6 * SCALE, x + w - n),   # right
        )
        for kind, a0, a1, c in edges:
            pos = a0
            while True:
                pos += rng.randint(step_lo, step_hi)
                # Each worn patch runs 2-4 chunky pixels along the edge.
                seg = rng.randint(2, 4) * n
                if pos + seg >= a1:
                    break
                if kind == "h":
                    tk.Frame(parent, bg=BG, width=seg, height=n).place(x=pos, y=c)
                    if not drops_only and rng.random() < 0.6:
                        tk.Frame(parent, bg=LIGHT, width=seg, height=n).place(
                            x=pos, y=c + n * rng.choice((1, -1)),
                        )
                else:
                    tk.Frame(parent, bg=BG, width=n, height=seg).place(x=c, y=pos)
                    if not drops_only and rng.random() < 0.6:
                        tk.Frame(parent, bg=LIGHT, width=n, height=seg).place(
                            x=c + n * rng.choice((1, -1)), y=pos,
                        )

    @staticmethod
    def _make_scroll_box(
        parent, x: int, y: int, w: int, h: int
    ) -> ctk.CTkScrollableFrame:
        """An outlined box holding a scrollable list with no visible scrollbar.

        The scrollbar is un-gridded rather than removed — customtkinter still
        drives it, and the mouse wheel still scrolls the canvas underneath.
        """
        box = tk.Frame(
            parent, bg=BG, highlightbackground=TEAL, highlightthickness=BORDER,
        )
        box.place(x=x, y=y, width=w, height=h)
        App._notch_corners(parent, x, y, w, h)
        App._weather_outline(parent, x, y, w, h, seed=x * 31 + y * 17 + w)
        inner = ctk.CTkScrollableFrame(
            box, width=w - SCROLL_INSET, height=h - SCROLL_INSET,
            fg_color=BG, corner_radius=0,
            scrollbar_fg_color=BG,
            scrollbar_button_color=BG,
            scrollbar_button_hover_color=BG,
        )
        inner.pack(fill="both", expand=True)
        inner._scrollbar.grid_forget()
        inner._outer_box = box  # for post-map decor positioning
        return inner

    def _make_folder_row(
        self, parent, y: int, name: str,
        is_var: tk.BooleanVar, path_var: tk.StringVar,
        on_toggle, on_browse, row_w: int,
    ) -> ctk.CTkCheckBox:
        """Checkbox + a clickable "<name>  <path>" label, all on one line.

        There is no separate Browse button — clicking the label opens the
        folder picker. The path is elided to fit whatever room is left after
        the name, same technique as the drop-zone status text.
        """
        check_size = 20 * SCALE
        check = ctk.CTkCheckBox(
            parent, text="", variable=is_var, command=on_toggle,
            fg_color=LIGHT, border_color=LIGHT, hover_color=LIGHT,
            checkmark_color=DARK, checkbox_width=check_size, checkbox_height=check_size,
            corner_radius=0, width=check_size,
        )
        check.place(x=INNER, y=y)

        # Negative size = pixel height, not points — matches what
        # customtkinter's own font scaling produces for its "16" checkboxes,
        # so this label reads at the same visual size as the others.
        name_font = tkfont.Font(family="Silkscreen", size=-16 * SCALE)
        path_font = tkfont.Font(family="Silkscreen", size=8 * SCALE)
        name_x = INNER + check_size + 8 * SCALE

        # Both labels are vertically centered on the checkbox's own center,
        # not just eyeballed — that's what kept the path text sitting a few
        # pixels below the name text.
        row_center = y + check_size // 2
        name_h, path_h = 24 * SCALE, 16 * SCALE

        name_lbl = tk.Label(
            parent, text=name, bg=BG, fg=LIGHT, font=name_font,
            anchor="w", cursor="hand2",
        )
        name_lbl.place(x=name_x, y=row_center - name_h // 2, height=name_h)

        path_x = name_x + name_font.measure(name) + 10 * SCALE
        max_path_px = max(row_w - path_x - INNER, 0)
        path_lbl = tk.Label(
            parent, text="", bg=BG, fg=DIM, font=path_font,
            anchor="w", cursor="hand2",
        )
        path_lbl.place(x=path_x, y=row_center - path_h // 2, width=max_path_px, height=path_h)

        def browse(_event=None) -> None:
            self._play_click()
            on_browse()

        name_lbl.bind("<Button-1>", browse)
        path_lbl.bind("<Button-1>", browse)

        def refresh(*_args) -> None:
            text = path_var.get()
            path_lbl.configure(
                text=self._elide(text, path_font, max_path_px) if text else ""
            )
        path_var.trace_add("write", refresh)
        refresh()

        return check

    def _make_entry_row(
        self, parent, y: int, label: str, var: tk.StringVar, row_w: int,
        show: Optional[str] = None, entry_x: Optional[int] = None,
    ) -> ctk.CTkEntry:
        """Label + editable text field on one line — the typed-value
        analogue of _make_folder_row, for settings that need real input
        (proxy host/port/credentials) instead of a folder picker."""
        name_font = tkfont.Font(family="Silkscreen", size=-16 * SCALE)
        name_lbl = tk.Label(
            parent, text=label, bg=BG, fg=LIGHT, font=name_font, anchor="w",
        )
        name_lbl.place(x=INNER, y=y + 4 * SCALE, height=24 * SCALE)

        if entry_x is None:
            entry_x = INNER + name_font.measure(label) + 10 * SCALE
        entry_w = max(row_w - entry_x - INNER, 60 * SCALE)
        entry = ctk.CTkEntry(
            parent, textvariable=var, show=show,
            font=("Silkscreen", 14 * SCALE), fg_color=BG, border_color=LIGHT,
            text_color=LIGHT, corner_radius=0, width=entry_w, height=28 * SCALE,
        )
        entry.place(x=entry_x, y=y)
        # Entries keep the tighter 2px round — a 4px corner is too much
        # curve on a 28px-tall field.
        self._notch_corners(parent, entry_x, y, entry_w, 28 * SCALE, radius=2 * SCALE)
        self._weather_outline(
            parent, entry_x, y, entry_w, 28 * SCALE, seed=y * 13 + 5,
            drops_only=True, step_lo=70, step_hi=140,
        )
        return entry

    # ------------------------------------------------------------------
    # Tab bar colors — keep unselected tab labels visible
    # ------------------------------------------------------------------
    def _on_tab_changed(self) -> None:
        if self._tabview.get() == "Quit":
            self.after(0, self._quit_app)
            return
        self._play_click()
        self._update_tab_colors()

    def _tab_under_pointer(self) -> Optional[str]:
        """Name of the tab button currently under the mouse, if any.

        Resolved with winfo_containing rather than pointer-vs-rootx
        arithmetic: the latter mixes coordinate spaces under DPI scaling /
        multiple monitors (measured: pointer inside a button while the
        comparison said otherwise), while winfo_containing and
        winfo_pointerx are consistent with each other by construction.
        """
        try:
            w = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
            buttons = self._tabview._segmented_button._buttons_dict
            while w is not None:
                for name, btn in buttons.items():
                    if w is btn:
                        return name
                w = getattr(w, "master", None)
        except Exception:
            pass
        return None

    def _poll_tab_hover(self) -> None:
        """Reconcile hover state against where the pointer actually is.

        Runs every 80ms. Entering a different tab plays the hover sound once
        and lights that chip; leaving the tab bar restores colors silently.

        The fill is re-asserted on EVERY tick while the pointer sits on a
        tab, not just on the transition: ctk's own Enter/Leave handlers
        repaint the button canvas whenever the pointer crosses between a
        chip's internal canvas and text label, which used to leave the chip
        unfilled with no transition for the poll to react to. Re-asserting
        is a no-op unless the color actually drifted, so it never flickers.

        winfo_containing also reports None for the odd tick while the
        pointer is still over a tab (grabs, DPI rounding); two consecutive
        misses are required before dropping the hover, so a single blip no
        longer unfills the chip and replays the sound.
        """
        try:
            if not self.winfo_exists():
                return
            # Reconcile the selection too: ctk's set() does not fire the
            # tabview's command, so a programmatic tab change would otherwise
            # leave the chips carrying the previous selection's text colors —
            # dark-on-dark and light-on-light, i.e. invisible labels.
            selected = self._tabview.get()
            if selected != getattr(self, "_painted_tab", None):
                self._painted_tab = selected
                self._update_tab_colors()

            name = self._tab_under_pointer()
            if name is None and self._hovered_tab is not None:
                self._hover_misses += 1
                if self._hover_misses < 2:
                    name = self._hovered_tab  # ignore a one-tick blip
            else:
                self._hover_misses = 0

            if name != self._hovered_tab:
                self._hovered_tab = name
                self._update_tab_colors()
                if name is not None:
                    self._play_hover()
            elif name is not None:
                self._paint_tab(name, lit=True)
        except Exception:
            pass
        self.after(80, self._poll_tab_hover)

    def _paint_tab(self, name: str, lit: bool) -> None:
        """Give one tab chip its lit (DARK on LIGHT) or unlit look.

        hover_color is set to match fg_color so ctk's own hover repaint —
        which fires on its own schedule and can land after ours — can only
        ever repaint the chip in the color it already has.
        """
        try:
            btn = self._tabview._segmented_button._buttons_dict[name]
            fg, text = (LIGHT, DARK) if lit else (DARK, LIGHT)
            if (btn.cget("fg_color"), btn.cget("hover_color"),
                    btn.cget("text_color")) != (fg, fg, text):
                btn.configure(fg_color=fg, hover_color=fg, text_color=text)
            self._round_tab_corners(btn)
        except Exception:
            pass  # private API — never let a ctk change break the app

    def _update_tab_colors(self) -> None:
        """Selected chip: DARK text on LIGHT bg; unselected: LIGHT text on DARK.

        customtkinter's segmented button only supports a single text color for
        all segments, so recolor the per-tab buttons directly. The hovered tab
        lights up the same way the selected one does.
        """
        try:
            seg = self._tabview._segmented_button
            selected = self._tabview.get()
            for name in seg._buttons_dict:
                self._paint_tab(name, lit=name in (selected, self._hovered_tab))
        except Exception:
            pass  # private API — never let a ctk change break the app

    def _round_tab_corners(self, btn) -> None:
        """Round the TOP corners of a tab chip's fill by 4px, once per chip.

        Same pixel-art quarter circle the white boxes use, knocked out in the
        tab strip's own background color — so it shapes the white fill and is
        invisible while the chip is dark. Only the top corners: the bottom of
        a chip meets the outline and stays square.
        """
        if getattr(btn, "_corner_bits", None):
            return
        # ctk draws the fill inset by the button's border width, so the
        # knockouts have to start there rather than at the widget edge.
        bw = btn.cget("border_width")
        bits = []
        for row, run in enumerate(_corner_steps(CORNER_R)):
            for relx, anchor in ((0.0, "nw"), (1.0, "ne")):
                bit = tk.Frame(
                    btn, bg=DARK, width=run, height=1,
                    borderwidth=0, highlightthickness=0,
                )
                bit.place(
                    relx=relx, x=bw if relx == 0.0 else -bw,
                    y=bw + row, anchor=anchor,
                )
                bits.append(bit)
        btn._corner_bits = bits

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

    _TORRENT_DONE_SOUNDS = (
        "torrent downloaded-001.wav",
        "torrent downloaded-002.wav",
        "torrent downloaded-003.wav",
        "torrent downloaded-004.wav",
    )

    def _preload_sounds(self, volume: Optional[float] = None) -> None:
        if volume is None:
            volume = self._settings.get("sound_volume", 100) / 100
        self._sound_paths: Dict[str, str] = {}
        if not hasattr(self, "_sound_tmp_dir"):
            self._sound_tmp_dir = tempfile.mkdtemp(prefix="hoarder_snd_")
        names = (
            "app quit.wav",
            "app_startup.wav",
            "checkbox.wav",
            "click.wav",
            "hover.wav",
            "transcoding done.wav",
            "when torrent added.wav",
            *self._TORRENT_DONE_SOUNDS,
        )
        for name in names:
            p = Path(__file__).parent / name
            if p.exists():
                try:
                    data = self._load_wav_at_volume(str(p), volume)
                    tmp = str(Path(self._sound_tmp_dir) / name)
                    with open(tmp, "wb") as f:
                        f.write(data)
                    self._sound_paths[name] = tmp
                except Exception:
                    pass

    def _play(self, filename: str) -> None:
        sounds_var = getattr(self, "_sounds_var", None)
        if sounds_var is not None and not sounds_var.get():
            return
        path = self._sound_paths.get(filename)
        if not path:
            return
        threading.Thread(
            target=winsound.PlaySound,
            args=(path, winsound.SND_FILENAME),
            daemon=True,
        ).start()

    def _play_click(self) -> None:
        self._play("click.wav")

    def _play_checkbox(self) -> None:
        self._play("checkbox.wav")

    def _play_hover(self) -> None:
        self._play("hover.wav")

    def _play_startup(self) -> None:
        self._play("app_startup.wav")

    def _play_done(self) -> None:
        self._play("transcoding done.wav")

    def _play_torrent_added(self) -> None:
        self._play("when torrent added.wav")

    def _play_torrent_downloaded(self) -> None:
        self._play(random.choice(self._TORRENT_DONE_SOUNDS))

    # ------------------------------------------------------------------
    # Drop / browse
    # ------------------------------------------------------------------
    def _on_drop(self, event) -> None:
        # Unlike every other entry point into the pipeline, this one runs
        # straight off a raw OS callback with no caller to catch a mistake —
        # in the built exe (console=False) an uncaught exception here has
        # nowhere to print to, so the drop silently does nothing at all.
        try:
            paths = expand_drops(parse_drop_paths(event.data))
            self._handle_paths(paths)
        except Exception as e:
            self._set_info(f"Drop failed: {e}", WARM)

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
        # Torrent files dropped on the drop zone go straight to the downloader
        torrents, paths = split_torrent_paths(paths)
        if torrents:
            self._add_dropped_torrents(torrents)
            if not paths:
                return

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

    def _add_dropped_torrents(self, torrents: List[str]) -> None:
        """Send dropped .torrent/.magnet files to the torrent downloader."""
        if self._torrent_downloader is None:
            if self._monitor_folder_var.get() and self._monitor_var.get():
                self._torrent_var.set(True)
                self._start_torrent_downloader()
            else:
                self._set_info("Enable Monitor folder in Setup first", WARM)
                return
        if self._torrent_downloader is None:
            return
        added = 0
        for t in torrents:
            if self._torrent_downloader.add(t) is not None:
                added += 1
        if added:
            plural = "s" if added != 1 else ""
            self._set_info(f"Added {added} torrent{plural}", SAGE)
        else:
            self._set_info("Could not add torrent", WARM)

    def _load_files(self, paths: List[str]) -> None:
        mode, flacs, cue, videos, error = detect_mode(paths)
        if error:
            self._set_info(error, WARM)
            self._flac_paths = []
            self._cue_path = None
            self._mode = None
            self._video_paths = []
            return

        self._flac_paths = flacs
        self._cue_path = cue
        self._mode = mode
        self._video_paths = videos

        # A direct drop/browse (0 or 1 CUE) reaches _start_conversion without
        # ever going through _enqueue_conversion, so nothing has put rows in
        # the encoding box yet — without this, conversion runs entirely
        # invisibly until the final "Done" sound.
        for f in flacs:
            self._add_encoding_progress(f, Path(f).name)
        for v in videos:
            self._add_encoding_progress(v, Path(v).name)

        self._set_info("Files loaded", SAGE)
        self._start_conversion()

    # ------------------------------------------------------------------
    # Status / settings
    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str = TEXT) -> None:
        """Show a transient status message in the drop zone."""
        self._set_info(text, color)

    def _save_settings(self) -> None:
        smod.save({
            "delete_flac": self._delete_var.get(),
            "auto_convert": self._auto_convert_var.get(),
            "minimize_to_tray": self._tray_var.get(),
            "start_on_startup": self._startup_var.get(),
            "monitor_enabled": self._monitor_var.get(),
            "monitor_folder": self._monitor_folder_var.get() or None,
            "torrent_enabled": self._torrent_var.get(),
            "torrent_delete_source": self._torrent_delete_var.get(),
            "max_active_downloads": self._max_downloads,
            "move_music_enabled": self._move_music_var.get(),
            "move_music_folder": self._move_music_folder_var.get() or None,
            "move_video_enabled": self._move_video_var.get(),
            "move_video_folder": self._move_video_folder_var.get() or None,
            "sounds_enabled": self._sounds_var.get(),
            "sound_volume": self._sound_volume,
            "proxy_enabled": self._proxy_var.get(),
            "proxy_host": self._proxy_host_var.get().strip() or None,
            "proxy_port": self._parse_port(self._proxy_port_var.get()),
            "proxy_username": self._proxy_username_var.get().strip() or None,
            "proxy_password": self._proxy_password_var.get() or None,
            "torrent_ext_association_asked": self._torrent_ext_asked,
        })

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------
    def _start_conversion(self) -> None:
        if self._is_converting:
            return
        if not check_ffmpeg():
            self._is_converting = True  # block re-entry while fetching
            self._set_status("Downloading ffmpeg (one-time setup)…", WARM)
            thread = threading.Thread(target=self._fetch_ffmpeg_then_convert, daemon=True)
            thread.start()
            return

        self._is_converting = True
        thread = threading.Thread(target=self._run_conversion, daemon=True)
        thread.start()

    def _fetch_ffmpeg_then_convert(self) -> None:
        """Download ffmpeg/ffprobe (see ffmpeg_fetch.py), then run the queued
        conversion that triggered the download in the first place."""
        from ffmpeg_fetch import download as fetch_ffmpeg

        def on_progress(frac: float) -> None:
            self.after(0, self._set_status, f"Downloading ffmpeg… {int(frac * 100)}%", WARM)

        try:
            fetch_ffmpeg(on_progress=on_progress)
        except Exception as e:
            self.after(0, self._set_status, f"Could not download ffmpeg: {e}", WARM)
            self.after(0, self._on_ffmpeg_fetch_failed)
            return
        self.after(0, self._on_ffmpeg_fetch_done)

    def _on_ffmpeg_fetch_failed(self) -> None:
        self._is_converting = False

    def _on_ffmpeg_fetch_done(self) -> None:
        thread = threading.Thread(target=self._run_conversion, daemon=True)
        thread.start()

    def _run_conversion(self) -> None:
        # Capture all mutable state now to avoid races with _load_files
        flacs     = self._flac_paths[:]
        cue       = self._cue_path
        mode      = self._mode
        videos    = self._video_paths[:]
        do_delete = self._delete_var.get()
        # Rows for this batch already exist — _enqueue_conversion added them
        # when it was queued, not now. Keep the ids around so this batch's
        # rows (and only this batch's) can be cleared once it's done,
        # leaving any other queued batches' rows on screen untouched.
        task_ids = flacs + videos

        def on_audio_progress(cur: int, total: int) -> None:
            if flacs and 0 <= cur - 1 < len(flacs):
                self.after(0, self._update_encoding_progress, flacs[cur - 1], 1.0)

        _last_video_idx = [-1]

        def on_video_progress(cur: float, total: int) -> None:
            idx = min(int(cur), total - 1)
            if idx != _last_video_idx[0] and 0 <= idx < len(videos):
                _last_video_idx[0] = idx
            if 0 <= idx < len(videos):
                frac = cur - int(cur) if cur > 0 else 0.0
                self.after(0, self._update_encoding_progress, videos[idx], min(frac, 1.0))

        try:
            # --- Audio ---
            audio_outputs: List[str] = []
            if flacs:
                if cue:
                    tracks = parse_cue(cue)
                    split_and_convert(flacs[0], tracks, on_audio_progress)
                else:
                    convert_files(flacs, on_audio_progress)
                # Compute output paths before deleting the CUE file below —
                # a CUE-mode split needs to re-parse it to name the tracks,
                # and delete_companion_files() removes that same file.
                audio_outputs = self._audio_outputs(flacs, cue)
                if do_delete:
                    delete_flacs(flacs)
                    delete_companion_files(flacs, cue)

            # --- Video ---
            unreadable_videos: List[str] = []

            def on_unreadable(path: str, error: str) -> None:
                unreadable_videos.append(path)
                self.after(0, self._set_info,
                           f"Skipped {Path(path).name} (unreadable — corrupt or incomplete download)",
                           WARM)

            if videos:
                # Claim the outputs before ffmpeg writes them, so the folder
                # monitor does not treat them as newly arrived source files.
                for v in videos:
                    self._ignore_output(str(video_output_path(Path(v))))
                transcode_videos(videos, on_video_progress, delete_source=do_delete,
                                  on_unreadable=on_unreadable)

            # Files ffprobe couldn't even read are left out of the library
            # mark below — that's what lets them keep showing up (and being
            # reported) on future scans instead of silently passing as done.
            videos = [v for v in videos if v not in unreadable_videos]
            video_outputs = self._video_outputs(videos)

            # Move converted files out of the monitored folder, per type.
            audio_moved = False
            if self._move_music_var.get():
                dest = self._move_music_folder_var.get()
                if dest and Path(dest).is_dir():
                    audio_outputs, warn = self._move_outputs(audio_outputs, dest)
                    audio_moved = True
                    if warn:
                        self.after(0, self._set_info, warn, WARM)
            video_moved = False
            if self._move_video_var.get():
                dest = self._move_video_folder_var.get()
                if dest and Path(dest).is_dir():
                    video_outputs, warn = self._move_outputs(video_outputs, dest)
                    video_moved = True
                    if warn:
                        self.after(0, self._set_info, warn, WARM)

            # Flag the finished work with " Done" so it reads as complete at
            # a glance, before marking it in the library — mark() needs the
            # paths it is given to still exist.
            audio_outputs = self._flag_encoded_done(
                Path(flacs[0]).parent if flacs else None,
                audio_outputs, audio_moved,
            )
            video_outputs = self._flag_encoded_done(
                Path(videos[0]).parent if videos else None,
                video_outputs, video_moved, is_video=True,
            )

            # Record the work so a restart does not repeat it. Outputs are
            # recorded as well as sources: a finished transcode left in the
            # monitored folder looks exactly like a new source video to the
            # startup scan.
            libmod.mark([
                p for p in [*flacs, cue, *videos, *audio_outputs, *video_outputs]
                if p
            ])

            # Done
            self.after(0, self._play_done)
            self.after(0, self._show_done)
            self.after(3000, self._remove_encoding_rows, task_ids)
            if do_delete:
                self.after(3000, self._reset_ui)

        except ValueError as e:
            self.after(0, self._set_info, f"Could not parse CUE file: {e}", WARM)
            self.after(0, self._remove_encoding_rows, task_ids)
        except RuntimeError as e:
            self.after(0, self._set_info, str(e), WARM)
            self.after(0, self._remove_encoding_rows, task_ids)
        except Exception as e:
            self.after(0, self._set_info, f"Unexpected error: {e}", WARM)
            self.after(0, self._remove_encoding_rows, task_ids)
        finally:
            self._is_converting = False
            self._active_batch = None
            self.after(0, self._save_session)
            self.after(0, self._process_next_queue_item)

    def _flag_encoded_done(
        self,
        source_dir: Optional[Path],
        outputs: List[str],
        moved: bool,
        is_video: bool = False,
    ) -> List[str]:
        """Append " Done" to finished output(s) so they read as complete at
        a glance.

        Renames the shared source folder once, covering every output inside
        it in one go — but only when the whole batch lived in a dedicated
        subfolder (an album or a movie's own folder) that outputs weren't
        just relocated out of; the monitored folder's own root and a
        move-to destination are both shared by unrelated batches, so
        neither has a single folder that belongs only to this one. In
        those cases each output file is flagged individually instead. A
        directory rename never reaches the folder watcher (it ignores
        directory move events outright); a file rename does, so a renamed
        video — still a video by extension — is registered as this app's
        own output first, same as the original write was.
        """
        if not outputs:
            return outputs
        monitor_root = self._monitor_folder_var.get()
        monitor_root_path = Path(monitor_root) if monitor_root else None
        if (
            not moved
            and source_dir is not None
            and source_dir != monitor_root_path
            and not source_dir.name.endswith(" Done")
        ):
            try:
                renamed_dir = source_dir.rename(
                    source_dir.with_name(source_dir.name + " Done")
                )
            except OSError:
                pass
            else:
                return [
                    str(renamed_dir / Path(p).relative_to(source_dir))
                    for p in outputs
                ]
        result = []
        for p in outputs:
            path = Path(p)
            if path.stem.endswith(" Done"):
                result.append(p)
                continue
            new_path = path.with_name(f"{path.stem} Done{path.suffix}")
            if is_video:
                self._ignore_output(str(new_path))
            try:
                path.rename(new_path)
            except OSError:
                result.append(p)
                continue
            result.append(str(new_path))
        return result

    @staticmethod
    def _audio_outputs(flacs: List[str], cue: Optional[str]) -> List[str]:
        """MP3 paths this conversion writes: split tracks, or one per source file."""
        outputs: List[str] = []
        if flacs:
            if cue:
                for track in parse_cue(cue):
                    outputs.append(str(
                        Path(flacs[0]).parent
                        / f"{track.number:02d} - {track.title}.mp3"
                    ))
            else:
                for f in flacs:
                    outputs.append(str(Path(f).parent / (Path(f).stem + ".mp3")))
        return outputs

    @staticmethod
    def _video_outputs(videos: List[str]) -> List[str]:
        return [str(video_output_path(Path(v))) for v in videos]

    @staticmethod
    def _conversion_outputs(
        flacs: List[str], cue: Optional[str], videos: List[str]
    ) -> List[str]:
        """Paths this conversion writes: split tracks or MP3s, plus transcodes."""
        return App._audio_outputs(flacs, cue) + App._video_outputs(videos)

    def _move_outputs(
        self, paths: List[str], dest: str
    ) -> Tuple[List[str], Optional[str]]:
        """Move converted files to *dest*, registering the destinations first.

        Registration happens before the move so the folder monitor — if
        *dest* sits inside the monitored tree — never treats the arrival as a
        new source file.
        """
        for p in paths:
            self._ignore_output(str(Path(dest) / Path(p).name))
        from converter import move_to_folder
        return move_to_folder(paths, dest)

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
        self._reset_drop_text()

    def _draw_wave_drop(self) -> None:
        """Redraw the drop-zone canvas with the waving status/prompt text."""
        c = self._drop_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 2 or h < 2:
            return  # canvas not yet realized
        font = self._drop_font
        text = self._elide(self._drop_text, font, w - 16 * SCALE)
        total_w = sum(font.measure(ch) for ch in text)
        x = (w - total_w) / 2
        cy = h / 2
        for i, ch in enumerate(text):
            cw = font.measure(ch)
            y = cy + 4 * SCALE * math.sin(self._wave_phase + i * 0.6)
            c.create_text(x + cw / 2, y, text=ch, font=font,
                          fill=self._drop_color, anchor="center")
            x += cw

    def _wave_tick(self) -> None:
        """Periodic animation tick — runs every 40 ms for the lifetime of the app."""
        self._wave_phase += 0.25
        self._draw_wave_drop()
        self.after(40, self._wave_tick)

    def _set_info(self, text: str, color: str = DIM, hold_ms: int = 4000) -> None:
        """Show *text* in the drop zone, reverting to the prompt after a pause.

        The drop zone is the only status surface left on the main page, so
        every message — errors included — lands here.
        """
        if self._drop_revert_id is not None:
            self.after_cancel(self._drop_revert_id)
            self._drop_revert_id = None
        self._drop_text = text
        self._drop_color = color
        self._drop_font = self._fit_drop_font(text)
        if text != "Drag & Drop":
            self._drop_revert_id = self.after(hold_ms, self._reset_drop_text)

    def _fit_drop_font(self, text: str) -> tkfont.Font:
        """Largest wave font in which *text* fits the drop zone on one line."""
        max_px = max(self._drop_canvas.winfo_width() - 16 * SCALE, 100 * SCALE)
        for font in self._wave_fonts:
            if font.measure(text) <= max_px:
                return font
        return self._wave_fonts[-1]

    def _reset_drop_text(self) -> None:
        self._drop_revert_id = None
        self._drop_text = "Drag & Drop"
        self._drop_color = DIM
        self._drop_font = self._wave_font_drop

    def _show_done(self) -> None:
        """Called on successful conversion completion."""
        self._set_info("Done.", GREEN)

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------
    def _on_tray_toggle(self) -> None:
        self._play_checkbox()
        """If tray is unchecked while window is hidden, restore immediately."""
        if not self._tray_var.get() and self._tray_icon is not None:
            self._restore_from_tray()

    def _on_unmap(self, event) -> None:
        """Called when window is minimized (or hidden). Route to tray if enabled."""
        if event.widget is not self:
            return
        if not self._tray_var.get():
            return
        self._hide_to_tray()

    def _on_close_button(self) -> None:
        """Handle the window's X button: honor "Minimize to tray" instead of
        always quitting outright, matching the taskbar-minimize behavior.
        The new Quit tab is the explicit, always-available way to fully exit."""
        if self._tray_var.get():
            self._hide_to_tray()
        else:
            self._quit_app()

    def _quit_app(self) -> None:
        """Quit, playing the quit sound first if sounds are on.

        The window hides immediately so quitting still feels instant; the
        process just lingers invisibly for the sound's duration, since
        destroy() would kill the process before an async PlaySound gets a
        chance to be heard.
        """
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        self.withdraw()
        sounds_var = getattr(self, "_sounds_var", None)
        path = self._sound_paths.get("app quit.wav")
        if path and (sounds_var is None or sounds_var.get()):
            def _play_then_exit() -> None:
                try:
                    winsound.PlaySound(path, winsound.SND_FILENAME)
                finally:
                    self.after(0, self.destroy)
            threading.Thread(target=_play_then_exit, daemon=True).start()
        else:
            self.destroy()

    def _hide_to_tray(self) -> None:
        """Hide the window and start the tray icon, unless already hidden."""
        if self._hiding_to_tray:
            return
        self._hiding_to_tray = True
        try:
            self._tray_icon = self._build_tray_icon()
            self.withdraw()
            self._tray_icon.run_detached()
        except Exception as e:
            self._tray_var.set(False)
            self._set_status(f"Tray error: {e}")
        finally:
            self._hiding_to_tray = False

    def _go_to_tray(self) -> None:
        """Hide window and start tray icon immediately (used for --tray launch)."""
        self._tray_icon = self._build_tray_icon()
        try:
            self._tray_icon.run_detached()
        except Exception as e:
            self._tray_var.set(False)
            self._set_status(f"Tray error: {e}")

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
        return pystray.Icon("Plunder", img, "Plunder", menu)

    def _tray_open(self, icon=None, item=None) -> None:
        self.after(0, self._restore_from_tray)

    def _tray_quit(self, icon=None, item=None) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.after(0, self._quit_app)

    def _restore_from_tray(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.deiconify()
        self.lift()
        self.focus_force()

    # ------------------------------------------------------------------
    # Windows startup registration
    # ------------------------------------------------------------------
    # A value under HKCU's Run key, not a .lnk in the Startup folder.
    # Creating or reading a shortcut means COM, which meant shelling out to
    # powershell.exe — and Windows refusing that spawn (Defender blocking an
    # unsigned exe from launching PowerShell is enough on its own) raised
    # PermissionError out of a cosmetic startup check and killed the app
    # before its window ever appeared. The registry needs no subprocess at
    # all, and it is how every other Windows integration here already works.
    #
    # It also removes the behaviour itself: an unsigned executable that
    # launches PowerShell at startup is a textbook malware signature, and
    # this app has enough trouble with antivirus heuristics already.
    _STARTUP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _STARTUP_VALUE = "Plunder"
    _LEGACY_STARTUP_VALUE = "Hoarder"        # pre-rename value name
    _LEGACY_LNK_NAMES = ("Plunder.lnk", "Hoarder.lnk")

    def _on_startup_toggle(self) -> None:
        self._play_checkbox()
        try:
            if self._startup_var.get():
                self._enable_startup()
                self._set_status("Windows Startup On")
            else:
                self._disable_startup()
                self._set_status("Windows Startup Off")
        except Exception as e:
            self._set_status(f"Windows Startup error: {e}")
            self._startup_var.set(not self._startup_var.get())  # revert

    @staticmethod
    def _startup_folder() -> Path:
        """The Startup folder — only needed now to clear out old shortcuts."""
        import os
        return (
            Path(os.environ["APPDATA"])
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )

    @staticmethod
    def _startup_target() -> Path:
        # Frozen: the exe itself. Otherwise the dev-only silent launcher.
        if getattr(sys, "frozen", False):
            return Path(sys.executable)
        return Path(__file__).parent / "run.vbs"

    @classmethod
    def _startup_command(cls) -> str:
        """The command line Windows should run at logon."""
        target = cls._startup_target().resolve()
        if getattr(sys, "frozen", False):
            return f'"{target}" --tray'
        # Values under Run are handed to CreateProcess, which cannot start a
        # .vbs the way a shortcut's file association could — name the script
        # host explicitly.
        return f'wscript.exe "{target}" --tray'

    def _enable_startup(self) -> None:
        """Register this build to start with Windows, minimized to tray."""
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._STARTUP_RUN_KEY) as key:
            winreg.SetValueEx(
                key, self._STARTUP_VALUE, 0, winreg.REG_SZ, self._startup_command()
            )
        self._clear_legacy_startup()

    def _disable_startup(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._STARTUP_RUN_KEY,
                0, winreg.KEY_ALL_ACCESS,
            ) as key:
                winreg.DeleteValue(key, self._STARTUP_VALUE)
        except FileNotFoundError:
            pass  # already absent, which is the state being asked for
        self._clear_legacy_startup()

    def _clear_legacy_startup(self) -> None:
        """Drop autostart left behind by earlier builds.

        Both the Startup-folder shortcut the PowerShell version wrote and the
        pre-rename Run value. Without this, switching the setting off would
        leave the app still starting itself at logon by the old route.
        """
        for name in self._LEGACY_LNK_NAMES:
            try:
                (self._startup_folder() / name).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._STARTUP_RUN_KEY,
                0, winreg.KEY_ALL_ACCESS,
            ) as key:
                winreg.DeleteValue(key, self._LEGACY_STARTUP_VALUE)
        except OSError:
            pass

    def _registered_startup_command(self) -> Optional[str]:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._STARTUP_RUN_KEY
            ) as key:
                val, _ = winreg.QueryValueEx(key, self._STARTUP_VALUE)
                return val
        except OSError:
            return None

    def _check_stale_startup_entry(self) -> None:
        """Re-point the logon entry at this build if it no longer matches.

        Same reasoning as _check_stale_handlers: the command is a snapshot of
        sys.executable from whenever the box was ticked, so rebuilding or
        moving the exe leaves Windows launching something that is not there.
        """
        if not self._startup_var.get():
            return
        if self._registered_startup_command() == self._startup_command():
            self._clear_legacy_startup()
            return
        self._enable_startup()

    # ------------------------------------------------------------------
    # Folder monitor
    # ------------------------------------------------------------------
    def _on_monitor_toggle(self) -> None:
        self._play_checkbox()
        folder = self._monitor_folder_var.get()
        if self._monitor_var.get():
            if not folder:
                self._set_status("Select a folder")
                self._monitor_var.set(False)
                return
            self._start_monitor(folder)
        else:
            self._stop_monitor()
            self._monitor_folder_var.set("")

    def _browse_monitor_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder to monitor")
        if not folder:
            return
        self._monitor_folder_var.set(folder)
        if self._monitor_var.get():
            self._stop_monitor()
            self._start_monitor(folder)

    def _on_torrent_toggle(self) -> None:
        self._play_checkbox()
        if self._torrent_var.get():
            self._start_torrent_downloader()
        else:
            self._stop_torrent_downloader()

    # ------------------------------------------------------------------
    # Move music / video to — post-conversion relocation
    # ------------------------------------------------------------------
    def _browse_move_music_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder for converted music")
        if folder:
            self._move_music_folder_var.set(folder)

    def _browse_move_video_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder for converted video")
        if folder:
            self._move_video_folder_var.set(folder)

    def _on_move_music_toggle(self) -> None:
        self._play_checkbox()
        if self._move_music_var.get() and not self._move_music_folder_var.get():
            self._set_status("Select a folder")
            self._move_music_var.set(False)

    def _on_move_video_toggle(self) -> None:
        self._play_checkbox()
        if self._move_video_var.get() and not self._move_video_folder_var.get():
            self._set_status("Select a folder")
            self._move_video_var.set(False)

    # ------------------------------------------------------------------
    # SOCKS5 proxy
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_port(text: str) -> Optional[int]:
        try:
            port = int(text.strip())
        except (ValueError, AttributeError):
            return None
        return port if 1 <= port <= 65535 else None

    def _on_proxy_toggle(self) -> None:
        self._play_checkbox()
        if self._proxy_var.get():
            host = self._proxy_host_var.get().strip()
            port = self._parse_port(self._proxy_port_var.get())
            if not host or port is None:
                self._set_status("Enter a valid proxy host and port")
                self._proxy_var.set(False)
                return
            self._check_proxy_reachability_async(host, port)
        if self._torrent_var.get() and self._torrent_downloader is not None:
            self._start_torrent_downloader()  # rebuild with the new proxy config

    def _check_proxy_reachability_async(self, host: str, port: int) -> None:
        def _check():
            from torrent_downloader import check_proxy_reachable
            ok = check_proxy_reachable(host, port)
            self.after(0, self._on_proxy_check_result, ok, host, port)
        threading.Thread(target=_check, daemon=True).start()

    def _on_proxy_check_result(self, ok: bool, host: str, port: int) -> None:
        if ok:
            self._set_status(f"Proxy reachable ({host}:{port})", SAGE)
        else:
            self._set_status(f"Proxy unreachable ({host}:{port})", WARM)

    # ------------------------------------------------------------------
    # Magnet protocol handler (Windows registry)
    # ------------------------------------------------------------------
    def _on_magnet_handler_toggle(self) -> None:
        self._play_checkbox()
        try:
            if self._magnet_handler_var.get():
                self._register_magnet_handler()
            else:
                self._unregister_magnet_handler()
        except OSError as e:
            self._set_status(f"Magnet handler error: {e}")
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
            winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, "Plunder")
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
        except OSError:
            # Runs during _build_ui — a permissions error here must not take
            # the whole app down before the window appears.
            return False

    # ------------------------------------------------------------------
    # Stale handler repair
    # ------------------------------------------------------------------
    _MAGNET_CMD_KEY = r"Software\Classes\magnet\shell\open\command"

    @staticmethod
    def _registered_command(subkey: str) -> Optional[str]:
        """Read the (default) command string of a shell\\open\\command key."""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "")
                return val
        except OSError:
            return None

    @staticmethod
    def _command_target(cmd: Optional[str]) -> Optional[Path]:
        """The executable a registered shell command launches."""
        if not cmd:
            return None
        cmd = cmd.strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            return Path(cmd[1:end]) if end > 1 else None
        head = cmd.split(" ", 1)[0]
        return Path(head) if head else None

    def _check_stale_handlers(self) -> None:
        """Re-point the magnet:/.torrent registrations at this build.

        The registered command is a snapshot of sys.executable taken when the
        checkbox was ticked, and nothing rewrites it afterwards. Rebuilding or
        installing the app somewhere else therefore leaves Windows launching an
        exe that no longer exists: Chrome fires the handler, nothing happens,
        and the checkbox still reads as enabled because it is driven by the
        URLAssociations key rather than by the command itself.

        A dev run must not steal a working installed registration, so the
        rewrite only happens when the recorded target is gone, or when this is
        the frozen build (the installed exe is the one the user launches from
        the browser).
        """
        for registered, cmd_key, current_cmd, reregister in (
            (
                self._is_magnet_handler_registered(),
                self._MAGNET_CMD_KEY,
                self._magnet_handler_exe_cmd(),
                self._register_magnet_handler,
            ),
            (
                self._is_torrent_ext_handler_registered(),
                rf"Software\Classes\{self._TORRENT_PROGID}\shell\open\command",
                self._torrent_ext_handler_exe_cmd(),
                self._register_torrent_ext_handler,
            ),
        ):
            if not registered:
                continue
            recorded = self._registered_command(cmd_key)
            if recorded == current_cmd:
                continue
            target = self._command_target(recorded)
            if target is not None and target.exists() and not getattr(sys, "frozen", False):
                continue
            try:
                reregister()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # .torrent file association
    # ------------------------------------------------------------------
    _TORRENT_PROGID = "Hoarder.torrentfile"

    @staticmethod
    def _torrent_ext_handler_exe_cmd() -> str:
        """Return the command string for opening a .torrent file."""
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable)
            return f'"{exe}" "%1"'
        exe = Path(sys.executable)
        script = Path(__file__).parent / "main.py"
        return f'"{exe}" "{script}" "%1"'

    def _register_torrent_ext_handler(self) -> None:
        """Make Hoarder the default handler for .torrent files (current user)."""
        cmd = self._torrent_ext_handler_exe_cmd()
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{self._TORRENT_PROGID}",
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Torrent File")
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{self._TORRENT_PROGID}\shell\open\command",
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, cmd)
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent",
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, self._TORRENT_PROGID)

    def _unregister_torrent_ext_handler(self) -> None:
        """Remove Hoarder as the .torrent file handler."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent",
                0, winreg.KEY_ALL_ACCESS,
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val == self._TORRENT_PROGID:
                    winreg.DeleteValue(key, "")
        except FileNotFoundError:
            pass
        except OSError:
            pass
        for subkey in [
            rf"Software\Classes\{self._TORRENT_PROGID}\shell\open\command",
            rf"Software\Classes\{self._TORRENT_PROGID}\shell\open",
            rf"Software\Classes\{self._TORRENT_PROGID}\shell",
            rf"Software\Classes\{self._TORRENT_PROGID}",
        ]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @classmethod
    def _is_torrent_ext_handler_registered(cls) -> bool:
        """Check if Hoarder is currently the default .torrent handler."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                return val == cls._TORRENT_PROGID
        except OSError:
            return False

    def _on_torrent_ext_handler_toggle(self) -> None:
        self._play_checkbox()
        try:
            if self._torrent_ext_var.get():
                self._register_torrent_ext_handler()
            else:
                self._unregister_torrent_ext_handler()
        except OSError as e:
            self._set_status(f"Association error: {e}")
            self._torrent_ext_var.set(not self._torrent_ext_var.get())
        self._torrent_ext_asked = True
        self._save_settings()

    def _maybe_prompt_torrent_association(self) -> None:
        """Ask once, on first startup, to associate .torrent files with
        Hoarder — unless already asked, or already associated."""
        if self._torrent_ext_asked or self._is_torrent_ext_handler_registered():
            return
        self._show_torrent_association_prompt()

    def _show_torrent_association_prompt(self) -> None:
        """A small popup locked to a fixed spot inside the app window: it
        has no title bar to drag by, follows the window if it's moved, and
        only ever closes via its own Yes/No buttons."""
        popup = tk.Toplevel(self, bg=LIGHT, highlightbackground=DARK, highlightthickness=BORDER)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.transient(self)

        def _reposition(_event=None) -> None:
            popup.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width() - popup.winfo_reqwidth()) // 2
            y = self.winfo_rooty() + (self.winfo_height() - popup.winfo_reqheight()) // 2
            popup.geometry(f"+{x}+{y}")

        follow_id = self.bind("<Configure>", _reposition, add="+")

        def _answer(associate: bool) -> None:
            self.unbind("<Configure>", follow_id)
            self._torrent_ext_asked = True
            if associate:
                try:
                    self._register_torrent_ext_handler()
                    self._torrent_ext_var.set(True)
                except OSError as e:
                    self._set_status(f"Association error: {e}")
            self._save_settings()
            popup.grab_release()
            popup.destroy()

        pad = 12 * SCALE
        tk.Label(
            popup, text="Open .torrent files with Plunder?",
            bg=LIGHT, fg=DARK, font=("Silkscreen", 12 * SCALE),
            justify="left", wraplength=220 * SCALE,
        ).pack(padx=pad, pady=(pad, 6 * SCALE))

        btn_row = tk.Frame(popup, bg=LIGHT)
        btn_row.pack(padx=pad, pady=(0, pad), fill="x")
        for text, associate in (("Yes", True), ("No", False)):
            tk.Button(
                btn_row, text=text, bg=DARK, fg=LIGHT,
                activebackground=DARK, activeforeground=LIGHT,
                font=("Silkscreen", 11 * SCALE), relief="flat",
                borderwidth=0, padx=10 * SCALE, pady=4 * SCALE,
                command=lambda a=associate: _answer(a),
            ).pack(side="left", expand=True, padx=4 * SCALE)

        _reposition()
        # Modal grab: must happen after the popup is actually mapped/shown
        # with real content and geometry — grabbing an unviewable window is
        # unreliable and can leave it never actually appearing on screen.
        popup.deiconify()
        popup.lift()
        popup.focus_force()
        popup.grab_set()

    def _handle_magnet_link(self, magnet_uri: str) -> None:
        """Handle a magnet URI passed via command line or browser."""
        if not self._torrent_var.get():
            self._torrent_var.set(True)
            self._start_torrent_downloader()
        if self._torrent_downloader:
            self._torrent_downloader.add(magnet_uri)
            self._set_status("Added magnet link")
        else:
            # The downloader needs a running folder monitor to stage into, so
            # a magnet handed over by the browser can arrive with nowhere to
            # go. Say so plainly instead of dropping it in silence.
            self._set_status("Magnet dropped — enable Monitor folder", WARM)

    def _start_torrent_downloader(self) -> None:
        """Start downloading torrents into a staging area inside the monitored
        folder, invisible to the folder watcher.

        BitTorrent doesn't write pieces in order, so a file's on-disk size
        can plateau mid-download or jump to near-final early — the watcher's
        generic "size stopped changing" heuristic can't tell that apart from
        "actually done." Staging sidesteps the guesswork entirely: nothing
        moves into the real monitored folder (where the watcher looks) until
        the download is protocol-confirmed complete. That means monitoring
        must actually be running, not just configured; otherwise a finished
        download would have nowhere to be picked up from.
        """
        self._stop_torrent_downloader()
        dl = self._monitor_folder_var.get()
        if not (dl and self._monitor_var.get()):
            self._set_status("Enable Monitor folder first")
            self._torrent_var.set(False)
            return

        proxy = None
        if self._proxy_var.get():
            host = self._proxy_host_var.get().strip()
            port = self._parse_port(self._proxy_port_var.get())
            if host and port is not None:
                proxy = {
                    "host": host, "port": port,
                    "username": self._proxy_username_var.get().strip() or None,
                    "password": self._proxy_password_var.get() or None,
                }

        staging = Path(dl) / STAGING_DIRNAME
        staging.mkdir(parents=True, exist_ok=True)
        self._torrent_downloader = TorrentDownloader(
            str(staging),
            on_progress=self._on_torrent_progress,
            on_complete=self._on_torrent_complete,
            proxy=proxy,
            max_active=self._max_downloads,
        )
        self._torrent_downloader.start()

    # ------------------------------------------------------------------
    # Unfinished work across restarts
    # ------------------------------------------------------------------
    def _encode_snapshot(self) -> List[dict]:
        """Conversion batches not yet finished — the one in flight, then the
        queue behind it, in the order they would run."""
        batches = ([self._active_batch] if self._active_batch else [])
        batches += [list(b) for b in self._conversion_queue]
        return [{"paths": list(b)} for b in batches if b]

    def _save_session(self) -> None:
        """Write down what is still in flight, so a restart can pick it up."""
        downloads = (
            self._torrent_downloader.snapshot()
            if self._torrent_downloader is not None else []
        )
        # Records the last restore could not act on — the downloader was off,
        # or the staged .torrent had gone — are carried forward rather than
        # dropped. Writing only the live snapshot would erase the record of a
        # part-finished download the moment the app started without torrents
        # enabled, and its partial data in staging would be orphaned for good.
        downloads += self._unresumed_downloads
        sess.save(downloads, self._encode_snapshot())

    def _restore_session(self) -> None:
        """Resume the downloads and re-run the conversions the last run left.

        Downloads genuinely resume: aria2c picks up from the partial data and
        its control file still sitting in staging. Encodes cannot — ffmpeg has
        no way back into a half-written file — so an interrupted batch is run
        again from the start, after its partial output is cleared away.
        """
        state = sess.load()
        resumed = self._resume_downloads(state["downloads"])
        requeued = self._resume_encodes(state["encodes"])
        self._save_session()
        self._sweep_staged_torrents()
        if resumed or requeued:
            parts = []
            if resumed:
                parts.append(f"{resumed} download{'s' if resumed != 1 else ''}")
            if requeued:
                parts.append(f"{requeued} encode{'s' if requeued != 1 else ''}")
            self._set_info(f"Resumed {' and '.join(parts)}", SAGE)

    def _sweep_staged_torrents(self) -> None:
        """Drop the staged .torrent copies nothing unfinished refers to.

        Run right after a restore, when the session file has just been
        rewritten and therefore names every transfer still worth keeping.
        """
        live = [r.get("target", "") for r in sess.load()["downloads"]]
        if self._torrent_downloader is not None:
            live += [r.get("target", "") for r in self._torrent_downloader.snapshot()]
        sweep_stale_staged_torrents(live)

    def _resume_downloads(self, records: List[dict]) -> int:
        """Hand every still-usable record back to the downloader.

        Anything not restarted here is kept in _unresumed_downloads instead of
        being forgotten, so _save_session writes it out again and both the
        record and the partial data in staging survive to the next launch.
        """
        self._unresumed_downloads = []
        if not records:
            return 0
        if self._torrent_downloader is None:
            # Nowhere to put them, but the record is worth keeping: enable the
            # monitor and downloader later and the next launch resumes them.
            self._unresumed_downloads = [dict(r) for r in records]
            return 0
        resumed = 0
        for rec in records:
            target = rec.get("target") or ""
            # A magnet URI is always usable; a staged .torrent copy may have
            # been swept out of %TEMP% since, in which case the transfer
            # cannot be restarted from here.
            if not target.startswith("magnet:?") and not Path(target).is_file():
                continue
            # resume=True: the partial data is already in staging, so aria2c
            # is told to hash-check and continue rather than trust a control
            # file that may be stale or missing entirely.
            if self._torrent_downloader.add(target, resume=True) is not None:
                resumed += 1
        return resumed

    def _resume_encodes(self, records: List[dict]) -> int:
        """Re-queue interrupted conversion batches.

        The first record is whatever was actually mid-encode, so its partial
        output is deleted before the rerun. Later records never started, and
        have nothing to clean up.
        """
        requeued = 0
        for i, rec in enumerate(records):
            paths = [p for p in rec.get("paths", []) if Path(p).exists()]
            if not paths:
                continue
            if i == 0:
                self._discard_partial_outputs(paths)
            if self._enqueue_conversion(paths):
                requeued += 1
        return requeued

    def _discard_partial_outputs(self, paths: List[str]) -> None:
        """Delete the outputs an interrupted batch had begun writing.

        A truncated .mp3/.mp4 left mid-encode is indistinguishable from a
        finished one by name alone, and leaving it would either be picked up
        as a source file or collide with the rerun's own output. The sources
        are still on disk (they are only deleted after a batch succeeds), so
        throwing the partial away costs nothing but the encode time.
        """
        _, flacs, cue, videos, error = detect_mode(paths)
        if error:
            return
        outputs = self._audio_outputs(flacs, cue) + self._video_outputs(videos)
        for out in outputs:
            try:
                p = Path(out)
                if p.is_file():
                    p.unlink()
            except OSError:
                pass

    def _stop_torrent_downloader(self) -> None:
        if self._torrent_downloader:
            self._torrent_downloader.stop()
            self._torrent_downloader = None
        for tid in list(self._torrent_progress_widgets):
            self._remove_torrent_progress(tid)

    def _on_torrent_progress(self, tid: str, name: str, progress: float) -> None:
        self.after(0, self._update_torrent_progress, tid, name, progress)

    def _update_torrent_progress(self, tid: str, name: str, progress: float) -> None:
        if progress == PROGRESS_QUEUED:
            # Over the concurrency limit: the torrent is accepted and shown,
            # it just hasn't been handed to a downloader yet.
            if tid not in self._torrent_progress_widgets:
                self._add_torrent_progress_row(tid, name)
            self._torrent_progress_widgets[tid]["bar"].set(0, "QUEUED")
            self._save_session()
            return
        if progress < 0:
            if tid not in self._torrent_progress_widgets:
                self._add_torrent_progress_row(tid, name)
            widgets = self._torrent_progress_widgets[tid]
            widgets["bar"].set(0, "ERROR")
            widgets["name_lbl"].config(fg=WARM)
            self.after(5000, self._remove_torrent_progress, tid)
            self._save_session()
            return
        new_row = tid not in self._torrent_progress_widgets
        if new_row:
            self._add_torrent_progress_row(tid, name)
        self._torrent_progress_widgets[tid]["bar"].set(progress)
        # Only when the set of live downloads actually changes — a progress
        # tick a second per torrent is not worth a disk write.
        if new_row or progress >= 1.0:
            self._save_session()

    def _add_torrent_progress_row(self, tid: str, name: str) -> None:
        self._play_torrent_added()
        frame = tk.Frame(self._torrent_progress_frame, bg=DARK)
        frame.pack(fill="x", padx=2 * SCALE, pady=1 * SCALE)
        short_name = format_torrent_name(name)
        name_lbl = tk.Label(frame, text=short_name, bg=DARK, fg=SAGE,
                            font=("Silkscreen", 8 * SCALE), anchor="w", width=20)
        name_lbl.pack(side="left")
        # Bars hang off the right edge, clear of the box outline, so every
        # row's bar lines up whatever its name is.
        bar = PixelBar(frame)
        bar.pack(side="right", padx=(4 * SCALE, INNER - 4 * SCALE))
        self._torrent_progress_widgets[tid] = {
            "frame": frame, "bar": bar, "name_lbl": name_lbl,
        }

    def _remove_torrent_progress(self, tid: str) -> None:
        widgets = self._torrent_progress_widgets.pop(tid, None)
        if widgets:
            widgets["frame"].destroy()

    def _on_torrent_complete(self, tid: str, download_path: str) -> None:
        self.after(0, self._on_torrent_complete_gui, tid, download_path)

    def _on_torrent_complete_gui(self, tid: str, download_path: str) -> None:
        """Move the finished download out of staging and into the monitored folder.

        Downloads land in a staging subfolder the watcher ignores, so nothing
        here is ever partially written — by the time this runs, the transfer
        is protocol-confirmed complete (aria2c exit 0 / libtorrent
        is_finished), not just "file size looks stable." Moving it into the
        real monitored folder lets the existing watcher pick it up exactly
        like a manual drop. Directory moves don't generate per-file watchdog
        events (the handler ignores directory move events), so multi-file
        torrents need one explicit nudge; single files are picked up
        naturally once they land.
        """
        self._play_torrent_downloaded()
        self._remove_torrent_progress(tid)
        self._save_session()
        monitor_folder = self._monitor_folder_var.get()
        if not monitor_folder:
            return
        src = Path(download_path)
        if not src.exists():
            return
        try:
            dest = self._move_into_monitor_folder(src, Path(monitor_folder), tid[:8])
        except OSError as e:
            self._set_info(f"Could not move downloaded file: {e}", WARM)
            return
        if dest.is_dir():
            self._enqueue_media_tree(str(dest))

    @staticmethod
    def _move_into_monitor_folder(src: Path, dest_parent: Path, tag: str) -> Path:
        """Move *src* into *dest_parent*, resolving same-name collisions.

        shutil.move merges *into* an existing destination directory rather
        than overwriting it, and raises on Windows for an existing
        destination file — neither of which should silently lose a freshly
        downloaded file, so both are handled explicitly.
        """
        dest = dest_parent / src.name
        if not dest.exists():
            shutil.move(str(src), str(dest))
            return dest
        if src.is_dir() and dest.is_dir():
            for item in src.iterdir():
                item_dest = dest / item.name
                if item_dest.exists():
                    item_dest = dest / f"{item.stem}_{tag}{item.suffix}"
                shutil.move(str(item), str(item_dest))
            src.rmdir()
            return dest
        disambiguated = dest_parent / f"{src.stem}_{tag}{src.suffix}"
        shutil.move(str(src), str(disambiguated))
        return disambiguated

    # ------------------------------------------------------------------
    # Encoding progress (encoding box)
    # ------------------------------------------------------------------
    def _add_encoding_progress(self, task_id: str, name: str) -> None:
        # Idempotent: a batch queued via _enqueue_conversion already has rows
        # by the time _load_files runs for it, and _load_files adds its own
        # rows for the direct-drop path where nothing added them yet — this
        # guard is what lets both call it without producing duplicate rows.
        if task_id in self._encoding_progress_widgets:
            return
        frame = tk.Frame(self._encoding_progress_frame, bg=BG)
        frame.pack(fill="x", padx=2 * SCALE, pady=1 * SCALE)
        short_name = name if len(name) <= 20 else name[:17] + "..."
        name_lbl = tk.Label(frame, text=short_name, bg=BG, fg=SAGE,
                            font=("Silkscreen", 8 * SCALE), anchor="w", width=20)
        name_lbl.pack(side="left")
        bar = PixelBar(frame)
        bar.pack(side="right", padx=(4 * SCALE, INNER - 4 * SCALE))
        self._encoding_progress_widgets[task_id] = {
            "frame": frame, "bar": bar, "name_lbl": name_lbl,
        }

    def _update_encoding_progress(self, task_id: str, progress: float) -> None:
        widgets = self._encoding_progress_widgets.get(task_id)
        if not widgets:
            return
        widgets["bar"].set(progress)

    def _remove_encoding_progress(self, task_id: str) -> None:
        widgets = self._encoding_progress_widgets.pop(task_id, None)
        if widgets:
            widgets["frame"].destroy()

    def _remove_encoding_rows(self, task_ids: List[str]) -> None:
        for task_id in task_ids:
            self._remove_encoding_progress(task_id)

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
            exclude_dirname=STAGING_DIRNAME,
        )
        try:
            self._monitor.start()
            self._recover_staged_downloads(folder)
            self._scan_existing_files(folder)
            self._schedule_staging_sweep()
        except Exception as e:
            self._set_status(f"Monitor error: {e}")
            self._monitor_var.set(False)
            self._monitor = None

    def _recover_staged_downloads(self, monitor_folder: str) -> int:
        """Move complete-looking downloads left behind in torrent staging
        into the real monitored folder, so they don't sit stuck forever.

        A download normally moves out of staging the instant it finishes
        (see _on_torrent_complete_gui) — but if Hoarder itself was closed
        or killed while a download was still in flight, the aria2c/
        libtorrent process is orphaned and can go on to finish completely
        with nobody left to notice or move it. aria2c leaves a ".aria2"
        control file next to any file it hasn't finished writing, and
        deletes it the moment that file is done — that's aria2c's own
        authoritative "is this actually complete" signal, so recovery
        checks for its absence rather than guessing from anything else.
        Entries that still have one are left alone: still downloading (by
        an orphaned process) or genuinely interrupted, either way not safe
        to convert yet.

        The control file is not the only guard. It is written periodically
        rather than continuously, so a transfer killed seconds after it
        started may have none at all — and the saved session, which lists
        every transfer that was still in flight at shutdown, is the record
        that survives that. Anything it still names is left in staging for
        _resume_downloads to pick up, however complete it looks here.
        """
        staging = Path(monitor_folder) / STAGING_DIRNAME
        if not staging.is_dir():
            return 0
        unfinished = self._unfinished_download_names()
        recovered = 0
        for entry in list(staging.iterdir()):
            if entry.suffix in (ARIA2_CONTROL_SUFFIX, ".torrent"):
                # aria2c's own bookkeeping — a control file, or the metadata
                # it saved for a magnet. Never content, and moving either one
                # into the monitored folder would have the watcher re-add it.
                continue
            if entry.name in unfinished:
                continue
            if self._has_incomplete_download(entry):
                continue
            try:
                self._move_into_monitor_folder(entry, Path(monitor_folder), "recovered")
                recovered += 1
            except OSError:
                pass  # best-effort; the next monitor start tries again
        if recovered:
            plural = "s" if recovered != 1 else ""
            self._set_info(f"Recovered {recovered} interrupted download{plural}", SAGE)
        return recovered

    # How often the monitor re-checks staging for downloads whose completion
    # was never acted on — e.g. on_complete firing while a widget it touches
    # no longer exists, or any other one-off failure in that handoff. Startup
    # recovery alone only runs once per launch; a torrent that finishes and
    # gets stuck hours into a long-running session would otherwise sit there
    # until the app is restarted.
    _STAGING_SWEEP_MS = 90_000

    def _schedule_staging_sweep(self) -> None:
        self._staging_sweep_after_id = self.after(
            self._STAGING_SWEEP_MS, self._sweep_stuck_staging
        )

    def _sweep_stuck_staging(self) -> None:
        folder = self._monitor_folder_var.get()
        if self._monitor is None or not folder:
            self._staging_sweep_after_id = None
            return
        if self._recover_staged_downloads(folder):
            self._scan_existing_files(folder)
        self._schedule_staging_sweep()

    @staticmethod
    def _unfinished_download_names() -> set:
        """Content names the saved session still lists as in flight.

        Read from disk rather than from the live downloader: at startup this
        runs before the resume does, and after a resume the same names are
        written straight back, so either way it reflects what must not be
        swept out of staging.
        """
        try:
            records = sess.load()["downloads"]
        except Exception:
            return set()
        return {r.get("name", "") for r in records if r.get("name")}

    @staticmethod
    def _has_incomplete_download(path: Path) -> bool:
        """True if aria2c still considers anything at or under *path* unfinished.

        Delegates so the ".aria2" placement rule lives in exactly one place:
        aria2c writes the control file *beside* what it is downloading, which
        for a multi-file torrent means beside the folder, not inside it.
        """
        return has_incomplete_download(path)

    def _scan_existing_files(self, folder: str) -> None:
        """Queue conversion jobs for everything already sitting in *folder*."""
        self._enqueue_media_tree(folder)

    def _enqueue_media_tree(self, root: str) -> None:
        """Queue conversion jobs for all audio and video files under *root*.

        Files are grouped by parent directory so each subfolder becomes its own
        job and all jobs run sequentially via _conversion_queue. Used both for
        the monitor's startup scan (root = the whole monitored folder) and for
        a just-completed torrent (root = wherever it landed) — either way,
        anything still sitting in the torrent staging area is skipped, since
        that means it isn't actually finished downloading yet.
        """
        folder_path = Path(root)

        def _not_staging(p: Path) -> bool:
            return STAGING_DIRNAME not in p.parts

        def _usable(p: Path) -> bool:
            # Skip stray 0-byte placeholders (e.g. aria2/torrent artifacts left
            # behind in the folder) — real media is never empty, and handing
            # one of these to ffprobe fails with no usable error message.
            try:
                return p.stat().st_size > 0
            except OSError:
                return False

        # --- Audio: collect all supported formats, group by parent directory ---
        audio_by_dir: dict[Path, list[Path]] = {}
        for ext in AUDIO_EXTS:
            for audio in sorted(folder_path.rglob(f"*{ext}")):
                if _not_staging(audio) and _usable(audio):
                    audio_by_dir.setdefault(audio.parent, []).append(audio)
        for d in audio_by_dir:
            audio_by_dir[d].sort()

        for dir_path, dir_audio in sorted(audio_by_dir.items()):
            cue_files = sorted(dir_path.glob("*.cue"))
            if not cue_files:
                # No CUEs — batch all audio files together
                self.after(0, self._enqueue_new,
                           [str(f) for f in dir_audio])
            else:
                # Pair CUEs with audio via stem-match + FILE directive fallback
                pairs = self._pair_cues_flacs(cue_files, dir_audio)
                paired_audio_set = {audio for audio, _ in pairs}
                for audio, cue in pairs:
                    # The CUE rides along: only the audio is library-checked.
                    self.after(0, self._enqueue_pair, str(audio), str(cue))
                lone = [str(f) for f in dir_audio if f not in paired_audio_set]
                if lone:
                    self.after(0, self._enqueue_new, lone)

        # --- Video: group by parent directory ---
        videos_by_dir: dict[Path, list[str]] = {}
        for pat in ("*.mp4", "*.mkv", "*.mov", "*.wmv", "*.avi"):
            for vid in sorted(folder_path.rglob(pat)):
                if _not_staging(vid) and _usable(vid):
                    videos_by_dir.setdefault(vid.parent, []).append(str(vid))
        for dir_path in sorted(videos_by_dir):
            self.after(0, self._enqueue_new, videos_by_dir[dir_path])

    def _enqueue_pair(self, audio: str, cue: str) -> None:
        """Enqueue an audio+CUE disc unless the audio is already in the library."""
        if libmod.filter_new([audio]):
            self._enqueue_conversion([audio, cue])

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

    def _enqueue_new(self, paths: List[str]) -> None:
        """Enqueue only the files the library has not already converted.

        Used by every automatic path — the startup scan, the folder watcher and
        finished torrents — so a restart does not re-encode a folder it has
        already been through. Files dropped or browsed by hand skip this check:
        asking for a file explicitly means asking for it to be converted.
        """
        fresh = libmod.filter_new(paths)
        if fresh:
            self._enqueue_conversion(fresh)

    def _enqueue_conversion(self, paths: List[str]) -> bool:
        """Validate *paths* and add them to the conversion queue.

        Silently ignores batches that detect_mode rejects (e.g. unsupported
        types arriving from the file-system watcher).  If nothing is currently
        converting, starts processing immediately.

        Encoding rows for the whole batch appear right away, not once it
        actually starts converting — so queuing up several folders at once
        (e.g. every disc of a multi-folder torrent) shows the full pending
        list immediately instead of revealing one folder at a time as each
        prior one finishes.

        Returns whether the batch was actually taken on.
        """
        _, flacs, _, videos, error = detect_mode(paths)
        if error:
            return False
        # Two paths can legitimately reach the same batch — the startup folder
        # scan and a resumed session both offer the monitored folder's files —
        # and encoding the same file twice would race two ffmpeg runs onto one
        # output. The library can't catch this: it only knows what has already
        # finished, not what is queued right now.
        if self._already_queued(paths):
            return False
        self._conversion_queue.append(paths)
        for f in flacs:
            self.after(0, self._add_encoding_progress, f, Path(f).name)
        for v in videos:
            self.after(0, self._add_encoding_progress, v, Path(v).name)
        self._save_session()
        self._process_next_queue_item()
        return True

    def _already_queued(self, paths: List[str]) -> bool:
        """True if any of *paths* is already queued or being converted."""
        pending = set()
        for batch in self._conversion_queue:
            pending.update(self._ignore_key(p) for p in batch)
        if self._active_batch:
            pending.update(self._ignore_key(p) for p in self._active_batch)
        return any(self._ignore_key(p) in pending for p in paths)

    def _process_next_queue_item(self) -> None:
        """Pop and start the next batch from the queue if the app is idle.

        Called both when a new item is enqueued and at the end of every
        conversion (via the finally block in _run_conversion).
        """
        if self._is_converting or not self._conversion_queue:
            return
        paths = self._conversion_queue.pop(0)
        self._active_batch = list(paths)
        self._save_session()
        self._load_files(paths)
        # Start even when auto_convert is off (monitor items always convert).
        # If _load_files already started it (auto_convert=True) this is a no-op
        # because _is_converting will already be True.
        if self._mode is not None and not self._is_converting:
            self._start_conversion()

    def _stop_monitor(self) -> None:
        if self._staging_sweep_after_id is not None:
            self.after_cancel(self._staging_sweep_after_id)
            self._staging_sweep_after_id = None
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    # ------------------------------------------------------------------
    # Self-produced output suppression
    # ------------------------------------------------------------------
    @staticmethod
    def _ignore_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _ignore_output(self, path: str) -> None:
        """Mark *path* as this app's own output so the watcher skips it once."""
        with self._ignore_lock:
            self._ignore_paths.add(self._ignore_key(path))

    def _claim_ignored(self, path: str) -> bool:
        """True if *path* was a registered output; consumes the registration.

        One-shot so a file the user later drops in under the same name is
        still converted normally.
        """
        key = self._ignore_key(path)
        with self._ignore_lock:
            if key in self._ignore_paths:
                self._ignore_paths.discard(key)
                return True
        return False

    def _on_monitor_files(self, paths: List[str]) -> None:
        """Called from watchdog thread when new files arrive - marshal to main thread."""
        paths = [p for p in paths if not self._claim_ignored(p)]
        if not paths:
            return
        self.after(0, self._enqueue_new, paths)

    def _on_torrent_files(self, paths: List[str]) -> None:
        """Called from watchdog thread when torrent files arrive."""
        if not self._torrent_var.get() or not self._torrent_downloader:
            return
        self.after(0, self._process_torrent_files, paths)

    def _process_torrent_files(self, paths: List[str]) -> None:
        for path in paths:
            if self._torrent_downloader is None:
                return
            tid = self._torrent_downloader.add(path)
            # Only clean up the source file if the torrent was actually added.
            if tid is not None and self._torrent_delete_var.get():
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
        # Before anything is torn down: stopping the downloader clears the
        # very state a snapshot is built from, so saving afterwards would
        # record an empty session and strand every part-finished transfer.
        try:
            self._save_session()
        except Exception:
            pass  # never let bookkeeping block the shutdown
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
