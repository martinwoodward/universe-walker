# Universe Walker

A two-player walking game for GitHub Badger 2350 badges (RP2350). Keep the
Walking app open while walking independently, then hold the badges back to
back to combine your steps toward a shared **10,000-step goal**. Separate them
before syncing again. Pairing starts from the hold gesture; no button is needed.

![Walking screen showing confirmed shared steps and a pending local contribution](design-jig/walking/final/pending-maggie.png)

The white number is the last confirmed shared total. The equally large yellow
**+N** is your new local contribution; it joins the white total after a
successful sync. Before the first sync, the number shows your personal steps
and says they are not synced yet. Only confirmed shared progress lights the
lighthouse.

For demos, hold **UP** to add steps to your own count. A press adds one step;
after half a second the count speeds up gradually, reaching about 10,000
after roughly ten seconds. It stops once your unsynced +N reaches 9,957.
Releasing starts the slow ramp again, so a brief accidental press only adds a
few steps. Hold **DOWN** to remove steps with the same ramp; it stops at your
last synced count, because the partner badge would restore anything lower.

Hold **SELECT** for three seconds to reset this badge's personal and team
counts to zero, as on first start. The status line counts down while you hold.
Reset both badges, or the next sync restores the partner's copy of the totals.

## Start here

- [Hardware guide](docs/hardware.md): install, reset demo progress, inspect a
  badge, and run the two-badge check.
- [Architecture](docs/architecture.md): data model, durable sync protocol,
  hardware timing constraints, and code map.
- [Agent guide](AGENTS.md): where to work and what must remain true.
- [Design preview](design-jig/walking/README.md): current browser previews and
  approved coast design.

## Local development

Use Python 3.10+ and Node.js 18+. Node runs the browser fixture checks within the
Python suite. Host tests do not require a connected badge or device packages.

```sh
python3 -m unittest discover -s tests -v
```

For USB tools, create a local environment and install the development
dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
```

Serve the visual previews from the repository root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Open [the walking preview](http://127.0.0.1:8765/design-jig/walking/fresh.html)
or [the count tuning jig](http://127.0.0.1:8765/design-jig/walking/counter.html).
These use fixture data and never write badge progress.

### Live badge dashboard

`dashboard/` mirrors both badges' screens side by side, live, in a browser.
Each badge running Walking adds its screen state to its Bluetooth advert
(`status_beacon.py`); the server only listens, so it never pairs with or
slows down the badges.

**1. Install the dependencies** (once). The server needs Python 3.10+ and
`bleak` from `requirements-dev.txt`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

**2. Start the server** from the repository root:

```sh
.venv/bin/python dashboard/server.py           # real badges over Bluetooth
.venv/bin/python dashboard/server.py --demo    # simulated pair, no Bluetooth or badges
```

| Option | Default | Use |
| --- | --- | --- |
| `--port N` | `8765` | Serve on another port, e.g. run `--demo` on 8766 alongside the real one. |
| `--host H` | `127.0.0.1` | Use `0.0.0.0` to open the page from another device on the network. |
| `--demo` | off | Animate two simulated badges through walking and syncing. |

On macOS, run it from Terminal.app (or another terminal that has been granted
Bluetooth access in **System Settings → Privacy & Security → Bluetooth**).
The first run asks for permission; without it the scanner finds nothing.
Stop the server with **Ctrl+C**.

**3. Open <http://127.0.0.1:8765/>** and switch both badges on with Walking
running (it opens automatically after the splash on our demo badges). The page
updates about twice a second; reloading it picks up dashboard code changes
without restarting the server.

Maggie's badge starts alone in the centre, even when Martin's is heard. Press
**2** to fly Martin's in from the side and **1** to return to just Maggie;
the page never switches by itself. While the
badges pair, the screens draw together with a linking animation. A confirmed
sync shows the same total on both screens and a full-window confetti burst.
Outside a sync, a badge greys out after 10 s without an advert.

If a badge never appears, check that Walking is open on it (the menu and other
apps don't advertise) and that the terminal has Bluetooth permission; try
`--demo` to confirm the page itself works.

## Repository

| Path | Purpose |
| --- | --- |
| `badge/apps/walking/` | Installable MicroPython app; uses the badge's existing firmware runtime. |
| `dashboard/` | Live two-badge screen mirror: BLE scanner, server and page. |
| `design-jig/walking/` | Plain HTML/JavaScript previews, approved renders, and vendored Dial Kit. |
| `tests/` | Python unit/integration tests, virtual badge harness, and Node fixture checks. |
| `tools/` | USB setup and diagnostics. |
| `docs/` | Current architecture and hardware guidance. |

Step counting, saved progress, and repeated two-badge exchanges have been
reported working on the physical demo badges. The latest large contribution
row and native font placement still need a visual check after installation;
browser screenshots and host tests cannot establish that result.
