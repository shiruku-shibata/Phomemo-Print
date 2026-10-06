import asyncio
import os

from phomemo import queue as pq


def test_pending_spool_files_filters_and_orders(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.txt"
    a.write_bytes(b"x")
    b.write_text("hi")
    os.utime(a, (100, 100))
    os.utime(b, (50, 50))
    (tmp_path / "c.png.tmp").write_bytes(b"x")    # still being written
    (tmp_path / ".hidden.png").write_bytes(b"x")
    (tmp_path / "notes.md").write_text("x")
    (tmp_path / "done").mkdir()
    assert [p.name for p in pq.pending_spool_files(tmp_path)] == ["b.txt", "a.png"]


def test_move_avoids_overwrite(tmp_path):
    dest = tmp_path / "done"
    for _ in range(2):
        f = tmp_path / "x.png"
        f.write_bytes(b"1")
        pq._move(f, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["x-1.png", "x.png"]


class FakeQueue(pq.PrintQueue):
    """Records payloads instead of talking BLE; fails on payload b'bad'."""

    def __init__(self):
        super().__init__(gap=0)
        self.sent = []
        self.active = 0
        self.max_active = 0

    async def _print(self, job):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if job.payload == b"bad":
            raise RuntimeError("boom")
        self.sent.append(job.payload)


def test_queue_serializes_jobs():
    async def go():
        q = FakeQueue()
        w = asyncio.create_task(q.run())
        futs = [q.submit(bytes([i])) for i in range(5)]
        await asyncio.gather(*futs)
        w.cancel()
        return q

    q = asyncio.run(go())
    assert q.sent == [bytes([i]) for i in range(5)]
    assert q.max_active == 1


def test_spool_end_to_end(tmp_path):
    (tmp_path / "1.txt").write_text("ok")
    (tmp_path / "2.txt").write_text("bad")
    (tmp_path / "3.txt").write_text("!render")

    def render(p):
        t = p.read_text()
        if t == "!render":
            raise ValueError("cannot render")
        return t.encode()

    async def go():
        q = FakeQueue()
        tasks = [asyncio.create_task(q.run()),
                 asyncio.create_task(pq.watch_spool(tmp_path, q, render, poll=0.01))]
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(list((tmp_path / "done").iterdir())) == 1 and \
               len(list((tmp_path / "failed").glob("*.txt"))) == 2:
                break
        for t in tasks:
            t.cancel()
        return q

    q = asyncio.run(go())
    assert q.sent == [b"ok"]
    assert [p.name for p in (tmp_path / "done").iterdir()] == ["1.txt"]
    failed = sorted(p.name for p in (tmp_path / "failed").iterdir())
    assert failed == ["2.txt", "2.txt.err", "3.txt", "3.txt.err"]


def test_retry_and_wait_for_printer(monkeypatch):
    """Printer missing twice, then one send error, then success."""
    from phomemo import ble

    events = []

    class FakeClient:
        is_connected = True

    async def fake_connect(self):
        events.append("connect")
        if events.count("connect") <= 2:
            raise ble.PrinterNotFound("off")
        return FakeClient()

    async def fake_send(client, payload, chunk=None, delay=0.0):
        events.append("send")
        if events.count("send") == 1:
            raise RuntimeError("link lost")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(pq.PrintQueue, "_connect", fake_connect)
    monkeypatch.setattr(ble, "send_with_client", fake_send)
    monkeypatch.setattr(pq.asyncio, "sleep", no_sleep)

    async def go():
        q = pq.PrintQueue(wait_for_printer=True, retries=1)
        await q._print(pq.Job(b"x"))

    asyncio.run(go())
    assert events == ["connect", "connect", "connect", "send", "connect", "send"]


def test_printer_not_found_raises_without_wait(monkeypatch):
    from phomemo import ble
    import pytest

    async def fake_connect(self):
        raise ble.PrinterNotFound("off")

    monkeypatch.setattr(pq.PrintQueue, "_connect", fake_connect)
    with pytest.raises(ble.PrinterNotFound):
        asyncio.run(pq.PrintQueue()._print(pq.Job(b"x")))
