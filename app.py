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
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y

from core import SUPPORTED_EXTENSIONS, default_output_path, inspect_metadata, strip_metadata

APP_TITLE = "Metadata Remover"

BODY_FONT = ("Segoe UI", 10)
MONO_FONT = ("Consolas", 9)

DARK_PANEL_BG = "#1f2229"
DARK_PANEL_FG = "#e6e6e6"
DARK_PANEL_SELECT = "#2f6f4f"


class MetadataRemoverApp(ttk.Window):
    def __init__(self):
        super().__init__(title=APP_TITLE, themename="darkly", size=(860, 760), minsize=(700, 620))

        self.files: list[Path] = []
        self.output_dir: Path | None = None

        self._build_widgets()

    # ---- UI construction -------------------------------------------------

    def _build_widgets(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill=BOTH, expand=True)

        # ---- Header ----
        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 14))

        ttk.Label(
            header, text="Metadata Remover", font=("Segoe UI", 20, "bold"), bootstyle="light"
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Strip EXIF, GPS, and hidden metadata from your photos before you share them.",
            font=BODY_FONT,
            bootstyle="secondary",
        ).pack(anchor="w", pady=(2, 0))

        # ---- File action buttons ----
        actions = ttk.Frame(outer)
        actions.pack(fill=X, pady=(0, 10))

        ttk.Button(actions, text="Add Images...", command=self.add_files, bootstyle="info").pack(
            side=LEFT
        )
        ttk.Button(
            actions, text="Add Folder...", command=self.add_folder, bootstyle="info-outline"
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            actions, text="Clear List", command=self.clear_files, bootstyle="secondary-outline"
        ).pack(side=LEFT, padx=(8, 0))

        # ---- Middle: file list + metadata preview ----
        mid = ttk.Frame(outer)
        mid.pack(fill=BOTH, expand=True, pady=(0, 10))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(0, weight=1)

        list_card = ttk.Labelframe(mid, text="Selected images", padding=8, bootstyle="info")
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        list_card.rowconfigure(0, weight=1)
        list_card.columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_card,
            selectmode="extended",
            bg=DARK_PANEL_BG,
            fg=DARK_PANEL_FG,
            selectbackground=DARK_PANEL_SELECT,
            selectforeground="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            font=BODY_FONT,
            activestyle="none",
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        list_scroll = ttk.Scrollbar(list_card, orient="vertical", command=self.listbox.yview, bootstyle="round")
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=list_scroll.set)

        preview_card = ttk.Labelframe(mid, text="Metadata found", padding=8, bootstyle="info")
        preview_card.grid(row=0, column=1, sticky="nsew")
        preview_card.rowconfigure(0, weight=1)
        preview_card.columnconfigure(0, weight=1)

        self.preview_text = tk.Text(
            preview_card,
            wrap="word",
            state="disabled",
            bg=DARK_PANEL_BG,
            fg=DARK_PANEL_FG,
            insertbackground=DARK_PANEL_FG,
            highlightthickness=0,
            borderwidth=0,
            font=MONO_FONT,
            padx=8,
            pady=6,
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")

        # ---- Output folder ----
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

        # ---- Main action ----
        action_frame = ttk.Frame(outer)
        action_frame.pack(fill=X, pady=(0, 10))

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

        # ---- Log ----
        log_card = ttk.Labelframe(outer, text="Log", padding=8, bootstyle="secondary")
        log_card.pack(fill=BOTH, expand=False)

        self.log_text = tk.Text(
            log_card,
            wrap="word",
            state="disabled",
            height=7,
            bg=DARK_PANEL_BG,
            fg=DARK_PANEL_FG,
            insertbackground=DARK_PANEL_FG,
            highlightthickness=0,
            borderwidth=0,
            font=MONO_FONT,
            padx=8,
            pady=6,
        )
        self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.tag_configure("ok", foreground="#4fd17a")
        self.log_text.tag_configure("warn", foreground="#e0b03e")
        self.log_text.tag_configure("fail", foreground="#e0554f")

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
        if path not in self.files:
            self.files.append(path)
            self.listbox.insert("end", str(path))

    def clear_files(self):
        self.files.clear()
        self.listbox.delete(0, "end")
        self._set_preview("")

    def choose_output_dir(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.output_dir = Path(folder)
            self.output_var.set(str(self.output_dir))

    # ---- metadata preview -----------------------------------------------

    def _on_select(self, _event):
        selection = self.listbox.curselection()
        if not selection:
            return
        path = self.files[selection[0]]
        try:
            report = inspect_metadata(path)
            self._set_preview(f"{path.name}\n\n{report.describe()}")
        except Exception as exc:
            self._set_preview(f"{path.name}\n\nCouldn't read metadata: {exc}")

    def _set_preview(self, text: str):
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", text)
        self.preview_text.config(state="disabled")

    # ---- stripping --------------------------------------------------------

    def run_stripping(self):
        if not self.files:
            messagebox.showinfo(APP_TITLE, "Add at least one image first.")
            return

        self.remove_button.config(state="disabled")
        self.progress.config(maximum=len(self.files), value=0)
        self._log_clear()

        thread = threading.Thread(target=self._strip_all, daemon=True)
        thread.start()

    def _strip_all(self):
        succeeded = 0
        for path in self.files:
            out_path = (
                self.output_dir / path.name if self.output_dir else default_output_path(path)
            )
            try:
                before = inspect_metadata(path)
                strip_metadata(path, out_path)
                after = inspect_metadata(out_path)
                if before.is_empty:
                    self._log(f"OK    {path.name}: no metadata found, saved clean copy anyway", "ok")
                else:
                    removed = len(before.exif_tags) + len(before.info_keys)
                    self._log(
                        f"OK    {path.name}: removed {removed} metadata field(s) -> {out_path.name}",
                        "ok",
                    )
                if not after.is_empty:
                    self._log(f"WARN  {path.name}: some metadata may remain: {after.describe()}", "warn")
                succeeded += 1
            except Exception as exc:
                self._log(f"FAIL  {path.name}: {exc}", "fail")
            finally:
                self.after(0, self.progress.step, 1)

        self.after(0, self._finish, succeeded, len(self.files))

    def _finish(self, succeeded: int, total: int):
        self.remove_button.config(state="normal")
        messagebox.showinfo(APP_TITLE, f"Done: {succeeded}/{total} image(s) processed.")

    def _log_clear(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _log(self, line: str, tag: str):
        def append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n", tag)
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        self.after(0, append)


def main():
    app = MetadataRemoverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
