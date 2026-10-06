from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from phomemo.raster import DITHERS, image_to_raster, raster_to_image, stripe_raster
from phomemo.text import text_to_image

OUT = Path(__file__).parent / "output"


def test_all_black_8x1():
    r = image_to_raster(Image.new("L", (8, 1), 0), width_px=8, dither="threshold")
    assert (r.width_px, r.height_px, r.data) == (8, 1, b"\xff")


def test_left_pixel_black_is_msb():
    img = Image.new("L", (8, 1), 255)
    img.putpixel((0, 0), 0)
    assert image_to_raster(img, 8, "threshold").data == b"\x80"


def test_all_white():
    assert image_to_raster(Image.new("L", (16, 2), 255), 16, "threshold").data == b"\x00" * 4


@pytest.mark.parametrize("dither", DITHERS)
def test_roundtrip_binary_image(dither):
    img = Image.new("1", (384, 40), 1)
    d = ImageDraw.Draw(img)
    d.rectangle((10, 5, 100, 30), fill=0)
    d.line((0, 0, 383, 39), fill=0)
    r = image_to_raster(img, 384, dither)
    back = raster_to_image(r)
    assert back.size == img.size
    assert back.tobytes() == img.tobytes()


def test_resize_keeps_aspect():
    r = image_to_raster(Image.new("RGB", (100, 50), "white"), 384)
    assert (r.width_px, r.height_px) == (384, 192)
    assert len(r.data) == 48 * 192


def test_non_multiple_of_8_input_width():
    r = image_to_raster(Image.new("L", (13, 13), 0), 384, "threshold")
    assert r.width_px == 384 and len(r.data) == 48 * r.height_px


def test_very_tall_image():
    r = image_to_raster(Image.new("L", (10, 5000), 0), 384, "threshold")
    assert r.height_px == 192000
    assert r.data == b"\xff" * (48 * r.height_px)


def test_transparent_png_becomes_white():
    img = Image.new("RGBA", (384, 10), (0, 0, 0, 0))  # fully transparent black
    img.putpixel((0, 0), (0, 0, 0, 255))
    r = image_to_raster(img, 384, "threshold")
    assert r.data[0] == 0x80
    assert r.data[1:] == bytes(len(r.data) - 1)


def test_width_must_be_multiple_of_8():
    with pytest.raises(ValueError):
        image_to_raster(Image.new("L", (10, 10)), 100)
    with pytest.raises(ValueError):
        image_to_raster(Image.new("L", (10, 10)), 384, dither="nope")


def test_stripe_raster():
    r = stripe_raster(16, 4, period=1)
    assert r.data == b"\xff\xff\x00\x00\xff\xff\x00\x00"


def test_text_renders_japanese():
    img = text_to_image("乾杯!", 384, font_size=48)
    r = image_to_raster(img, 384, "threshold")
    assert img.width == 384
    assert any(r.data)  # something got drawn


def test_text_wraps():
    one = text_to_image("あ", 384, font_size=48)
    many = text_to_image("あ" * 30, 384, font_size=48)
    assert many.height > one.height
    assert many.width == 384


def test_write_previews():
    """Not an assertion test: writes dither comparisons to tests/output/."""
    OUT.mkdir(exist_ok=True)
    grad = Image.linear_gradient("L").resize((384, 120))
    for d in DITHERS:
        raster_to_image(image_to_raster(grad, 384, d)).save(OUT / f"gradient_{d}.png")
    raster_to_image(image_to_raster(text_to_image("乾杯!\nPhomemo M02"), 384, "threshold")) \
        .save(OUT / "text.png")
