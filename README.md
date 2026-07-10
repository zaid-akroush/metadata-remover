# Metadata Remover

A small desktop app that strips EXIF, GPS, camera info, comments, and
other embedded metadata from images before you share them.

## What it removes

- EXIF tags: camera make/model, timestamps, GPS location, orientation,
  software used, and everything else stored in the EXIF block
- PNG text chunks (comments, author fields, software tags)
- ICC color profiles and any other embedded extras

It does **not** touch or report on the JPEG/PNG format's own mandatory
structural fields (like the JFIF density marker) since those aren't
personal data and can't meaningfully be "removed" without breaking the
file format itself.

## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python app.py
```

On Windows and macOS, tkinter (the GUI toolkit) ships with the standard
Python installer, so no extra install is needed there. On Linux, install
your distro's `python3-tk` package if `import tkinter` fails.

The UI is styled with [ttkbootstrap](https://ttkbootstrap.readthedocs.io/)
(dark theme), installed automatically via `requirements.txt`.

## Usage

1. **Add Images...** or **Add Folder...** to select one or more images.
   Each one appears as a card showing a thumbnail and a summary of the
   metadata found on it (or "No metadata found" if it's already clean).
2. Optionally **Choose...** an output folder (default: saves next to
   each original with a `_clean` suffix, so your originals are never
   overwritten).
3. **Remove Metadata From All**. Each card updates live: the arrow
   between the before/after thumbnails turns green, an after-thumbnail
   appears next to it, and the status line confirms the output filename
   (or shows an error if that specific file failed).

Supported formats: JPEG, PNG, BMP, TIFF, WEBP.

## How it works

Rather than trying to selectively delete known metadata fields (which
misses whatever field you didn't think to check for), the app rebuilds
each image from nothing but its decoded pixel data. The new image object
has no `.info` dict and no EXIF block to write out, so the saved copy is
clean regardless of what the original camera, phone, or editing app
embedded in it. JPEGs are re-saved at quality 95 to keep visual quality
close to the original while still fully re-encoding (which is what
actually drops the metadata for that format).

## Tests

Core stripping/inspection logic (`core.py`) is covered by 9 pytest tests
independent of the GUI, including a case that specifically injects EXIF
+ GPS-adjacent tags and PNG text chunks and verifies they're gone after
processing, plus a pixel-preservation check and a palette-mode (indexed
PNG) case.

```bash
pip install pytest
pytest tests/ -v
```

## Building a standalone .exe

Double-click `build_exe.bat` (Windows only). It installs PyInst