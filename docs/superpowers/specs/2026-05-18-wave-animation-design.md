# Wave Animation & Conversion File Display — Design Spec
_Date: 2026-05-18_

## Overview

Four UI changes to `gui.py`:

1. "Drag & Drop" label waves up/down continuously (always, regardless of conversion state).
2. Convert button text waves during conversion only; stops and returns to normal on done.
3. Info label (`_info_label`) shows the name of the currently converting file during conversion.
4. On conversion end, info label resets to its pre-conversion value.

No changes to `converter.py`, `tests/`, or any other file.

---

## Animation Engine

A single `_wave_tick()` method drives all animation. It is started once in `_build_ui` via
`self.after(40, self._wave_tick)` and reschedules itself unconditionally:

```python
def _wave_tick(self) -> None:
    self._wave_phase += 0.25          # ~1.6 rad/s at 25 fps
    self._draw_wave_drop()
    if self._wave_btn_visible:
        self._draw_wave_btn()
    self.after(40, self._wave_tick)
```

Instance variables added to `__init__` (via `_build_ui`):

| Variable | Type | Purpose |
|---|---|---|
| `_wave_phase` | `float` | Current phase, incremented every tick |
| `_wave_btn_text` | `str` | Text currently displayed in button wave canvas |
| `_wave_btn_visible` | `bool` | Whether button canvas overlay is shown |

Wave formula per character `i` (0-indexed):

```
y_offset = amplitude * sin(phase + i * 0.6)
```

Amplitude: **4 px** for drop canvas (Silkscreen 16), **5 px** for button canvas (Silkscreen 28).

---

## 1. Drop Zone Canvas

### Change
Replace `_drop_label` (`tk.Label`) with `_drop_canvas` (`tk.Canvas`).

### Placement
Same as current label: inside `_drop_frame`, `relx=0.5, rely=0.5, anchor="center"`, full frame size.

Actually: place as `tk.Canvas` filling the entire `_drop_frame` via `pack(fill="both", expand=True)` — simpler than nested placement.

### Rendering (`_draw_wave_drop`)
Each tick:
1. `_drop_canvas.delete("all")`
2. Measure total text width: `sum(font.measure(ch) for ch in "Drag & Drop")`
3. Start `x = (canvas_width - total_width) / 2`
4. For each character `i`, draw at `(x + half_char_width, center_y + 4*sin(phase + i*0.6))`; advance `x` by `font.measure(ch)`.

Font object: `tk.font.Font(family="Silkscreen", size=16)` — created once in `_build_ui`, stored as `_wave_font_drop`.

Canvas bg: `PANEL`. Text fill: `DIM` (= `LIGHT` = `#f0f6f0`).

### Bindings
`_drop_canvas` (not `_drop_frame`) gets the DND and click bindings. `_drop_frame` retains them too for the border area.

---

## 2. Convert Button Wave Canvas Overlay

### Change
Add `_wave_canvas_btn` (`tk.Canvas`, `bg=LIGHT`, `highlightthickness=0`) placed at the **same coordinates** as `_convert_btn` (`x=16, y=374, width=468, height=56`). Initially hidden (`not placed`).

### Show/Hide
- **Show**: called from `_start_conversion` after setting `_is_converting = True`.
  - `_convert_btn.configure(text="")` 
  - `_wave_canvas_btn.place(x=16, y=374, width=468, height=56)`
  - `_wave_btn_visible = True`
- **Hide**: called from `_run_conversion` finally block (via `self.after(0, ...)`) on completion.
  - `_wave_btn_visible = False`
  - `_wave_canvas_btn.place_forget()`
  - `_convert_btn.configure(text=<final_text>)`

### Rendering (`_draw_wave_btn`)
Same algorithm as drop canvas. Font: `tk.font.Font(family="Silkscreen", size=28)`, stored as `_wave_font_btn`. Canvas bg: `LIGHT`. Text fill: `DARK`.

Text source: `self._wave_btn_text` (updated by `_set_status`).

### `_set_status` update
Currently: `self._convert_btn.configure(text=text)`.

After change:
```python
def _set_status(self, text: str, color: str = GREEN) -> None:
    self._wave_btn_text = text
    if not self._wave_btn_visible:
        self._convert_btn.configure(text=text)
    self.update_idletasks()
```

So during conversion, `_set_status` only updates the wave text var (the canvas redraws it next tick). Outside conversion, it still sets the button text directly.

---

## 3. Current File in Info Label

