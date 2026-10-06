"""Text -> PIL image (pure logic, no I/O apart from loading the font)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# macOS bundled Hiragino Kaku Gothic, heaviest first (thermal print likes bold)
FONT_CANDIDATES = (
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)

ALIGNS = ("left", "center", "right")


def find_font(path: str | None = None) -> str:
    if path:
        if not Path(path).exists():
            raise FileNotFoundError(f"font not found: {path}")
        return path
    for cand in FONT_CANDIDATES:
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("no Japanese font found; pass --font /path/to/font")


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Character-level wrap (works for Japanese, which has no spaces)."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for ch in para:
            if cur and font.getlength(cur + ch) > max_width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def text_to_image(text: str, width_px: int = 384, font_size: int = 48,
                  font_path: str | None = None, align: str = "center",
                  margin: int = 8, line_spacing: float = 1.2) -> Image.Image:
    """Render `text` black-on-white, wrapped to `width_px`. Returns mode "L"."""
    if align not in ALIGNS:
        raise ValueError(f"align must be one of {ALIGNS}")
    font = ImageFont.truetype(find_font(font_path), font_size)
    inner = width_px - 2 * margin
    lines = _wrap(text, font, inner)

    ascent, descent = font.getmetrics()
    line_h = round((ascent + descent) * line_spacing)
    height = max(1, line_h * len(lines) + 2 * margin)
    img = Image.new("L", (width_px, height), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        w = font.getlength(line)
        if align == "left":
            x = margin
        elif align == "right":
            x = width_px - margin - w
        else:
            x = (width_px - w) / 2
        draw.text((x, margin + i * line_h), line, font=font, fill=0)
    return img
