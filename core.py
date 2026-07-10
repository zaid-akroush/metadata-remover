"""
Core metadata-stripping logic, kept separate from the GUI so it's easy to
unit test headlessly (no display required) and reusable from a script.

Strategy: rebuild the image from raw pixel data only. PIL's Image.open()
keeps EXIF/IPTC/XMP/ICC-profile/comment data attached to the returned
Image object (in .info and via .getexif()). By constructing a brand new
Image from nothing but the decoded pixels -- and never copying over
.info or the exif block -- the new object simply has no metadata to
write out, regardless of what the original file contained.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ExifTags

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

# Structural fields PIL's own encoder writes into every JPEG/PNG it produces
# (density units, JFIF version, etc). These aren't privacy-sensitive and
# can't meaningfully be "removed" -- they're part of the container format,
# not attached metadata -- so they're excluded from what counts as
# metadata for reporting/verification purposes.
_BENIGN_INFO_KEYS = {"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi"}


@dataclass
class MetadataReport:
    exif_tags: dict = field(default_factory=dict)
    info_keys: list = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.exif_tags and not self.info_keys

    def describe(self) -> str:
        if self.is_empty:
            return "No metadata found."
        lines = []
        if self.exif_tags:
            lines.append(f"EXIF tags ({len(self.exif_tags)}):")
            for name, value in self.exif_tags.items():
                lines.append(f"  {name}: {value}")
        if self.info_keys:
            lines.append(f"Other embedded info: {', '.join(self.info_keys)}")
        return "\n".join(lines)


def inspect_metadata(path: str | Path) -> MetadataReport:
    """Return a human-readable summary of what metadata a file currently has."""
    with Image.open(path) as img:
        exif_tags = {}
        try:
            exif = img.getexif()
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                exif_tags[name] = value
        except Exception:
            pass

        # img.info carries format-specific extras: PNG text chunks, ICC
        # profiles, DPI, comments, etc. -- report the keys, not raw values
        # (some, like icc_profile, are large binary blobs).
        info_keys = [
            k for k in img.info.keys()
            if k != "exif" and k not in _BENIGN_INFO_KEYS
        ]

        return MetadataReport(exif_tags=exif_tags, info_keys=info_keys)


def strip_metadata(input_path: str | Path, output_path: str | Path) -> None:
    """Write a metadata-free copy of the image at input_path to output_path."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    with Image.open(input_path) as img:
        img.load()
        mode = img.mode
        size = img.size
        data = list(img.getdata())
        fmt = img.format or _format_from_extension(output_path)

        clean = Image.new(mode, size)
        clean.putdata(data)
        if mode == "P":
            palette = img.getpalette()
            if palette is not None:
                clean.putpalette(palette)

        save_kwargs = {}
        if fmt == "JPEG":
            # Default PIL JPEG quality (75) visibly degrades photos; 95 is
            # close to source quality while still re-encoding (which is
            # what actually drops the metadata for JPEG).
            save_kwargs["quality"] = 95
            save_kwargs["optimize"] = True

        clean.save(output_path, format=fmt, **save_kwargs)


def _format_from_extension(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "JPEG", ".jpeg": "JPEG",
        ".png": "PNG",
        ".bmp": "BMP",
        ".tiff": "TIFF", ".tif": "TIFF",
        ".webp": "WEBP",
    }.get(ext, "PNG")


def default_output_path(input_path: str | Path) -> Path:
    input_path = Path(input_path)
    return input_path.with_name(f"{input_path.stem}_clean{input_path.suffix}")
