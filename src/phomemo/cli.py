"""phomemo CLI.

Exit codes (for Godot's OS.execute): 0 ok, 1 error, 2 printer not found, 3 bad input.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from PIL import Image, ImageOps

from . import ble, protocol
from .raster import DITHERS, Raster, image_to_raster, raster_to_image, solid_raster, stripe_raster
from .text import ALIGNS, text_to_image

EXIT_ERROR, EXIT_NOT_FOUND, EXIT_BAD_INPUT = 1, 2, 3


def _setup_logging(verbose: int) -> None:
    level = logging.WARNING - 10 * verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")


def _run_print(payloads: list[tuple[str, bytes]], name: str, chunk: int | None,
               delay: float) -> None:
    """Send payloads in order over a single connection."""
    async def go() -> None:
        from .queue import PrintQueue
        q = PrintQueue(name_prefix=name, chunk=chunk, delay=delay)
        worker = asyncio.create_task(q.run())
        try:
            futs = [q.submit(p, label) for label, p in payloads]
            for (label, _), fut in zip(payloads, futs):
                await fut
                click.echo(f"printed: {label}")
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(go())
    except ble.PrinterNotFound as e:
        click.echo(str(e), err=True)
        sys.exit(EXIT_NOT_FOUND)
    except Exception as e:
        click.echo(f"print failed: {type(e).__name__}: {e}", err=True)
        sys.exit(EXIT_ERROR)


# Shared options --------------------------------------------------------------

def ble_options(f):
    f = click.option("--name", default="M02", show_default=True,
                     help="Printer BLE name prefix")(f)
    f = click.option("--chunk", type=int, default=None,
                     help="Bytes per BLE write (default: from MTU)")(f)
    f = click.option("--delay", type=float, default=0.02, show_default=True,
                     help="Seconds between BLE writes")(f)
    f = click.option("--feed", type=int, default=2, show_default=True,
                     help="Feed lines after printing")(f)
    return f


def image_options(f):
    f = click.option("--width", type=int, default=384, show_default=True)(f)
    f = click.option("--dither", type=click.Choice(DITHERS), default="floyd", show_default=True)(f)
    f = click.option("--threshold", type=click.IntRange(0, 255), default=128, show_default=True)(f)
    f = click.option("--contrast", type=float, default=1.0, show_default=True)(f)
    f = click.option("--gamma", type=float, default=1.0, show_default=True,
                     help=">1 lightens midtones (thermal paper prints dark)")(f)
    f = click.option("--rotate", type=click.Choice(["none", "auto", "90", "180", "270"]),
                     default="none", show_default=True,
                     help="auto: rotate landscape images to portrait")(f)
    return f


def _prepare(img: Image.Image, rotate: str) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if rotate == "auto" and img.width > img.height:
        return img.rotate(90, expand=True)
    if rotate in ("90", "180", "270"):
        return img.rotate(int(rotate), expand=True)
    return img


@click.group()
@click.option("-v", "--verbose", count=True, help="-v info, -vv debug (shows BLE notifications)")
@click.version_option()
def main(verbose: int) -> None:
    """Print to a Phomemo M02 thermal printer over BLE."""
    _setup_logging(verbose)


@main.command()
@click.option("--timeout", type=float, default=5.0, show_default=True)
@click.option("--all", "show_all", is_flag=True, help="Show every BLE device, not just printers")
@click.option("--name", default="M02", show_default=True)
def scan(timeout: float, show_all: bool, name: str) -> None:
    """Find nearby M02 printers."""
    results = asyncio.run(ble.scan(timeout))
    if not results:
        click.echo(ble.PERMISSION_HINT, err=True)
        sys.exit(EXIT_NOT_FOUND)
    hits = [r for r in results if r.name.startswith(name) or r.looks_like_phomemo]
    shown = results if show_all else hits
    for r in shown:
        mark = "*" if r in hits else " "
        click.echo(f"{mark} {r.name or '(no name)':<24} rssi={r.rssi!s:>4}  {r.device.address}")
    if not hits:
        click.echo(f"No printer matching {name!r} ({len(results)} other devices). "
                   "Try --all to see advertised names.", err=True)
        sys.exit(EXIT_NOT_FOUND)


@main.command("print")
@click.argument("images", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--text", "text", default=None, help="Print text instead of / after images")
@click.option("--font", default=None, help="Font file (default: Hiragino Kaku Gothic)")
@click.option("--font-size", type=int, default=48, show_default=True)
@click.option("--align", type=click.Choice(ALIGNS), default="center", show_default=True)
@click.option("--preview", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Save converted bitmap to this PNG and do NOT print")
@image_options
@ble_options
def print_cmd(images, text, font, font_size, align, preview, width, dither, threshold,
              contrast, gamma, rotate, name, chunk, delay, feed) -> None:
    """Print image file(s) and/or --text."""
    if not images and text is None:
        raise click.UsageError("give an image path or --text")

    rasters: list[tuple[str, Raster]] = []
    try:
        for path in images:
            with Image.open(path) as img:
                img = _prepare(img, rotate)
                rasters.append((path.name, image_to_raster(
                    img, width, dither, threshold, contrast=contrast, gamma=gamma)))
        if text is not None:
            img = text_to_image(text.replace("\\n", "\n"), width_px=width,
                                font_size=font_size, font_path=font, align=align)
            # Text is already black/white; threshold avoids dither noise on edges
            rasters.append(("text", image_to_raster(img, width, "threshold", threshold)))
    except (OSError, ValueError) as e:
        click.echo(f"cannot convert: {e}", err=True)
        sys.exit(EXIT_BAD_INPUT)

    if preview is not None:
        _save_preview(preview, [r for _, r in rasters])
        return

    _run_print([(label, protocol.build_print_job(r, feed)) for label, r in rasters],
               name, chunk, delay)


def _save_preview(path: Path, rasters: list[Raster]) -> None:
    imgs = [raster_to_image(r).convert("L") for r in rasters]
    w = max(i.width for i in imgs)
    gap = 16
    out = Image.new("L", (w, sum(i.height for i in imgs) + gap * (len(imgs) - 1)), 200)
    y = 0
    for i in imgs:
        out.paste(i, (0, y))
        y += i.height + gap
    out.save(path)
    click.echo(f"preview saved: {path} ({w}x{out.height})")


@main.command("test-pattern")
@click.option("--kind", type=click.Choice(["solid", "stripes"]), default="solid", show_default=True)
@click.option("--height", type=int, default=50, show_default=True)
@click.option("--width", type=int, default=384, show_default=True)
@click.option("--dump", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the raw command bytes to this file instead of printing")
@ble_options
def test_pattern(kind, height, width, dump, name, chunk, delay, feed) -> None:
    """Print a small black block (or stripes) to check the BLE link."""
    r = solid_raster(width, height) if kind == "solid" else stripe_raster(width, height)
    payload = protocol.build_print_job(r, feed)
    if dump:
        dump.write_bytes(payload)
        click.echo(f"wrote {len(payload)} bytes to {dump}")
        return
    _run_print([(f"{kind} {width}x{height}", payload)], name, chunk, delay)


@main.command()
@click.option("--spool", type=click.Path(file_okay=False, path_type=Path),
              default=Path("spool"), show_default=True,
              help="Folder to watch. Drop .png/.jpg or .txt files here (write then rename).")
@click.option("--font", default=None)
@click.option("--font-size", type=int, default=48, show_default=True)
@click.option("--align", type=click.Choice(ALIGNS), default="center", show_default=True)
@image_options
@ble_options
def serve(spool, font, font_size, align, width, dither, threshold, contrast, gamma, rotate,
          name, chunk, delay, feed) -> None:
    """Resident mode: watch a spool folder and print files one at a time."""
    from .queue import IMAGE_SUFFIXES, PrintQueue, watch_spool

    def render(path: Path) -> bytes:
        if path.suffix.lower() in IMAGE_SUFFIXES:
            with Image.open(path) as img:
                r = image_to_raster(_prepare(img, rotate), width, dither, threshold,
                                    contrast=contrast, gamma=gamma)
        else:
            img = text_to_image(path.read_text(encoding="utf-8").rstrip("\n"),
                                width_px=width, font_size=font_size, font_path=font,
                                align=align)
            r = image_to_raster(img, width, "threshold", threshold)
        return protocol.build_print_job(r, feed)

    async def go() -> None:
        q = PrintQueue(name_prefix=name, chunk=chunk, delay=delay, wait_for_printer=True)
        await asyncio.gather(q.run(), watch_spool(spool.resolve(), q, render))

    if not logging.getLogger().isEnabledFor(logging.INFO):
        logging.getLogger().setLevel(logging.INFO)
    click.echo(f"serving spool {spool.resolve()}  (Ctrl-C to stop)")
    try:
        asyncio.run(go())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
