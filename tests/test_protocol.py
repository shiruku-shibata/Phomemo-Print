import pytest

from phomemo import protocol
from phomemo.raster import Raster, solid_raster

HEADER = bytes.fromhex("1b40 1b6101 1f110204")
FOOTER = bytes.fromhex("1b6402 1b6402 1f1108 1f110e 1f1107 1f1109")


def test_header_footer_exact():
    assert protocol.header() == HEADER
    assert protocol.footer() == FOOTER


def test_footer_feed_lines():
    assert protocol.footer(5)[:6] == bytes.fromhex("1b6405 1b6405")
    with pytest.raises(ValueError):
        protocol.footer(256)


def test_single_block_exact():
    r = solid_raster(384, 50)
    job = protocol.build_print_job(r)
    expected = HEADER + bytes.fromhex("1d763000 3000 3200") + b"\xff" * (48 * 50) + FOOTER
    assert job == expected


def test_splits_into_256_line_blocks():
    r = Raster(16, 600, bytes(range(256)) * (2 * 600 // 256) + bytes(2 * 600 % 256))
    job = protocol.build_print_job(r)
    body = job[len(HEADER):-len(FOOTER)]
    heights = []
    rows = b""
    i = 0
    while i < len(body):
        assert body[i:i + 4] == b"\x1d\x76\x30\x00"
        wb = int.from_bytes(body[i + 4:i + 6], "little")
        h = int.from_bytes(body[i + 6:i + 8], "little")
        assert wb == 2
        heights.append(h)
        rows += body[i + 8:i + 8 + wb * h]
        i += 8 + wb * h
    assert heights == [256, 256, 88]
    assert rows == r.data


def test_height_minus_one_and_escape_lf():
    blk = protocol.raster_block(1, b"\x0a\x0b", height_minus_one=True, escape_lf=True)
    assert blk == bytes.fromhex("1d763000 0100 0100 140b")


def test_rejects_bad_raster():
    with pytest.raises(ValueError):
        protocol.build_print_job(Raster(384, 2, b"\x00" * 10))
    with pytest.raises(ValueError):
        protocol.build_print_job(Raster(380, 1, b"\x00" * 47))
