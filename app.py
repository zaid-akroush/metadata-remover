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
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from PIL import Image, ImageTk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y

from core import SUPPORTED_EXTENSIONS, default_output_path, inspect_metadata, strip_metadata

APP_TITLE = "Metadata Remover"

TITLE_FONT = ("Segoe UI", 20, "bold")
BODY_FONT = ("Segoe UI", 10)
SMALL_FONT = ("Segoe UI", 9)
MONO_FONT = ("Consolas", 9)

CARD_BG = "#20242c"
CARD_BORDER = "#333844"
THUMB_BG = "#14161b"
THUMB_SIZE = (96, 96)


def _load_thumbnail(path: Path, size=THUMB_SIZE) -> ImageTk.PhotoImage:
    """Return a PhotoImage thumbnail, letterboxed onto a fixed-size dark tile
    so every card lines up regardless of the source image's aspect ratio."""
    tile = Image.new("RGB", size, THUMB_BG)
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail(size)
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        tile.paste(img, offset)
    return ImageTk.PhotoImage(tile)


def _placeholder_thumbnail(size=THUMB_SIZE) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(Image.new("RGB", size, THUMB_BG))


def _short_metadata_summary(report) -> str:
    if report.is_empty:
        return "No metadata found"
    parts = list(report.exif_tags.keys())[:3]
    extra = report.exif_tags and len(report.exif_tags) > 3
    text = ", ".join(parts)
    remaining = len(report.exif_tags) - len(parts) + len(report.info_keys)
    if remaining > 0:
        text += f" +{remaining} more" if text else f"{remaining} field(s)"
    return text or "Metadata present"


class ImageCard:
    """A single row: before-thumbnail | filename + metadata summary | arrow |
    after-thumbnail + status. Keeps its own PhotoImage references alive
    (Tk garbage-collects images with no surviving Python reference)."""

    def __init__(self, parent, path: Path, on_remove):
        self.path = path
        self.on_remove = on_remove

        self.frame = tk.Frame(parent, bg=CARD_BG, highlightbackground=CARD_BORDER, highlightthickness=1)
        self.frame.pack(fill=X, pady=5, padx=2)

        pad = dict(padx=10, pady=10)

        self.before_photo = _placeholder_thumbnail()
        self.before_label = tk.Label(self.frame, image=self.before_photo, bg=THUMB_BG, bd=0)
        self.before_label.grid(row=0, column=0, rowspan=2, **pad)

        info = tk.Frame(self.frame, bg=CARD_BG)
        info.grid(row=0, column=1, rowspan=2, sticky="w", pady=10)

        self.name_label = tk.Label(
            info, text=path.name, font=BODY_FONT, bg=CARD_BG, fg="#f0f0f0", anchor="w"
        )
        self.name_label.pack(anchor="w")

        self.meta_label = tk.Label(
            info, text="Scanning...", font=SMALL_FONT, bg=CARD_BG, fg="#a8adb8", anchor="w", justify="left"
        )
        self.meta_label.pack(anchor="w", pady=(2, 0))

        self.status_label = tk.Label(
            info, text="Not processed yet", font=SMALL_FONT, bg=CARD_BG, fg="#7a8094", anchor="w"
        )
        self.status_label.pack(anchor="w", pady=(2, 0))

        self.arrow_label = tk.Label(
            self.frame, text="→", font=("Segoe UI", 22), bg=CARD_BG, fg="#4a4f5c"
        )
        self.arrow_label.grid(row=0, column=2, rowspan=2, padx=6)

        self.after_photo = _placeholder_thumbnail()
        self.after_label = tk.Label(self.frame, image=self.after_photo, bg=THUMB_BG, bd=0)
        self.after_label.grid(row=0, column=3, rowspan=2, **pad)

        remove_btn = tk.Label(
            self.frame, text="✕", font=("Segoe UI", 11), bg=CARD_BG, fg="#7a8094", cursor="hand2"
        )
        remove_btn.grid(row=0, column=4, sticky="ne", padx=(0, 10), pady=(8, 0))
        remove_btn.bind("<Button-1>", lambda _e: self.on_remove(self))
        remove_btn.bind("<Enter>", lambda _e: remove_btn.config(fg="#e0554f"))
        remove_btn.bind("<Leave>", lambda _e: remove_btn.config(fg="#7a8094"))

        self.frame.grid_columnconfigure(1, weight=1)

    def set_scanned(self, report):
        try:
            self.before_photo = _load_thumbnail(self.path)
            self.before_label.config(image=self.before_photo)
        except Exception:
            pass
        self.meta_label.config(
            text=_short_metadata_summary(report),
            fg="#e0b03e" if not report.is_empty else "#7a8094",
        )
        self._report = report

    def set_scan_error(self, exc):
        self.meta_label.config(text=f"Couldn't read: {exc}", fg="#e0554f")

    def set_processing(self):
        self.status_label.config(text="Processing...", fg="#5aa9e6")

    def set_done(self, out_path: Path, after_report):
        try:
            self.after_photo = _load_thumbnail(out_path)
            self.after_label.config(image=self.after_photo)
        except Exception:
            pass
        self.arrow_label.config(fg="#4fd17a")
        if after_report.is_empty:
            self.status_label.config(text=f"Clean -> {out_path.name}", fg="#4fd17a")
        else:
            self.status_label.config(text="Some metadata may remain", fg="#e0b03e")

    def set_failed(self, exc):
        self.status_label.config(text=f"Failed: {exc}", fg="#e0554f")
        self.arrow_label.config(fg="#e0554f")

    def destroy(self):
        self.frame.destroy()


