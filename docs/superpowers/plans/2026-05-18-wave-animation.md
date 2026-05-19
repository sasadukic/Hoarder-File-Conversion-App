# Wave Animation & Conversion File Display — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sine-wave letter animation to the "Drag & Drop" label (always on) and the convert button (during conversion only), and show the current converting file name in the info label.

**Architecture:** All changes are confined to `gui.py`. A single 40 ms `after`-loop tick drives two `tk.Canvas` widgets — one replacing the drop label, one overlaying the convert button. A thin closure change in `_run_conversion` updates `_info_label` per file.

**Tech Stack:** Python 3, tkinter (`tk.Canvas`, `tk.font.Font`), customtkinter, existing Silkscreen font.

---

### Task 1: Add wave state variables and font objects in `_build_ui`

**Files:**
- Modify: `gui.py` — `_build_ui` method and class init area

- [ ] **Step 1: Add instance variables at the top of `_build_ui` (before drop zone block)**

In `gui.py`, inside `_build_ui`, add right after `s = self._settings`:

```python
        # Wave animation state
        self._wave_phase: float = 0.0
        self._wave_btn_text: str = "Convert"
        self._wave_btn_visible: bool = False
        import tkinter.font as tkfont
        self._wave_font_drop = tkfont.Font(family="Silkscreen", size=16)
        self._wave_font_btn  = tkfont.Font(family="Silkscreen", size=28)
```

- [ ] **Step 2: Run existing tests to confirm no breakage**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 3: Commit**

```
git add gui.py
git commit -m "feat(wave): add wave state variables and font objects"
```

---

### Task 2: Replace `_drop_label` with `_drop_canvas`

**Files:**
- Modify: `gui.py` — drop zone block inside `_build_ui`, and anywhere `_drop_label` is referenced

- [ ] **Step 1: Replace the `_drop_label = tk.Label(...)` block**

Find in `_build_ui` (around line 184):
```python
        self._drop_label = tk.Label(
            self._drop_frame,
            text="Drag & Drop",
            bg=PANEL,
            fg=DIM,
            font=("Silkscreen", 16),
            justify="center",
        )
        self._drop_label.place(relx=0.5, rely=0.5, anchor="center")

        for widget in (self._drop_frame, self._drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.bind("<Button-1>", lambda e: self._browse())
```

Replace with:
```python
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
```

- [ ] **Step 2: Check no remaining references to `_drop_label`**

Search `gui.py` for `_drop_label` — should be zero occurrences after this edit.

- [ ] **Step 3: Run tests**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 4: Commit**

```
git add gui.py
git commit -m "feat(wave): replace _drop_label with _drop_canvas"
```

---

### Task 3: Add `_draw_wave_drop` and `_draw_wave_btn` methods

**Files:**
- Modify: `gui.py` — add two new methods after `_reset_ui`

- [ ] **Step 1: Add `_draw_wave_drop` after `_reset_ui`**

```python
    def _draw_wave_drop(self) -> None:
        """Redraw the drop-zone canvas with a waving 'Drag & Drop' text."""
        import math
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
```

- [ ] **Step 2: Add `_draw_wave_btn` directly after `_draw_wave_drop`**

```python
    def _draw_wave_btn(self) -> None:
        """Redraw the button-overlay canvas with waving status text."""
        import math
        c = self._wave_canvas_btn
        c.delete("all")
        text = self._wave_btn_text
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
```

- [ ] **Step 3: Run tests**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 4: Commit**

```
git add gui.py
git commit -m "feat(wave): add _draw_wave_drop and _draw_wave_btn methods"
```

---

### Task 4: Add `_wave_canvas_btn` widget and `_wave_tick` loop

**Files:**
- Modify: `gui.py` — convert button block inside `_build_ui`; add `_wave_tick` method

- [ ] **Step 1: Add `_wave_canvas_btn` after the `_convert_btn` place call**

