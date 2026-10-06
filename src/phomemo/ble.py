"""BLE transport for the Phomemo M02 (macOS / CoreBluetooth via bleak).

On macOS the device address is a CoreBluetooth UUID, not a MAC address, so the
printer is located by advertised name prefix or by the ff00 service UUID.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

log = logging.getLogger(__name__)

# GATT layout from CLAUDE.md "既知の情報" -- verify with tools/explore_gatt.py
SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUIDS = (
    "0000ff01-0000-1000-8000-00805f9b34fb",
    "0000ff03-0000-1000-8000-00805f9b34fb",
)

# Fallback when the backend reports no usable MTU. Conservative BLE 4.x value.
DEFAULT_CHUNK = 128
# Upper bound even if the backend reports a larger MTU; some printers choke on
# big writes without response.
MAX_CHUNK = 512
# Wait after the final write so the printer can drain its buffer before we
# disconnect (disconnecting early truncates the print on many cheap printers).
DRAIN_SECONDS = 1.5

PERMISSION_HINT = (
    "BLE デバイスが 1 台も見つかりませんでした。\n"
    "  - Bluetooth がオンか確認してください\n"
    "  - システム設定 > プライバシーとセキュリティ > Bluetooth で、"
    "このコマンドを実行しているアプリ（ターミナル / VS Code / Godot）を許可してください\n"
    "  - 許可後はアプリを再起動してください"
)


class PrinterNotFound(RuntimeError):
    pass


@dataclass
class ScanResult:
    device: BLEDevice
    name: str
    rssi: int | None
    service_uuids: list[str]

    @property
    def looks_like_phomemo(self) -> bool:
        return SERVICE_UUID in self.service_uuids


async def scan(timeout: float = 5.0) -> list[ScanResult]:
    """All advertising devices, strongest signal first."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = [
        ScanResult(dev, adv.local_name or dev.name or "", adv.rssi,
                   [u.lower() for u in adv.service_uuids])
        for dev, adv in found.values()
    ]
    results.sort(key=lambda r: -(r.rssi if r.rssi is not None else -999))
    return results


async def find_printer(name_prefix: str = "M02", timeout: float = 10.0) -> BLEDevice:
    """First device whose name starts with `name_prefix` or advertises ff00."""
    def match(dev: BLEDevice, adv) -> bool:
        name = adv.local_name or dev.name or ""
        if name_prefix and name.startswith(name_prefix):
            return True
        return SERVICE_UUID in [u.lower() for u in adv.service_uuids]

    device = await BleakScanner.find_device_by_filter(match, timeout=timeout)
    if device is not None:
        return device

    # Distinguish "nothing at all" (permission problem) from "printer not seen"
    others = await BleakScanner.discover(timeout=2.0)
    if not others:
        raise PrinterNotFound(PERMISSION_HINT)
    raise PrinterNotFound(
        f"名前が {name_prefix!r} で始まるプリンターが見つかりません "
        f"（周囲の BLE デバイス {len(others)} 台）。電源と距離を確認し、"
        "`phomemo scan --all` で広告名を確認してください。"
    )


def _chunk_size(client: BleakClient, requested: int | None) -> int:
    if requested:
        return requested
    char = client.services.get_characteristic(WRITE_CHAR_UUID)
    size = getattr(char, "max_write_without_response_size", 0) if char else 0
    if not size or size < 20:
        return DEFAULT_CHUNK
    return min(size, MAX_CHUNK)


def _on_notify(sender, data: bytearray) -> None:
    log.info("notify %s: %s", getattr(sender, "uuid", sender), data.hex(" "))


async def send(device: BLEDevice, payload: bytes, chunk: int | None = None,
               delay: float = 0.02) -> None:
    """Connect, stream `payload` to ff02 in chunks (write without response)."""
    async with BleakClient(device) as client:
        await send_with_client(client, payload, chunk=chunk, delay=delay)


async def send_with_client(client: BleakClient, payload: bytes, chunk: int | None = None,
                           delay: float = 0.02) -> None:
    """Like send() but on an already-connected client (used by the print queue)."""
    subscribed = []
    for uuid in NOTIFY_CHAR_UUIDS:
        if client.services.get_characteristic(uuid) is None:
            continue
        try:
            await client.start_notify(uuid, _on_notify)
            subscribed.append(uuid)
        except Exception as e:  # notify may be unsupported; only for logging
            log.debug("start_notify %s failed: %s", uuid, e)

    size = _chunk_size(client, chunk)
    log.info("sending %d bytes in chunks of %d (delay %.3fs)", len(payload), size, delay)
    try:
        for off in range(0, len(payload), size):
            await client.write_gatt_char(WRITE_CHAR_UUID, payload[off:off + size],
                                         response=False)
            if delay:
                await asyncio.sleep(delay)
        await asyncio.sleep(DRAIN_SECONDS)
    finally:
        for uuid in subscribed:
            try:
                await client.stop_notify(uuid)
            except Exception:
                pass
