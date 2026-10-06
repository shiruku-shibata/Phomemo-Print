"""Phomemo M02 command byte sequences (pure logic, no I/O).

All values are guesses until verified on the real device; record results in
docs/device-notes.md.

Source: vivier/phomemo-tools, tools/phomemo-filter.py
  print_header()  L13-16
  print_marker()  L18-24
  print_footer()  L26-34
  print_line()    L36-48
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .raster import Raster

# ESC @ (init) + ESC a 1 (center) + 1F 11 02 04 (vendor: density/heat?)
# phomemo-filter.py L15
HEADER = b"\x1b\x40" + b"\x1b\x61\x01" + b"\x1f\x11\x02\x04"

# GS v 0, mode 0 (normal) -- followed by xL xH yL yH
# phomemo-filter.py L20-21
RASTER_CMD = b"\x1d\x76\x30\x00"

# Max raster rows per GS v 0 block. phomemo-filter.py L77-78
MAX_BLOCK_LINES = 256

# ESC d n (feed n lines). Sent twice. phomemo-filter.py L28-29
FEED_CMD = b"\x1b\x64"

# Vendor trailer. phomemo-filter.py L30-33
FOOTER_TAIL = b"\x1f\x11\x08" + b"\x1f\x11\x0e" + b"\x1f\x11\x07" + b"\x1f\x11\x09"

# phomemo-filter.py L23 writes (lines - 1) as the row count, while standard
# ESC/POS GS v 0 expects the real count. Flip this if the printer drops or
# adds a row per block on the real device.
HEIGHT_MINUS_ONE = False

# phomemo-filter.py L43-46: "0x0a breaks the rendering" -> replaced by 0x14.
# Off by default (GS v 0 payload should be binary-safe); enable if output
# shows glitches on rows containing that byte pattern.
ESCAPE_LF = False


def header() -> bytes:
    return HEADER


def footer(feed_lines: int = 2) -> bytes:
    if not 0 <= feed_lines <= 255:
        raise ValueError(f"feed_lines must be 0..255, got {feed_lines}")
    feed = FEED_CMD + bytes([feed_lines])
    return feed + feed + FOOTER_TAIL


def raster_block(width_bytes: int, rows: bytes, *, height_minus_one: bool | None = None,
                 escape_lf: bool | None = None) -> bytes:
    """One GS v 0 block. `rows` must be a whole number of rows."""
    if height_minus_one is None:
        height_minus_one = HEIGHT_MINUS_ONE
    if escape_lf is None:
        escape_lf = ESCAPE_LF
    if width_bytes <= 0 or len(rows) % width_bytes:
        raise ValueError("rows length must be a multiple of width_bytes")
    lines = len(rows) // width_bytes
    if not 1 <= lines <= MAX_BLOCK_LINES:
        raise ValueError(f"block must have 1..{MAX_BLOCK_LINES} lines, got {lines}")
    count = lines - 1 if height_minus_one else lines
    if escape_lf:
        rows = rows.replace(b"\x0a", b"\x14")
    return (
        RASTER_CMD
        + width_bytes.to_bytes(2, "little")
        + count.to_bytes(2, "little")
        + rows
    )


def build_print_job(raster: "Raster", feed_lines: int = 2) -> bytes:
    """Header + GS v 0 blocks (<= MAX_BLOCK_LINES rows each) + footer."""
    if raster.width_px % 8:
        raise ValueError("raster width must be a multiple of 8")
    width_bytes = raster.width_px // 8
    if len(raster.data) != width_bytes * raster.height_px:
        raise ValueError("raster data length does not match width/height")

    out = bytearray(header())
    block_size = width_bytes * MAX_BLOCK_LINES
    for start in range(0, len(raster.data), block_size):
        out += raster_block(width_bytes, raster.data[start:start + block_size])
    out += footer(feed_lines)
    return bytes(out)