Find in `_build_ui`:
```python
        self._convert_btn.place(x=16, y=374)
```

Add immediately after:
```python
        # Button wave overlay (hidden until conversion starts)
        self._wave_canvas_btn = tk.Canvas(
            self,
            bg=LIGHT,
            highlightthickness=0,
        )
        # not placed yet — shown by _start_conversion
```

- [ ] **Step 2: Add `_wave_tick` method after `_draw_wave_btn`**

```python
    def _wave_tick(self) -> None:
        """Periodic animation tick — runs every 40 ms for the lifetime of the app."""
        self._wave_phase += 0.25
        self._draw_wave_drop()
        if self._wave_btn_visible:
            self._draw_wave_btn()
        self.after(40, self._wave_tick)
```

- [ ] **Step 3: Start the tick loop at the end of `_build_ui`**

Find the last line of `_build_ui`:
```python
        if s["monitor_folder"] and s["monitor_enabled"]:
            self._monitor_var.set(True)
            self._start_monitor(s["monitor_folder"])
```

Add after:
```python
        # Start animation loop
        self.after(40, self._wave_tick)
```

- [ ] **Step 4: Run tests**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 5: Commit**

```
git add gui.py
git commit -m "feat(wave): add _wave_canvas_btn and start _wave_tick loop"
```

---

### Task 5: Add `_hide_wave_btn` helper and wire show/hide in conversion flow

**Files:**
- Modify: `gui.py` — `_set_status`, `_start_conversion`, `_run_conversion`, add `_hide_wave_btn`, `_show_done`, `_set_converting_file`

- [ ] **Step 1: Add `_hide_wave_btn` method (after `_wave_tick`)**

```python
    def _hide_wave_btn(self, text: str) -> None:
        """Stop the button wave overlay and restore normal button text."""
        self._wave_btn_visible = False
        self._wave_canvas_btn.place_forget()
        self._convert_btn.configure(text=text)
```

- [ ] **Step 2: Add `_set_converting_file` method**

```python
    def _set_converting_file(self, path: str) -> None:
        """Show the currently converting file name in the info label."""
        self._info_label.config(text=Path(path).name, fg=SAGE)
```

- [ ] **Step 3: Add `_show_done` method**

```python
    def _show_done(self) -> None:
        """Called on successful conversion completion."""
        self._hide_wave_btn("Done.")
        has_files = bool(self._flac_paths or self._video_paths)
        self._info_label.config(
            text="Files Loaded" if has_files else "No files loaded",
            fg=SAGE if has_files else DIM,
        )
```

- [ ] **Step 4: Update `_set_status` to also set `_wave_btn_text`**

Find:
```python
    def _set_status(self, text: str, color: str = GREEN) -> None:
        """Update the convert button text with a status message."""
        self._convert_btn.configure(text=text)
        self.update_idletasks()
```

Replace with:
```python
    def _set_status(self, text: str, color: str = GREEN) -> None:
        """Update the convert button text (or wave canvas text during conversion)."""
        self._wave_btn_text = text
        if not self._wave_btn_visible:
            self._convert_btn.configure(text=text)
        self.update_idletasks()
```

- [ ] **Step 5: Update `_start_conversion` to show the wave canvas**

Find in `_start_conversion`:
```python
        self._is_converting = True
        self._convert_btn.configure(state="disabled")
        self._set_status("Conversion Running", SAGE)
```

Replace with:
```python
        self._is_converting = True
        self._convert_btn.configure(state="disabled", text="")
        self._wave_btn_text = "Conversion Running"
        self._wave_btn_visible = True
        self._wave_canvas_btn.place(x=16, y=374, width=468, height=56)
```

- [ ] **Step 6: Run tests**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 7: Commit**

```
git add gui.py
git commit -m "feat(wave): wire show/hide wave canvas in conversion flow"
```

---

### Task 6: Update `_run_conversion` — per-file name display and done/error handling

