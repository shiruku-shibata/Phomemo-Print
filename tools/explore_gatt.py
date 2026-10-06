#!/usr/bin/env python3
"""Dump advertisement + every GATT service / characteristic / property.

Usage:
    python tools/explore_gatt.py                 # scan, list devices
    python tools/explore_gatt.py --name M02      # connect to first match and dump
    python tools/explore_gatt.py --name M02 --listen 10   # also print notifications

Paste the output into docs/device-notes.md.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from bleak import BleakClient, BleakScanner


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="device name prefix to connect to (e.g. M02)")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--listen", type=float, default=0.0,
                    help="seconds to listen for notifications after dumping")
    args = ap.parse_args()

    print(f"# GATT dump {datetime.now():%Y-%m-%d %H:%M:%S}")
    found = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    if not found:
        print("No BLE devices. Check Bluetooth permission for this app "
              "(System Settings > Privacy & Security > Bluetooth).")
        return

    target = None
    print("\n## Advertisements")
    for dev, adv in sorted(found.values(), key=lambda x: -(x[1].rssi or -999)):
        name = adv.local_name or dev.name or ""
        print(f"- {name or '(no name)'}  addr={dev.address}  rssi={adv.rssi}")
        if adv.service_uuids:
            print(f"    services: {', '.join(adv.service_uuids)}")
        if adv.manufacturer_data:
            for cid, data in adv.manufacturer_data.items():
                print(f"    manufacturer 0x{cid:04x}: {data.hex(' ')}")
        if args.name and target is None and name.startswith(args.name):
            target = dev

    if not args.name:
        return
    if target is None:
        print(f"\nNo device with name prefix {args.name!r}")
        return

    print(f"\n## GATT of {target.name} ({target.address})")
    async with BleakClient(target) as client:
        for svc in client.services:
            print(f"\n[service] {svc.uuid}  {svc.description}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                mtu = getattr(ch, "max_write_without_response_size", "?")
                print(f"  [char] {ch.uuid}  handle={ch.handle}  props={props}  "
                      f"max_wwr={mtu}  {ch.description}")
                if "read" in ch.properties:
                    try:
                        val = await client.read_gatt_char(ch.uuid)
                        print(f"     value: {bytes(val).hex(' ')}  {bytes(val)!r}")
                    except Exception as e:
                        print(f"     read failed: {e}")
                for d in ch.descriptors:
                    print(f"     [desc] {d.uuid} handle={d.handle}")

        if args.listen > 0:
            print(f"\n## Notifications ({args.listen}s)")
            for svc in client.services:
                for ch in svc.characteristics:
                    if "notify" in ch.properties or "indicate" in ch.properties:
                        await client.start_notify(
                            ch.uuid,
                            lambda s, d, u=ch.uuid: print(f"  {u}: {bytes(d).hex(' ')}"))
            await asyncio.sleep(args.listen)


if __name__ == "__main__":
    asyncio.run(main())
