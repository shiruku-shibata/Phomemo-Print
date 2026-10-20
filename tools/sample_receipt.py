#!/usr/bin/env python3
"""Render a receipt-style test image (384px wide) for the M02.

Usage:
    python tools/sample_receipt.py out.png
    phomemo print out.png --dither threshold --delay 0.05
"""

from __future__ import annotations

import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from phomemo.text import find_font

W = 384
M = 12  # side margin

ITEMS = [
    ("生ビール", 2, 580),
    ("枝豆", 1, 380),
    ("唐揚げ", 1, 680),
    ("だし巻き玉子", 1, 520),
    ("ハイボール", 3, 450),
]


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = find_font() if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    return ImageFont.truetype(path, size)


def render() -> Image.Image:
    img = Image.new("L", (W, 1200), 255)
    d = ImageDraw.Draw(img)
    y = 16

    def center(text: str, f: ImageFont.FreeTypeFont, gap: int = 6) -> None:
        nonlocal y
        d.text(((W - f.getlength(text)) / 2, y), text, font=f, fill=0)
        y += f.size + gap

    def row(left: str, right: str, f: ImageFont.FreeTypeFont, gap: int = 6) -> None:
        nonlocal y
        d.text((M, y), left, font=f, fill=0)
        d.text((W - M - f.getlength(right), y), right, font=f, fill=0)
        y += f.size + gap

    def dashed() -> None:
        nonlocal y
        y += 4
        for x in range(M, W - M, 10):
            d.line((x, y, x + 5, y), fill=0, width=2)
        y += 12

    big, mid, small = font(34), font(22), font(18, bold=False)

    center("居酒屋 ふぉめも", big, 4)
    center("PHOMEMO PRINT TEST", small, 2)
    center("Tel 00-0000-0000", small, 10)
    now = datetime.now()
    row(now.strftime("%Y年%m月%d日(%a)"), now.strftime("%H:%M"), small)
    row("卓番 7", "担当 Claude", small)
    dashed()

    total = 0
    for name, qty, price in ITEMS:
        amount = qty * price
        total += amount
        row(name, f"¥{amount:,}", mid, 2)
        d.text((M + 16, y), f"{qty} × ¥{price:,}", font=small, fill=0)
        y += small.size + 8
    dashed()

    tax = total * 10 // 110
    row(f"小計 ({sum(q for _, q, _ in ITEMS)}点)", f"¥{total:,}", mid)
    row("(内消費税 10%)", f"¥{tax:,}", small)
    y += 4
    d.rectangle((M, y, W - M, y + 48), fill=0)
    f = font(30)
    d.text((M + 12, y + 7), "合計", font=f, fill=255)
    t = f"¥{total:,}"
    d.text((W - M - 12 - f.getlength(t), y + 7), t, font=f, fill=255)
    y += 60
    row("お預り", "¥5,000", mid)
    row("お釣り", f"¥{5000 - total:,}", mid)
    dashed()

    # fake barcode: deterministic bar widths
    bx, seed = 48, 7
    while bx < W - 48:
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        bw = 2 + seed % 4
        d.rectangle((bx, y, bx + bw - 1, y + 56), fill=0)
        bx += bw + 2 + (seed >> 8) % 3
    y += 64
    center(now.strftime("No. %Y%m%d-%H%M%S"), small, 12)
    center("ありがとうございました", mid, 4)
    center("またのご来店を", small, 4)
    center("お待ちしております", small, 20)

    return img.crop((0, 0, W, y))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "receipt.png"
    render().save(out)
    print(out)