**Files:**
- Modify: `gui.py` — `_run_conversion` method

- [ ] **Step 1: Update `on_audio_progress` to set current file name**

Find `on_audio_progress` inside `_run_conversion`:
```python
        def on_audio_progress(cur: int, total: int) -> None:
            completed[0] = cur
            pct = int(completed[0] / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")
```

Replace with:
```python
        def on_audio_progress(cur: int, total: int) -> None:
            completed[0] = cur
            # Show current file name (cur is 1-indexed; audio files are flacs or CUE tracks)
            file_list = flacs  # always the FLAC paths, even for CUE mode
            if file_list and 0 <= cur - 1 < len(file_list):
                self.after(0, self._set_converting_file, file_list[cur - 1])
            pct = int(completed[0] / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")
```

- [ ] **Step 2: Update `on_video_progress` to set current file name**

Find:
```python
        def on_video_progress(cur: int, total: int) -> None:
            pct = int((audio_units + cur) / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")
```

Replace with:
```python
        _last_video_idx = [-1]

        def on_video_progress(cur: float, total: int) -> None:
            idx = min(int(cur), total - 1)
            if idx != _last_video_idx[0] and 0 <= idx < len(videos):
                _last_video_idx[0] = idx
                self.after(0, self._set_converting_file, videos[idx])
            pct = int((audio_units + cur) / grand_total * 100)
            self.after(0, self._set_status, f"Conversion Running {pct}%")
```

- [ ] **Step 3: Replace the "Done message" block**

Find:
```python
            # Done message
            self.after(0, self._play_done)
            self.after(0, self._set_status, "Done.")
            if do_delete:
                self.after(3000, self._reset_ui)
```

Replace with:
```python
            # Done
            self.after(0, self._play_done)
            self.after(0, self._show_done)
            if do_delete:
                self.after(3000, self._reset_ui)
```

- [ ] **Step 4: Update error handlers to hide wave canvas**

Find the except blocks:
```python
        except ValueError as e:
            self.after(0, self._set_status, f"Could not parse CUE file: {e}")
        except RuntimeError as e:
            self.after(0, self._set_status, str(e))
        except Exception as e:
            self.after(0, self._set_status, f"Unexpected error: {e}")
        finally:
            self._is_converting = False
            self.after(0, lambda: self._convert_btn.configure(state="normal"))
```

Replace with:
```python
        except ValueError as e:
            self.after(0, self._hide_wave_btn, f"Could not parse CUE file: {e}")
        except RuntimeError as e:
            self.after(0, self._hide_wave_btn, str(e))
        except Exception as e:
            self.after(0, self._hide_wave_btn, f"Unexpected error: {e}")
        finally:
            self._is_converting = False
            self.after(0, lambda: self._convert_btn.configure(state="normal"))
```

- [ ] **Step 5: Run tests**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 6: Commit**

```
git add gui.py
git commit -m "feat(wave): per-file info label + hide wave on done/error"
```

---

### Task 7: Manual smoke test

- [ ] **Step 1: Launch the app**

```
py main.py
```

Verify:
- "Drag & Drop" text is visibly waving up and down immediately on startup.
- Convert button shows "Convert" statically (no wave).

- [ ] **Step 2: Load a video or FLAC file and start conversion**

- Info label changes to the file name as each file is processed.
- Convert button text waves (e.g., "Conversion Running 45%").
- Wave amplitude is noticeable but not jarring.

- [ ] **Step 3: Verify done state**

- On completion: button stops waving, shows "Done." then wave overlay disappears.
- Info label resets to "Files Loaded".
- "Drag & Drop" canvas continues waving.

- [ ] **Step 4: Final test run**

```
py -m pytest tests/ -q
```
Expected: `66 passed`

- [ ] **Step 5: Final commit**

```
git add gui.py
git commit -m "feat(wave): smoke-tested wave animation feature complete"
```
