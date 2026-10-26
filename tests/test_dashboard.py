"""Check the live dashboard: its model matches the badge, and its server decodes adverts."""

import json
import subprocess
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import server
import status_beacon as sb
from badge_harness import BadgeHarness

# A walk through every screen, including first use, warnings, retries and arrival.
# (own, team, partner, status, progress, success_total, now_ms)
SEQUENCE = [
    (0, None, None, "Hold badges back to back", None, None, 0),
    (40, None, None, "Hold steady", 0.4, None, 100),
    (40, None, None, "Hold together to retry", None, None, 200),
    (40, None, None, "Could not sync - try again", None, None, 300),
    (40, None, None, "Step sensor unavailable", None, None, 400),
    (4950, 9900, 4950, "Hold badges back to back", None, None, 500),
    (5000, 9900, 4950, "Hold steady", 1.0, None, 600),
    (5000, 9900, 4950, "Syncing...", None, None, 700),
    (5000, 10010, 5010, "Synced", None, 10010, 800),
    (5000, 10010, 5010, "Synced", None, 10010, 900),
    (5000, 10010, 5010, "Move badges apart", None, None, 1000),
    (5010, 10010, 5010, "Hold badges back to back", None, None, 5000),
    (5010, 10010, 5010, "Progress not saved", None, None, 9000),
    (5020, 10010, 5010, "Sync paused - reopen Walking", None, None, 9100),
]
FIELDS = ("phase", "status", "tone", "hold", "lost", "new_steps", "shared", "mine",
          "reached", "prev_team", "arrival", "team")


class ModelParityTests(unittest.TestCase):
    def test_js_model_matches_the_badge(self):
        with BadgeHarness() as app:
            ui = app.app["ui"]
            python = []
            for own, team, partner, status, progress, success, now in SEQUENCE:
                m = ui.model(own, team, partner, status, progress, 0 if success is not None else None, success, now)
                python.append({f: getattr(m, f) for f in FIELDS})
        result = subprocess.run(["node", "-e", """
const { tracker } = require('./dashboard/model.js');
const model = tracker();
const rows = JSON.parse(process.argv[1]).map(([own, team, partner, status, progress, success, now]) => {
  const m = model(own, team, partner, status, progress, success, now);
  return { ...m, new_steps: m.newSteps, prev_team: m.prevTeam };
});
console.log(JSON.stringify(rows));
""", json.dumps(SEQUENCE)], cwd=ROOT, capture_output=True, text=True, check=True)
        js = json.loads(result.stdout)
        for i, (want, got) in enumerate(zip(python, js)):
            with self.subTest(step=i, status=SEQUENCE[i][3]):
                for field in FIELDS:
                    if isinstance(want[field], float):
                        self.assertAlmostEqual(got[field], want[field], places=9, msg=field)
                    else:
                        self.assertEqual(got[field], want[field], field)
        self.assertTrue(any(row["arrival"] for row in python), "Sequence covers arrival")


class PairCoordinatorTests(unittest.TestCase):
    def test_one_confirmed_total_celebrates_on_both_screens_once(self):
        result = subprocess.run(["node", "-e", """
const assert = require('node:assert/strict');
const { coordinator, CELEBRATE_MS, QUIET_MS } = require('./dashboard/model.js');
const pair = coordinator();
const badge = (id, team, status, extra = {}) => ({ id, own: 100, team, partner: 50, status, progress: null, success: false, ...extra });
// Recorded on hardware: Maggie's success is heard, Martin's only as a new total.
assert.equal(pair.observe([badge('m', 297, 'Hold steady', { progress: 0.4 }), badge('n', 297, 'Hold badges back to back')], 0), false, 'page load is not a sync');
const holding = badge('m', 297, 'Hold steady', { progress: 0.4 });
assert.equal(pair.inputs(holding, 200, 100).status, 'Hold steady');
assert.equal(pair.inputs(holding, QUIET_MS + 100, 100).status, 'Syncing...', 'quiet mid-hold means linked');
assert.equal(pair.observe([badge('m', 376, 'Synced', { success: true }), badge('n', 297, 'Hold badges back to back')], 1000), true);
assert.equal(pair.inputs(badge('n', 297, 'Hold steady', { progress: 1 }), 3000, 1100).successTotal, 376, 'partner shows the same success');
assert.equal(pair.observe([badge('m', 376, 'Synced'), badge('n', 376, 'Synced')], 1500), false, 'one burst per sync');
assert.equal(pair.celebrating(1000 + CELEBRATE_MS + 1), false);
assert.equal(pair.inputs(badge('n', 376, 'Move badges apart'), 0, 1000 + CELEBRATE_MS + 1).successTotal, null);
assert.equal(pair.observe([badge('n', 0, 'Hold badges back to back')], 9000), false, 'a reset is not a sync');
assert.equal(pair.observe([badge('n', 40, 'Move badges apart')], 9500), true, 'a rise without a heard success still counts');
"""], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ServerTests(unittest.TestCase):
    def test_decodes_only_walking_status_from_service_data(self):
        payload = sb.pack("f95119f417c67d7e", 3, 12, 40, 17, "Hold steady", 0.5)
        got = server.decode_advert({server.SERVICE_KEY: payload, "0000180f-0000-1000-8000-00805f9b34fb": b"x"})
        self.assertEqual((got["own"], got["status"], got["progress"]), (12, "Hold steady", 0.5))
        self.assertIsNone(server.decode_advert({}))
        self.assertIsNone(server.decode_advert({server.SERVICE_KEY: b"\x09" + payload[1:]}))

    def test_demo_badges_agree_on_the_shared_total(self):
        hub = server.Hub()
        demo = server.Demo(hub)
        for t in [x / 2 for x in range(0, 80)]:
            demo.tick(t)
            maggie, martin = (hub.badges[i] for i in demo.IDS)
            self.assertEqual(maggie["team"], martin["team"])
            self.assertEqual(maggie["status"], martin["status"])
            if not maggie["success"]:
                self.assertEqual(maggie["team"], maggie["partner"] + martin["partner"])

    def test_serves_status_and_page(self):
        hub = server.Hub()
        hub.update(sb.unpack(sb.pack("79469e7227b64f70", 1, 5, None, None, "Hold badges back to back")), -60)
        server.Handler.hub = hub
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(ROOT)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = "http://127.0.0.1:%d" % httpd.server_port
        status = json.load(urllib.request.urlopen(base + "/status"))
        self.assertEqual(status["badges"][0]["wearer"], "Martin")
        self.assertIn(b"live.js", urllib.request.urlopen(base + "/").read())
        script = urllib.request.urlopen(base + "/design-jig/walking/fresh/directions.js")
        self.assertIn(b"function paint", script.read())
        self.assertEqual(script.headers["Cache-Control"], "no-cache")
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/badge/apps/walking/__init__.py")


if __name__ == "__main__":
    unittest.main()
