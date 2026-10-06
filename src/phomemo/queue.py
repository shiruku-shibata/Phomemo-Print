"""Print queue: serializes jobs onto one BLE connection, plus a spool watcher.

Multiple print requests (e.g. from Godot) never talk to the printer at the
same time: they are pushed onto an asyncio.Queue and a single worker sends
them in order over a connection that is kept open and re-established on error.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bleak import BleakClient

from . import ble

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
TEXT_SUFFIXES = {".txt"}
SPOOL_SUFFIXES = IMAGE_SUFFIXES | TEXT_SUFFIXES


@dataclass
class Job:
    payload: bytes
    label: str = ""
    done: asyncio.Future = field(default=None)  # type: ignore[assignment]


class PrintQueue:
    def __init__(self, name_prefix: str = "M02", chunk: int | None = None,
                 delay: float = 0.02, retries: int = 2, gap: float = 0.5,
                 wait_for_printer: bool = False):
        self.name_prefix = name_prefix
        # True (serve mode): keep jobs and retry until the printer shows up
        self.wait_for_printer = wait_for_printer
        self.chunk = chunk
        self.delay = delay
        self.retries = retries
        self.gap = gap  # pause between jobs so the cutter-less paper can settle
        self._q: asyncio.Queue[Job] = asyncio.Queue()
        self._client: BleakClient | None = None

    def submit(self, payload: bytes, label: str = "") -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self._q.put_nowait(Job(payload, label, fut))
        log.info("queued %s (%d bytes, %d waiting)", label, len(payload), self._q.qsize())
        return fut

    def pending(self) -> int:
        return self._q.qsize()

    async def _connect(self) -> BleakClient:
        if self._client is not None and self._client.is_connected:
            return self._client
        device = await ble.find_printer(self.name_prefix)
        client = BleakClient(device, disconnected_callback=lambda _: log.warning("printer disconnected"))
        await client.connect()
        log.info("connected to %s", device.name)
        self._client = client
        return client

    async def _disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

    async def _print(self, job: Job) -> None:
        attempt = 0
        while True:
            try:
                client = await self._connect()
                await ble.send_with_client(client, job.payload, chunk=self.chunk, delay=self.delay)
                return
            except ble.PrinterNotFound as e:
                if not self.wait_for_printer:
                    raise
                log.warning("waiting for printer (%s still queued): %s", job.label, e)
                await asyncio.sleep(5.0)
            except Exception as e:
                attempt += 1
                log.warning("job %s attempt %d failed: %s", job.label, attempt, e)
                await self._disconnect()
                if attempt > self.retries:
                    raise
                await asyncio.sleep(1.0)

    async def run(self) -> None:
        """Worker loop. Run as a task; cancel to stop."""
        try:
            while True:
                job = await self._q.get()
                try:
                    await self._print(job)
                    log.info("printed %s", job.label)
                    if not job.done.done():
                        job.done.set_result(None)
                except Exception as e:
                    log.error("failed %s: %s", job.label, e)
                    if not job.done.done():
                        job.done.set_exception(e)
                finally:
                    self._q.task_done()
                await asyncio.sleep(self.gap)
        finally:
            await self._disconnect()


# ---------------------------------------------------------------- spool folder

def pending_spool_files(spool: Path) -> list[Path]:
    """Ready-to-print files in `spool`, oldest first.

    Writers must create the file under a temporary name (e.g. `x.png.tmp` or a
    dotfile) and rename it into place, so half-written files are never picked up.
    """
    files = [
        p for p in spool.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SPOOL_SUFFIXES
    ]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return files


def _move(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.stem}-{n}{src.suffix}"
        n += 1
    shutil.move(str(src), dest)
    return dest


async def watch_spool(spool: Path, queue: PrintQueue,
                      render: Callable[[Path], bytes], poll: float = 0.5) -> None:
    """Poll `spool`, claim files into processing/, queue them, sort into done/ failed/."""
    processing, done, failed = spool / "processing", spool / "done", spool / "failed"
    for d in (spool, processing, done, failed):
        d.mkdir(parents=True, exist_ok=True)

    # Recover files left in processing/ by a previous crash
    for p in sorted(processing.iterdir()):
        _move(p, spool)

    async def finish(path: Path, fut: asyncio.Future) -> None:
        try:
            await fut
            _move(path, done)
        except Exception as e:
            dest = _move(path, failed)
            dest.with_name(dest.name + ".err").write_text(f"{type(e).__name__}: {e}\n")

    tasks: set[asyncio.Task] = set()
    log.info("watching spool %s", spool)
    while True:
        for path in pending_spool_files(spool):
            claimed = _move(path, processing)
            try:
                payload = render(claimed)
            except Exception as e:
                log.error("cannot render %s: %s", path.name, e)
                dest = _move(claimed, failed)
                dest.with_name(dest.name + ".err").write_text(f"{type(e).__name__}: {e}\n")
                continue
            fut = queue.submit(payload, claimed.name)
            t = asyncio.create_task(finish(claimed, fut))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
        await asyncio.sleep(poll)