class ScrollableCardList(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        self.canvas = tk.Canvas(self, bg="#181a1f", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, bootstyle="round")
        self.inner = tk.Frame(self.canvas, bg="#181a1f")

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self._window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class MetadataRemoverApp(ttk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE, themename="darkly", size=(920, 760), minsize=(760, 620))

        self.cards: dict[Path, ImageCard] = {}
        self.output_dir: Path | None = None

        self._build_widgets()

    # ---- UI construction -------------------------------------------------

    def _build_widgets(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill=BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 14))
        ttk.Label(header, text="Metadata Remover", font=TITLE_FONT, bootstyle="light").pack(anchor="w")
        ttk.Label(
            header,
            text="Strip EXIF, GPS, and hidden metadata from your photos before you share them.",
            font=BODY_FONT,
            bootstyle="secondary",
        ).pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill=X, pady=(0, 10))
        ttk.Button(actions, text="Add Images...", command=self.add_files, bootstyle="info").pack(side=LEFT)
        ttk.Button(
            actions, text="Add Folder...", command=self.add_folder, bootstyle="info-outline"
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            actions, text="Clear List", command=self.clear_files, bootstyle="secondary-outline"
        ).pack(side=LEFT, padx=(8, 0))

        out_frame = ttk.Frame(outer)
        out_frame.pack(fill=X, pady=(0, 10))
        ttk.Label(out_frame, text="Output folder:", font=BODY_FONT, bootstyle="light").pack(side=LEFT)
        self.output_var = tk.StringVar(value="same folder as each original, with _clean suffix")
        ttk.Label(out_frame, textvariable=self.output_var, font=BODY_FONT, bootstyle="secondary").pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(
            out_frame, text="Choose...", command=self.choose_output_dir, bootstyle="secondary-outline"
        ).pack(side=RIGHT)

        action_frame = ttk.Frame(outer)
        action_frame.pack(fill=X, pady=(0, 12))
        self.remove_button = ttk.Button(
            action_frame,
            text="Remove Metadata From All",
            command=self.run_stripping,
            bootstyle="success",
            padding=(16, 10),
        )
        self.remove_button.pack(side=LEFT)
        self.progress = ttk.Progressbar(action_frame, mode="determinate", bootstyle="success-striped")
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(14, 0))

        list_label = ttk.Label(outer, text="Images", font=("Segoe UI", 11, "bold"), bootstyle="light")
        list_label.pack(anchor="w", pady=(0, 6))

        self.card_list = ScrollableCardList(outer)
        self.card_list.pack(fill=BOTH, expand=True)

        self.empty_hint = tk.Label(
            self.card_list.inner,
            text="Add images to see their metadata here.",
            font=BODY_FONT,
            bg="#181a1f",
            fg="#5a5f6c",
        )
        self.empty_hint.pack(pady=40)

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

    def _remove_card(self, card: ImageCard):
        card.destroy()
        self.cards.pop(card.path, None)
        if not self.cards:
            self.empty_hint.pack(pady=40)

    def clear_files(self):
        for card in list(self.cards.values()):
            card.destroy()
        self.cards.clear()
        self.empty_hint.pack(pady=40)

    def choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir = Path(folder)
            self.output_var.set(str(self.output_dir))

    # ---- stripping --------------------------------------------------------

    def run_stripping(self):
        if not self.cards:
            messagebox.showinfo(APP_TITLE, "Add at least one image first.")
            return

        self.remove_button.config(state="disabled")
        self.progress.config(maximum=len(self.cards), value=0)

        thread = threading.Thread(target=self._strip_all, daemon=True)
        thread.start()

    def _strip_all(self):
        succeeded = 0
        for path, card in list(self.cards.items()):
            self.after(0, card.set_processing)
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

        self.after(0, self._finish, succeeded, len(self.cards))

    def _finish(self, succeeded: int, total: int):
        self.remove_button.config(state="normal")
        messagebox.showinfo(APP_TITLE, f"Done: {succeeded}/{total} image(s) processed.")


def main():
    app = MetadataRemoverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
