import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from PIL.PngImagePlugin import PngInfo

import core


def make_jpeg_with_exif(path: Path):
    img = Image.new("RGB", (40, 30), color=(200, 50, 50))

    exif = img.getexif()
    exif[0x010F] = "TestCamera Inc."      # Make
    exif[0x0110] = "Model X"              # Model
    exif[0x0132] = "2026:01:01 12:00:00"  # DateTime
    exif[0x9286] = "field test comment"   # UserComment

    img.save(path, format="JPEG", exif=exif, quality=90)


def make_png_with_text(path: Path):
    img = Image.new("RGB", (40, 30), color=(50, 200, 50))
    info = PngInfo()
    info.add_text("Comment", "made in a totally real camera app")
    info.add_text("Author", "Jane Doe")
    img.save(path, format="PNG", pnginfo=info)


def test_inspect_metadata_finds_exif_tags(tmp_path):
    p = tmp_path / "photo.jpg"
    make_jpeg_with_exif(p)

    report = core.inspect_metadata(p)

    assert not report.is_empty
    assert "Make" in report.exif_tags
    assert report.exif_tags["Make"] == "TestCamera Inc."
    assert report.exif_tags["Model"] == "Model X"


def test_inspect_metadata_finds_png_text_chunks(tmp_path):
    p = tmp_path / "graphic.png"
    make_png_with_text(p)

    report = core.inspect_metadata(p)

    assert not report.is_empty
    assert "Comment" in report.info_keys
    assert "Author" in report.info_keys


def test_inspect_metadata_clean_image_reports_empty(tmp_path):
    p = tmp_path / "plain.png"
    Image.new("RGB", (10, 10), color="blue").save(p, format="PNG")

    report = core.inspect_metadata(p)

    assert report.is_empty


def test_strip_metadata_removes_jpeg_exif(tmp_path):
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_clean.jpg"
    make_jpeg_with_exif(src)

    assert not core.inspect_metadata(src).is_empty

    core.strip_metadata(src, out)

    report = core.inspect_metadata(out)
    assert report.is_empty, f"expected no metadata, found: {report.describe()}"


def test_strip_metadata_removes_png_text_chunks(tmp_path):
    src = tmp_path / "graphic.png"
    out = tmp_path / "graphic_clean.png"
    make_png_with_text(src)

    assert not core.inspect_metadata(src).is_empty

    core.strip_metadata(src, out)

    report = core.inspect_metadata(out)
    assert report.is_empty, f"expected no metadata, found: {report.describe()}"


def test_strip_metadata_preserves_pixel_data(tmp_path):
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_clean.jpg"
    make_jpeg_with_exif(src)

    core.strip_metadata(src, out)

    with Image.open(src) as original, Image.open(out) as cleaned:
        assert original.size == cleaned.size
        assert original.mode == cleaned.mode
        # allow small JPEG re-encoding difference, but colors should be close
        orig_px = original.convert("RGB").getpixel((5, 5))
        clean_px = cleaned.convert("RGB").getpixel((5, 5))
        for o, c in zip(orig_px, clean_px):
            assert abs(o - c) < 15, f"pixel drifted too much: {orig_px} vs {clean_px}"


def test_strip_metadata_preserves_palette_mode(tmp_path):
    src = tmp_path / "sprite.png"
    out = tmp_path / "sprite_clean.png"

    img = Image.new("P", (20, 20))
    img.putpalette([i % 256 for i in range(768)])
    for x in range(20):
        for y in range(20):
            img.putpixel((x, y), (x + y) % 256)
    img.save(src, format="PNG")

    core.strip_metadata(src, out)

    with Image.open(out) as cleaned:
        assert cleaned.mode == "P"
        assert cleaned.getpixel((5, 5)) == img.getpixel((5, 5))


def test_default_output_path_adds_clean_suffix():
    result = core.default_output_path("/some/dir/photo.jpg")
    assert result.name == "photo_clean.jpg"


def test_supported_extensions_cover_common_formats():
    for ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"]:
        assert ext in core.SUPPORTED_EXTENSIONS
