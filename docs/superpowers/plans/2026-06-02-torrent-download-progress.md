# Torrent Download Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show active torrent downloads in the Downloads tab with cleaned, truncated names and a right-aligned progress indicator that disappears when complete.

**Architecture:** Keep the change in `gui.py` so it stays presentation-only. Add a tiny name-normalization helper, use it when rendering torrent rows, and preserve the existing torrent downloader callbacks and completion removal path.

**Tech Stack:** Python, tkinter/customtkinter, pytest

---

### Task 1: Add download-name formatting in the GUI

**Files:**
- Modify: `gui.py`
- Test: `tests/test_gui.py`

- [x] **Step 1: Write the failing test**

```python
def test_format_torrent_name_strips_dots_dashes_and_truncates():
    result = format_torrent_name("AB.CD - EF.GH IJ.KL MN.OP QR")
    assert result == "ABCD  EFGH IJKL MNOP"
    assert len(result) == 20
    assert "." not in result
    assert "-" not in result
```

- [x] **Step 2: Run the test to verify it fails**

Run: `py -m pytest tests/test_gui.py -q`
Expected: import error for `format_torrent_name` before implementation.

- [x] **Step 3: Write minimal implementation**

```python
def format_torrent_name(name: str, limit: int = 20) -> str:
    cleaned = name.replace(".", "").replace("-", "")
    return cleaned[:limit]
```

- [x] **Step 4: Run test to verify it passes**

Run: `py -m pytest tests/test_gui.py -q`
Expected: pass.

---

### Task 2: Use the formatted name in the Downloads row

**Files:**
- Modify: `gui.py`

- [x] **Step 1: Update torrent row rendering**

```python
def _add_torrent_progress_row(self, tid: str, name: str) -> None:
    frame = tk.Frame(self._torrent_progress_frame, bg=DARK)
    frame.pack(fill="x", padx=2, pady=1)
    short_name = format_torrent_name(name)
    name_lbl = tk.Label(frame, text=short_name, bg=DARK, fg=SAGE,
                        font=("Silkscreen", 8), anchor="w", width=20)
    name_lbl.pack(side="left")
    bar = ctk.CTkProgressBar(frame, width=180, height=14)
    bar.set(0)
    bar.pack(side="left", padx=(4, 4))
    pct = tk.Label(frame, text="0%", bg=DARK, fg=TEXT,
                    font=("Silkscreen", 8), width=4)
    pct.pack(side="left")
```

- [x] **Step 2: Verify the full suite**

Run: `py -m pytest tests -q`
Expected: all tests pass.
