"""Live Walking dashboard: listens for badge adverts and serves the mirror page.

Passive only: the laptop scans BLE adverts and never connects to a badge.
On macOS run it from Terminal.app, which needs Bluetooth permission.

    .venv/bin/python dashboard/server.py            # real badges
    .venv/bin/python dashboard/server.py --demo     # simulated pair
"""

import argparse
import asyncio
import json
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "badge/apps/walking"))
import status_beacon  # noqa: E402

SERVICE_KEY = "0000%04x-0000-1000-8000-00805f9b34fb" % status_beacon.SERVICE_UUID
WEARERS = {"f95119f417c67d7e": "Maggie", "79469e7227b64f70": "Martin"}
STATIC = ("/dashboard/", "/design-jig/walking/")


class Hub:
    """Latest status per badge, plus a condition to wake event streams."""

    def __init__(self):
        self.badges = {}
        self.scanner = {"state": "starting", "error": None}
        self.version = 0
        self.changed = threading.Condition()

    def update(self, status, rssi=None, now=None):
        with self.changed:
            self.badges[status["id"]] = dict(status, rssi=rssi, seen=now or time.time(),
                                             wearer=WEARERS.get(status["id"]))
            self.version += 1
            self.changed.notify_all()

    def scanner_state(self, state, error=None):
        with self.changed:
            self.scanner = {"state": state, "error": error}
            self.version += 1
            self.changed.notify_all()

    def snapshot(self):
        with self.changed:
            return {"now": time.time(), "scanner": dict(self.scanner),
                    "badges": [dict(b) for b in self.badges.values()]}

    def wait(self, version, timeout):
        with self.changed:
            self.changed.wait_for(lambda: self.version != version, timeout)
            return self.version


def decode_advert(service_data):
    """Badge status from a bleak service-data dict, or None."""
    raw = service_data.get(SERVICE_KEY)
    return status_beacon.unpack(bytes(raw)) if raw else None


async def scan(hub):
    from bleak import BleakScanner

    def seen(device, advert):
        status = decode_advert(advert.service_data)
        if status:
            hub.update(status, advert.rssi)

    # Active scanning asks each badge for the scan response that carries status.
    async with BleakScanner(detection_callback=seen, scanning_mode="active"):
        hub.scanner_state("scanning")
        while True:
            await asyncio.sleep(3600)


def run_scanner(hub):
    try:
        asyncio.run(scan(hub))
    except Exception as error:  # Shown on the page; the server keeps serving.
        hub.scanner_state("error", "%s: %s" % (type(error).__name__, error))


class Demo:
    """Two simulated badges walking and syncing on a 36 s loop, quiet while linked."""

    IDS = ("f95119f417c67d7e", "79469e7227b64f70")
    PERIOD = 36

    def __init__(self, hub):
        self.hub = hub
        self.synced = [4800, 4900]
        self.own = [4860, 4930]
        self.seq = 0
        self.cycle = None

    def tick(self, t):
        cycle, phase = divmod(t, self.PERIOD)
        if phase < 12 or phase >= 30:
            self.own = [self.own[0] + 4, self.own[1] + 3]
        if phase >= 18 and self.cycle != cycle:
            self.cycle, self.synced = cycle, list(self.own)
        team = sum(self.synced)
        for i, badge in enumerate(self.IDS):
            status, progress, success = "Hold badges back to back", None, None
            if 12 <= phase < 16:
                status, progress = "Hold steady", min(1, (phase - 12) / 3)
            elif 16 <= phase < 18:
                continue  # Linked badges stop advertising, as on hardware.
            elif 18 <= phase < 22:
                # Often only one badge's brief success screen is heard.
                status = "Synced"
                success = team if i == 0 or phase < 18.6 else None
            elif 22 <= phase < 26:
                status = "Move badges apart"
            self.seq += 1
            payload = status_beacon.pack(badge, self.seq, self.own[i], team, self.synced[1 - i],
                                         status, progress, success)
            self.hub.update(status_beacon.unpack(payload), -50 - 6 * i)

    def run(self):
        self.hub.scanner_state("demo")
        start = time.time()
        while True:
            self.tick(time.time() - start)
            time.sleep(0.5)


class Handler(SimpleHTTPRequestHandler):
    hub = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/dashboard"):
            self.send_response(302)
            self.send_header("Location", "/dashboard/")
            self.end_headers()
        elif path == "/status":
            self.send_json(self.hub.snapshot())
        elif path == "/events":
            self.stream()
        elif path.startswith(STATIC) and ".." not in path:
            super().do_GET()
        else:
            self.send_error(404)

    def end_headers(self):
        # Without this, browsers such as Edge reuse stale renderer scripts
        # heuristically and draw the scene at the wrong scale.
        if self.path.split("?", 1)[0].startswith(STATIC):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        version = None
        try:
            while True:
                self.wfile.write(b"data: %s\n\n" % json.dumps(self.hub.snapshot()).encode())
                self.wfile.flush()
                # Wake on news, or every second so the page can age stale badges.
                version = self.hub.wait(version, 1.0)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--demo", action="store_true", help="simulate two badges instead of scanning")
    args = parser.parse_args(argv)

    hub = Hub()
    worker = Demo(hub).run if args.demo else partial(run_scanner, hub)
    threading.Thread(target=worker, daemon=True).start()

    Handler.hub = hub
    server = ThreadingHTTPServer((args.host, args.port), partial(Handler, directory=str(ROOT)))
    server.daemon_threads = True
    print("Walking dashboard: http://%s:%d/" % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