### Change
Add `_set_converting_file(name: str)` method:

```python
def _set_converting_file(self, name: str) -> None:
    self._info_label.config(text=Path(name).name, fg=SAGE)
```

### Integration in `_run_conversion`

Before calling each conversion function, call `self.after(0, self._set_converting_file, path)` for each file. Specifically:

- **`split_and_convert`**: one FLAC file → call `_set_converting_file(flacs[0])` once before the call.
- **`convert_files`**: wrap in a loop that calls `_set_converting_file` per file, or pass a pre-progress hook. Since `convert_files` iterates internally, the simplest approach is to call `_set_converting_file(flac_path)` for each file by wrapping the progress callback to also update the label on first call for that index.
  - Actually simpler: before `convert_files(flacs, cb)`, iterate and use a counter in the audio progress callback to derive the current file name from `flacs[cur-1]`.
- **`transcode_videos`**: before `transcode_videos(videos, cb, ...)`, similarly derive current file from video index in `on_video_progress`.

Concrete plan:
- `on_audio_progress(cur, total)` already knows `cur` and `flacs` list → call `self.after(0, self._set_converting_file, flacs[cur-1])` at the start of each callback invocation.
- `on_video_progress(cur, total)` knows `cur` is float → `int(cur)` gives current file index → `videos[int(cur)]` (but `cur` can be fractional). Better: track last integer in a closure variable.

### Video file name tracking
Since `on_video_progress` receives `(float, int)` where float = `i-1 + pct`, the current file index is `int(cur)` clamped to `[0, total-1]`. Use a closure `last_idx = [-1]`:

```python
def on_video_progress(cur: float, total: int) -> None:
    idx = min(int(cur), total - 1)
    if idx != last_idx[0]:
        last_idx[0] = idx
        self.after(0, self._set_converting_file, videos[idx])
    pct = int((audio_units + cur) / grand_total * 100)
    self.after(0, self._set_status, f"Conversion Running {pct}%")
```

---

## 4. Reset on Done

On successful completion:

```python
self.after(0, self._play_done)
self.after(0, self._show_done)   # new method
```

`_show_done`:
```python
def _show_done(self) -> None:
    self._hide_wave_btn("Done.")
    self._info_label.config(
        text="Files Loaded" if self._flac_paths or self._video_paths else "No files loaded",
        fg=SAGE,
    )
```

If `do_delete` is True, `_reset_ui` is called after 3 s as before (which sets info to "No files loaded").

On error, `_hide_wave_btn(error_text)` is called with the error string, info label stays on last file name (acceptable — error is prominent in the button).

`_hide_wave_btn(text: str)`:
```python
def _hide_wave_btn(self, text: str) -> None:
    self._wave_btn_visible = False
    self._wave_canvas_btn.place_forget()
    self._convert_btn.configure(text=text)
```

---

## Summary of New/Changed Members in `App`

| Member | Kind | Description |
|---|---|---|
| `_drop_canvas` | `tk.Canvas` | Replaces `_drop_label` |
| `_wave_font_drop` | `tk.font.Font` | Silkscreen 16, used for drop canvas drawing |
| `_wave_canvas_btn` | `tk.Canvas` | Overlay on convert button |
| `_wave_font_btn` | `tk.font.Font` | Silkscreen 28, used for button canvas drawing |
| `_wave_phase` | `float` | Shared phase for all animations |
| `_wave_btn_text` | `str` | Text currently waving in button canvas |
| `_wave_btn_visible` | `bool` | Whether button canvas overlay is active |
| `_wave_tick()` | method | 40 ms periodic animation tick |
| `_draw_wave_drop()` | method | Redraws drop canvas |
| `_draw_wave_btn()` | method | Redraws button canvas |
| `_set_converting_file(name)` | method | Updates info label to file basename |
| `_hide_wave_btn(text)` | method | Hides button canvas, restores button text |
| `_show_done()` | method | Called on conversion success |
| `_set_status` | modified | Also updates `_wave_btn_text` |
| `_start_conversion` | modified | Shows button canvas |
| `_run_conversion` | modified | Updates info label per file; calls `_show_done`/`_hide_wave_btn` |

---

## Testing

No automated tests for animation (visual-only). Existing 66 tests must continue to pass unchanged. Manual verification:
- "Drag & Drop" label waves continuously at app startup.
- Convert button waves during conversion; stops on done.
- Info label shows each file name as it is processed.
- Info label resets to "Files Loaded" after success (or "No files loaded" after delete + reset).
