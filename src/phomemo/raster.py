"""Image -> 1-bit raster conversion for the M02 (pure logic, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageOps

DITHERS = ("floyd", "threshold", "atkinson")


@dataclass
class Raster:
    width_px: int  # multiple of 8. M02 is 384
    height_px: int
    data: bytes  # one row = width_px // 8 bytes, MSB is leftmost, 1 = black

    @property
    def width_bytes(self) -> int:
        return self.width_px // 8


def _flatten_to_gray(img: Image.Image) -> Image.Image:
    """Composite transparency onto white, then convert to 8-bit grayscale."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    return img.convert("L")


def _atkinson(gray: Image.Image) -> Image.Image:
    """Atkinson dither -> mode "L" image with only 0/255 values."""
    w, h = gray.size
    px = [float(v) for v in gray.tobytes()]
    # (dx, dy) neighbours each receive 1/8 of the error
    spread = ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2))
    for y in range(h):
        row = y * w
        for x in range(w):
            old = px[row + x]
            new = 255.0 if old >= 128 else 0.0
            px[row + x] = new
            err = (old - new) / 8
            if not err:
                continue
            for dx, dy in spread:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and ny < h:
                    px[ny * w + nx] += err
    out = Image.new("L", (w, h))
    out.frombytes(bytes(255 if v >= 128 else 0 for v in px))
    return out


def _binarize(gray: Image.Image, dither: str, threshold: int) -> Image.Image:
    """Return a mode "L" image containing only 0 (black) / 255 (white)."""
    if dither == "threshold":
        return gray.point(lambda v: 255 if v >= threshold else 0)
    if dither == "floyd":
        return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    if dither == "atkinson":
        return _atkinson(gray)
    raise ValueError(f"unknown dither {dither!r}; choose from {DITHERS}")


def _pack(bw: Image.Image) -> bytes:
    """Pack a 0/255 "L" image into rows of bytes, MSB left, 1 = black."""
    w, h = bw.size
    width_bytes = w // 8
    src = bw.tobytes()
    out = bytearray(width_bytes * h)
    i = 0
    for y in range(h):
        row = src[y * w:(y + 1) * w]
        for bx in range(width_bytes):
            byte = 0
            chunk = row[bx * 8:bx * 8 + 8]
            for bit, v in enumerate(chunk):
                if v < 128:
                    byte |= 0x80 >> bit
            out[i] = byte
            i += 1
    return bytes(out)


def image_to_raster(img: Image.Image, width_px: int = 384,
                    dither: str = "floyd", threshold: int = 128, *,
                    contrast: float = 1.0, gamma: float = 1.0,
                    invert: bool = False) -> Raster:
    """Resize to `width_px` keeping aspect ratio, binarize and pack."""
    if width_px <= 0 or width_px % 8:
        raise ValueError("width_px must be a positive multiple of 8")
    if dither not in DITHERS:
        raise ValueError(f"unknown dither {dither!r}; choose from {DITHERS}")

    gray = _flatten_to_gray(img)
    if gray.width != width_px:
        height = max(1, round(gray.height * width_px / gray.width))
        gray = gray.resize((width_px, height), Image.Resampling.LANCZOS)
    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
    if gamma != 1.0:
        lut = [round(255 * (v / 255) ** gamma) for v in range(256)]
        gray = gray.point(lut)
    if invert:
        gray = ImageOps.invert(gray)

    bw = _binarize(gray, dither, threshold)
    return Raster(width_px=width_px, height_px=bw.height, data=_pack(bw))


def raster_to_image(raster: Raster) -> Image.Image:
    """Inverse of packing, for --preview. Returns a mode "1" image."""
    # PIL "1" raw: 1 = white, so invert our 1 = black convention
    inverted = bytes(b ^ 0xFF for b in raster.data)
    return Image.frombytes("1", (raster.width_px, raster.height_px), inverted)


def solid_raster(width_px: int = 384, height_px: int = 50) -> Raster:
    """All-black test pattern."""
    return Raster(width_px, height_px, b"\xff" * (width_px // 8 * height_px))


def stripe_raster(width_px: int = 384, height_px: int = 50, period: int = 10) -> Raster:
    """Horizontal stripes: `period` black rows then `period` white rows."""
    wb = width_px // 8
    rows = bytearray()
    for y in range(height_px):
        rows += (b"\xff" if (y // period) % 2 == 0 else b"\x00") * wb
    return Raster(width_px, height_px, bytes(rows))
