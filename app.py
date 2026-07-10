"""
Metadata Remover -- a small desktop app that strips EXIF/GPS/comment/ICC
metadata from images before you share them.

Run with:  python app.py
Requires:  pip install -r requirements.txt
           (tkinter ships with standard Python on Windows/macOS; on Linux
           install your distro's python3-tk package)
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as ttk
from PIL import Image, ImageDraw, ImageTk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y

from core import SUPPORTED_EXTENSIONS, default_output_path, inspect_metadata, strip_metadata

APP_TITLE = "Metadata Remover"

# ---- palette: black-and-neon terminal theme --------------------------------
BG = "#060907"
LIST_BG = "#08100c"
SCANLINE = "#0b1811"
CARD_BG = "#0c1611"
CARD_BG_RGB = (12, 22, 17)
CARD_BORDER = "#1c3327"
TEXT_PRIMARY = "#dffff0"
TEXT_SECONDARY = "#6fae82"
TEXT_MUTED = "#375242"
GREEN = "#39ff88"
GREEN_DIM = "#1f8a4d"
CYAN = "#3ce6ff"
WARNING = "#ffd23f"
DANGER = "#ff4d4d"
PENDING = "#375242"

MONO = "Consolas"
TITLE_FONT = (MONO, 22, "bold")
SUBTITLE_FONT = (MONO, 10)
BODY_FONT = (MONO, 11)
NAME_FONT = (MONO, 11, "bold")
META_FONT = (MONO, 9)
BADGE_FONT = (MONO, 8, "bold")
STATUS_FONT = (MONO, 10, "bold")

THUMB_SIZE = (100, 100)
THUMB_RADIUS = 4
CARD_HEIGHT = 132
CARD_RADIUS = 6


# ---- image helpers ----------------------------------------------------------

def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return mask


def _load_thumbnail(path: Path, size=THUMB_SIZE) -> ImageTk.PhotoImage:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail(size)
        base = Image.new("RGB", size, CARD_BG_RGB)
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        base.paste(img, offset)
    base = base.convert("RGBA")
    base.putalpha(_rounded_mask(size, THUMB_RADIUS))
    return ImageTk.PhotoImage(base)


def _placeholder_thumbnail(size=THUMB_SIZE) -> ImageTk.PhotoImage:
    tile = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle(
        [1, 1, size[0] - 2, size[1] - 2], radius=THUMB_RADIUS, outline="#1c3327", width=2
    )
    return ImageTk.PhotoImage(tile)


def _round_rect_points(x1, y1, x2, y2, r):
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _short_metadata_summary(report) -> str:
    if report.is_empty:
        return "no metadata found"
    parts = list(report.exif_tags.keys())[:3]
    text = ", ".join(parts)
    remaining = len(report.exif_tags) - len(parts) + len(report.info_keys)
    if remaining > 0:
        text += f" +{remaining} more" if text else f"{remaining} field(s)"
    return text or "metadata present"


STATE_COLOR = {
    "pending": PENDING,
    "processing": CYAN,
    "done": GREEN,
    "warn": WARNING,
    "failed": DANGER,
}
STATE_LABEL = {
    "pending": "[ QUEUED ]",
    "processing": "[ SCANNING... ]",
    "done": None,
    "warn": None,
    "failed": None,
}


class ImageCard:
    """One image, rendered as a single canvas so the panel border, accent
    bar, thumbnails, and status tag are all drawn together."""

    def __init__(self, parent, path: Path, on_remove):
        self.path = path
        self.on_remove = on_remove
        self.state = "pending"
        self.status_text = "[ QUEUED ]"
        self.summary = "scanning..."
        self.summary_color = TEXT_SECONDARY

        self.before_photo = _placeholder_thumbnail()
        self.after_photo = _placeholder_thumbnail()

        self.canvas = tk.Canvas(parent, height=CARD_HEIGHT, bg=LIST_BG, highlightthickness=0)
        self.canvas.pack(fill=X, pady=6, padx=2)
        self.canvas.bind("<Configure>", lambda e: self._redraw())

    # ---- drawing ----------------------------------------------------------

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = CARD_HEIGHT
        if w < 10:
            return

        accent = STATE_COLOR[self.state]

        c.create_polygon(
            _round_rect_points(1, 1, w - 1, h - 1, CARD_RADIUS),
            smooth=True, fill=CARD_BG, outline=accent if self.state != "pending" else CARD_BORDER, width=1,
        )
        c.create_polygon(
            _round_rect_points(1, 1, 5, h - 1, CARD_RADIUS),
            smooth=True, fill=accent, outline="",
        )

        pad = 16
        thumb_y = h // 2

        c.create_image(pad + THUMB_SIZE[0] // 2, thumb_y, image=self.before_photo)

        text_x = pad * 2 + THUMB_SIZE[0]
        after_x = w - pad - THUMB_SIZE[0] // 2
        arrow_x = after_x - THUMB_SIZE[0] // 2 - 34
        text_wrap = max(120, arrow_x - 34 - text_x)

        c.create_text(
            text_x, thumb_y - 28, anchor="w", text=self.path.name,
            font=NAME_FONT, fill=TEXT_PRIMARY, width=text_wrap,
        )
        c.create_text(
            text_x, thumb_y - 6, anchor="w", text=self.summary,
            font=META_FONT, fill=self.summary_color, width=text_wrap,
        )

        pill_text = self.status_text
        text_id = c.create_text(0, 0, anchor="nw", text=pill_text, font=BADGE_FONT)
        bbox = c.bbox(text_id)
        c.delete(text_id)
        pill_pad_x = 8
        pill_w = (bbox[2] - bbox[0]) + pill_pad_x * 2 if bbox else 60
        pill_h = 20
        pill_y0 = thumb_y + 12
        c.create_rectangle(
            text_x, pill_y0, text_x + pill_w, pill_y0 + pill_h,
            fill=CARD_BG, outline=accent, width=1,
        )
        c.create_text(
            text_x + pill_w / 2, pill_y0 + pill_h / 2, text=pill_text,
            font=BADGE_FONT, fill=accent,
        )

        # arrow: double chevron, monospace, terminal-style
        c.create_text(arrow_x, thumb_y, text=">>", font=(MONO, 15, "bold"), fill=accent)

        c.create_image(after_x, thumb_y, image=self.after_photo)

        c.create_text(
            w - 14, 14, text="X", font=(MONO, 10, "bold"), fill=TEXT_MUTED, tags="remove", anchor="ne"
        )
        c.tag_bind("remove", "<Button-1>", lambda e: self.on_remove(self))

    def _on_click(self, _event):
        pass

    # ---- state updates -----------------------------------------------------

    def set_scanned(self, report):
        try:
            self.before_photo = _load_thumbnail(self.path)
        except Exception:
            pass
        self.summary = _short_metadata_summary(report)
        self.summary_color = WARNING if not report.is_empty else TEXT_MUTED
        self._redraw()

    def set_scan_error(self, exc):
        self.summary = f"couldn't read: {exc}"
        self.summary_color = DANGER
        self._redraw()

    def set_processing(self):
        self.state = "processing"
        self.status_text = "[ SCANNING... ]"
        self._redraw()

    def set_done(self, out_path: Path, after_report):
        try:
            self.after_photo = _load_thumbnail(out_path)
        except Exception:
            pass
        if after_report.is_empty:
            self.state = "done"
            self.status_text = "[ CLEAN ]"
        else:
            self.state = "warn"
            self.status_text = "[ PARTIAL ]"
        self._redraw()

    def set_failed(self, exc):
        self.state = "failed"
        self.status_text = "[ FAILED ]"
        self._redraw()

    def destroy(self):
        self.canvas.destroy()


class ScrollableCardList(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.canvas = tk.Canvas(self, bg=LIST_BG, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, bootstyle="round")
        self.inner = tk.Frame(self.canvas, bg=LIST_BG)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self._draw_scanlines()

        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    def _draw_scanlines(self):
        for y in range(0, 2000, 3):
            self.canvas.create_line(0, y, 4000, y, fill=SCANLINE, tags="scanline")
        self.canvas.tag_lower("scanline")

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self._window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class MetadataRemoverApp(ttk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE, themename="darkly", size=(960, 780), minsize=(780, 620))
        self.configure(bg=BG)
        self._setup_style()

        self.cards: dict[Path, ImageCard] = {}
        self.output_dir: Path | None = None

        self._build_widgets()

    def _setup_style(self):
        style = self.style
        style.configure("TButton", font=(MONO, 10, "bold"))
        style.configure("success.TButton", font=(MONO, 10, "bold"))

    # ---- UI construction -------------------------------------------------

    def _build_widgets(self):
        outer = tk.Frame(self, bg=BG, padx=22, pady=20)
        outer.pack(fill=BOTH, expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill=X, pady=(0, 16))
        tk.Label(header, text="> METADATA_REMOVER", font=TITLE_FONT, bg=BG, fg=GREEN).pack(anchor="w")
        tk.Label(
            header,
            text="// strip EXIF, GPS, and hidden metadata before you share a file",
            font=SUBTITLE_FONT,
            bg=BG,
            fg=TEXT_SECONDARY,
        ).pack(anchor="w", pady=(3, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill=X, pady=(0, 12))
        ttk.Button(actions, text="ADD IMAGES", command=self.add_files, bootstyle="success").pack(side=LEFT)
        ttk.Button(
            actions, text="ADD FOLDER", command=self.add_folder, bootstyle="success-outline"
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            actions, text="CLEAR", command=self.clear_files, bootstyle="secondary-outline"
        ).pack(side=LEFT, padx=(8, 0))

        out_frame = tk.Frame(outer, bg=BG)
        out_frame.pack(fill=X, pady=(0, 12))
        tk.Label(out_frame, text="OUTPUT:", font=BODY_FONT, bg=BG, fg=TEXT_PRIMARY).pack(side=LEFT)
        self.output_var = tk.StringVar(value="same folder as each original, with _clean suffix")
        tk.Label(out_frame, textvariable=self.output_var, font=BODY_FONT, bg=BG, fg=TEXT_SECONDARY).pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(
            out_frame, text="CHOOSE...", command=self.choose_output_dir, bootstyle="secondary-outline"
        ).pack(side=RIGHT)

        action_frame = ttk.Frame(outer)
        action_frame.pack(fill=X, pady=(0, 6))
        self.remove_button = ttk.Button(
            action_frame,
            text="REMOVE METADATA FROM ALL",
            command=self.run_stripping,
            bootstyle="success",
            padding=(18, 11),
        )
        self.remove_button.pack(side=LEFT)
        self.progress = ttk.Progressbar(action_frame, mode="determinate", bootstyle="success-striped")
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(16, 0))

        status_frame = tk.Frame(outer, bg=BG)
        status_frame.pack(fill=X, pady=(4, 16))
        self.status_var = tk.StringVar(value="> ready")
        self.status_label = tk.Label(
            status_frame, textvariable=self.status_var, font=(MONO, 10, "bold"), bg=BG, fg=TEXT_SECONDARY
        )
        self.status_label.pack(anchor="w")

        tk.Label(outer, text="// IMAGES", font=(MONO, 10, "bold"), bg=BG, fg=TEXT_MUTED).pack(
            anchor="w", pady=(0, 8)
        )

        self.card_list = ScrollableCardList(outer)
        self.card_list.pack(fill=BOTH, expand=True)

        self.empty_hint = tk.Label(
            self.card_list.inner,
            text="// add images to scan for metadata",
            font=BODY_FONT,
            bg=LIST_BG,
            fg=TEXT_MUTED,
        )
        self.empty_hint.pack(pady=50)

    # ---- file selection -----------------------------------------------

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select images",
            filetypes=[
                ("Image files", " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))),
                ("All files", "*.*"),
            ],
        )
        for p in paths:
            self._add_path(Path(p))

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select a folder of images")
        if not folder:
            return
        for entry in sorted(Path(folder).iterdir()):
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                self._add_path(entry)

    def _add_path(self, path: Path):
        if path in self.cards:
            return
        self.empty_hint.pack_forget()
        card = ImageCard(self.card_list.inner, path, on_remove=self._remove_card)
        self.cards[path] = card
        try:
            report = inspect_metadata(path)
            card.set_scanned(report)
        except Exception as exc:
            card.set_scan_error(exc)
        self.status_var.set(f"> {len(self.cards)} image(s) queued")

    def _remove_card(self, card: ImageCard):
        card.destroy()
        self.cards.pop(card.path, None)
        if not self.cards:
            self.empty_hint.pack(pady=50)
            self.status_var.set("> ready")
        else:
            self.status_var.set(f"> {len(self.cards)} image(s) queued")

    def clear_files(self):
        for card in list(self.cards.values()):
            card.destroy()
        self.cards.clear()
        self.empty_hint.pack(pady=50)
        self.status_var.set("> ready")

    def choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir = Path(folder)
            self.output_var.set(str(self.output_dir))

    # ---- stripping --------------------------------------------------------

    def run_stripping(self):
        if not self.cards:
            self.status_var.set("> add at least one image first")
            self.status_label.config(fg=WARNING)
            return

        self.remove_button.config(state="disabled")
        self.progress.config(maximum=len(self.cards), value=0)
        self.status_label.config(fg=CYAN)

        thread = threading.Thread(target=self._strip_all, daemon=True)
        thread.start()

    def _strip_all(self):
        succeeded = 0
        total = len(self.cards)
        done_count = 0
        for path, card in list(self.cards.items()):
            self.after(0, card.set_processing)
            done_count += 1
            self.after(0, self.status_var.set, f"> removing metadata... ({done_count}/{total})")
            out_path = self.output_dir / path.name if self.output_dir else default_output_path(path)
            try:
                strip_metadata(path, out_path)
                after_report = inspect_metadata(out_path)
                self.after(0, card.set_done, out_path, after_report)
                succeeded += 1
            except Exception as exc:
                self.after(0, card.set_failed, exc)
            finally:
                self.after(0, self.progress.step, 1)

        self.after(0, self._finish, succeeded, total)

    def _finish(self, succeeded: int, total: int):
        self.remove_button.config(state="normal")
        if succeeded == total:
            self.status_var.set(f"> done: {succeeded}/{total} cleaned")
            self.status_label.config(fg=GREEN)
        else:
            self.status_var.set(f"> done: {succeeded}/{total} cleaned, {total - succeeded} failed")
            self.status_label.config(fg=WARNING)


def main():
    app = MetadataRemoverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
