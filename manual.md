# PolarPrism User Manual

PolarPrism is a real-time sailing navigation instrument that connects to a Signal K server over WebSocket and displays heading, wind, polar performance, route progress, and nautical charts.

## Getting Started

### Prerequisites

- Python 3.11+
- A running Signal K server (default: `ws://localhost:3000/signalk/v1/stream`)
- Required Python packages (install via `pip install -e .`)

### Running

```bash
python main.py
# or, after `pip install -e .`:
polarprism
```

Press `Esc` or close the window to quit. Press `F11` to toggle fullscreen —
handy on a dedicated cockpit nav display.

## Interface Layout

The screen is divided into two areas:

- **Left sidebar** — Navigation menu for switching between pages
- **Main content area** — Displays the active page with tabs at the top

Click any sidebar item to switch pages. Click a tab to switch sub-pages.

## Pages

### Navigation (⚓)

Displays a tile-based nautical chart centered on the vessel's GPS position.

| Action | Control |
|---|---|
| Pan the chart | Click and drag |
| Zoom in/out | Scroll wheel, `+`/`-` keys, or on-screen `+`/`-` buttons |
| Center on vessel | Press `C` |

The chart overlay shows the active route with waypoints. The current leg is highlighted in yellow; completed legs are dimmed.

The chart is drawn from two tile layers: an opaque **base map**
(`[tile] base_url`, OpenStreetMap by default — land, water, coastline) with the
transparent **OpenSeaMap seamark overlay** (`[tile] url` — buoys and marks) on
top. Tiles are cached under `tiles/base/` and `tiles/seamark/`. When
`[tile] online` is enabled (the default), any tile not already cached is
downloaded in the background as you pan and zoom — a "downloading map…" badge
appears at the top of the chart while base tiles are in flight. With
`online = false`, only cached tiles are shown, and the chart notes when none
are cached. Set `url = ""` to show only the base map without the seamark
overlay.

### Heading (↗)

Two tabs:

- **Compass** — A compass rose showing magnetic heading, true heading, COG, autopilot target, and waypoint bearing. Each signal has a distinct color.
- **Headings** — A numeric table of all heading-related values with data sources and timestamps.

| Action | Control |
|---|---|
| Adjust heading offset | `[` (decrease) / `]` (increase) by 0.5° |


### Sailing (⛵)

Four tabs:

#### Polars

A polar rose diagram showing theoretical boat speed at various wind angles for the selected true wind speed (TWS). The current boat position is plotted on the polar. Recommended sail is displayed based on current conditions.

- Click on the polar diagram to select TWS, or press `W`/`S` (or `↑`/`↓`)
- Click the TWS buttons in the panel to select TWS
- Press `R` to cycle to the next route

#### Wind

A wind rose showing apparent and true wind vectors. True wind is computed from apparent wind, boat speed, and heading.

#### Log

A sailing log recorder for tracking performance against polar targets.

| Action | Control |
|---|---|
| Start/stop log | Click the button or press `L` |
| Set sailing state | Click the state buttons, or press `1` (sailing), `2` (motoring), `3` (idle) |
| Toggle sails | Click sail buttons (headsail group: Jib/Code0 are exclusive; downwind: Asym) |

The log records polar target percentage, active sails, and sailing state to `heading_log.jsonl`.

#### Route

Displays route waypoints, leg bearings, distances, and computed VMC (velocity made good on course). Allows advancing legs and switching between loaded routes.

| Action | Control |
|---|---|
| Next leg | Click "Next Leg" button or press `N` |
| Previous leg | Press `P` / `B` |
| Cycle route | Click route buttons or press `R` |

Routes are loaded from `.gpx` files placed in the `routes/` directory.

### Replay (⏵)

Plays back a recorded sailing log so you can review a session — the boat,
wind, and polar pages all animate from the logged data as if you were sailing
it live.

The page lists every log found in the sailing-logs directory
(`sailing_logs/` next to the app, or `[paths] log_dir` in
`polarprism.toml`). **Files must be named `sailing_*.jsonl`** — the name
PolarPrism gives them when recording. Click **Play** next to a log to start.
If someone sends you a log file, drop it into that directory and reopen the
page; if the list is empty, the page shows the exact folder it's looking in.

| Action | Control |
|---|---|
| Start playback | Click **Play** next to a file |
| Stop playback | **Stop Replay** button or `Esc` |
| Pause / resume | `Space` |
| Speed up / down | `>` / `<` (1x–20x) |
| Restart from beginning | `R` |
| Scrub timeline | Mouse wheel |

While a replay is running, a status bar at the bottom of the screen shows
play state, the current log time, speed, and progress — visible on every
page, so you can watch the Sailing or Navigation pages during playback.

### Diagnostics (📊)

Two tabs:

- **Values** — Raw Signal K values organized by N2K device, with format-appropriate units
- **NMEA Log** — A scrolling log of recent Signal K delta messages

| Action | Control |
|---|---|
| Scroll NMEA log | Click scroll area or press `Page Up`/`Page Down` |

### Settings (⚙)

Three tabs:

- **SignalK** — Connection status, editable WebSocket URL, vessel name, and discovered N2K device sources. Click the URL to edit it; press Enter to save (written to `polarprism.toml`) and reconnect, or Esc to cancel.
- **Display** — Heading offset value and adjustment controls
- **Setup** — A checklist that walks through connecting Signal K, loading polars, loading a route, configuring sails, and reviewing `polarprism.toml`. Click a section to expand its step-by-step instructions.

## Data Sources

PolarPrism subscribes to the following Signal K paths on startup:

- Navigation heading (magnetic & true)
- Course over ground (true)
- Magnetic variation
- Rate of turn
- Speed over ground & through water
- Rudder angle
- Attitude (roll, pitch, yaw)
- Apparent wind angle & speed
- Course/route bearing & distance
- Vessel position

If a true heading is not provided directly, it is derived from magnetic heading + magnetic variation.

## Polar Diagrams

Polar files are loaded from the `polars/` directory. A sail definition file (`<polar_basename>.saildef`) maps sail numbers to names, and `<polar_basename>.sailselect` defines recommended sail selections by wind range. Each sail has its own polar file (e.g., `MyBoat_Jib.csv`).

> **Sample data:** the repo ships with example polars for a J/105 (US50 ORC
> rating) — `example_J105_BestPerf.csv`, `example_J105_Jib.csv`, etc. These let
> you explore the polar features immediately. They hide automatically once any
> non-`example_` polar CSV exists in `polars/`, so just add your own boat's
> data. See `polars/README.md`.

## Route Files

Drop GPX files into the `routes/` directory. Waypoints are extracted from `<rtept>` elements inside `<route>`. The first route found is selected by default.

> **Sample data:** the repo ships with `example_lake_erie_route.gpx`, the Mills
> Presidents Trophy Course on Lake Erie, as an example. Overwrite it with your
> own course. See `routes/README.md`.

## Importing Raw Signal K Logs

The Signal K server can record raw NMEA 2000 frames to hourly files named
`skserver-raw_YYYY-MM-DDTHH.log`. PolarPrism can convert these into its own
sailing-log JSONL format automatically on startup, so you can replay and
analyze past sessions.

1. Enable raw logging in your Signal K server (it writes
   `skserver-raw_*.log` files to a directory of your choice).
2. Copy (or symlink) those `.log` files into `logs/raw/` (or your configured
   `raw_dir`).
3. In `polarprism.toml`, enable auto-conversion and set your local UTC offset:

   ```toml
   [logging]
   auto_convert_raw = true
   local_tz_offset = -4   # EDT. Use 0 for UTC, +1 for CET, etc.
   ```

4. Launch PolarPrism. Any raw log without a matching `sailing_*.jsonl` in
   `sailing_logs/` is converted automatically; existing outputs are skipped.

For manual one-off conversions (with a specific time range), use the CLI
front-end:

```bash
python log_analysis.py convert --raw-dir logs/raw --tz-offset -4 \
    --date 2026-06-05 --start 05:40 --end 18:30 --output-dir sailing_logs
# or convert the full span of every file:
python log_analysis.py convert --raw-dir logs/raw --tz-offset -4 --full-range
```

---

## Optimizing Your Sailing with Polar Data and Routes

This section walks through how to use PolarPrism to make tactical sailing decisions using your boat's polar data and a loaded course.

### Step 1: Load Your Polar Data

Place your polar CSV files in the `polars/` directory. Each file defines theoretical boat speed at various true wind angles (TWA) and true wind speeds (TWS).

**Polar CSV format** — semicolon- or comma-separated, with TWS values in the header row and TWA values in the first column:

```
TWA\TWS;6;8;10;12;14;16;20;24
31;3.40;4.35;5.10;5.70;6.15;6.35;6.44;6.28
...
180;3.20;4.10;5.00;5.80;6.50;7.10;7.80;7.50
```

Each sail configuration gets its own file (e.g., `MyBoat_Jib.csv`, `MyBoat_Asym.csv`). The first polar loaded becomes active by default. PolarPrism discovers all `.csv` files in `polars/` on startup and loads them automatically.

**Sail definition file** — `<polar_basename>.saildef` maps sail numbers to names:

```
1;Jib
2;Asym
3;Code0
```

If only one `.saildef` exists it applies to all polars; otherwise it is matched to a polar by basename. Sail names drive three things:

- **Sail-to-polar mapping** — built automatically by matching each sail name to a polar whose basename ends with `_<sail>` (case-insensitive), e.g. `Jib` -> `MyBoat_Jib.csv`. Override with `[[sail.polar_map]]` in `polarprism.toml`.
- **Polar display names** — the profile buttons on the Polars page show the sail name (e.g. `1:Jib`) when a polar maps to a sail; otherwise the common filename prefix is stripped. Override the prefix with `[sail] polar_name_prefix`.
- **Sail groups** — if no `[[sail.groups]]` is defined in config, all sails from the saildef go in a single group named `sails`. Define groups explicitly (e.g. `headsail`, `downwind`) in `polarprism.toml` to split them.

**Sail selection file** — `<polar_basename>.sailselect` is a matrix of recommended sail numbers indexed by TWA and TWS, matching the polar's TWA/TWS grid. This enables the "Recommended Sail" display on the Polars page.

### Step 2: Load Your Course

Place a GPX file containing a `<route>` with `<rtept>` waypoints in the `routes/` directory. The coordinates below are illustrative (Lake Erie) — use your own marks:

```xml
<gpx version="1.1" xmlns="http://www.topografix.net/GPX/1/1">
  <route>
    <name>My Race Course</name>
    <rtept lat="41.7617" lon="-83.3283">
      <name>START</name>
    </rtept>
    <rtept lat="41.8217" lon="-83.1950">
      <name>MARK1</name>
    </rtept>
    <rtept lat="41.6633" lon="-82.9733">
      <name>FINISH</name>
    </rtept>
  </route>
</gpx>
```

Routes load automatically on startup. If multiple GPX files exist, click the route name buttons on the **Route** tab or press `R` to cycle between them.

### Step 3: Connect to Signal K

PolarPrism connects to a Signal K server at `ws://localhost:3000/signalk/v1/stream`. Make sure your Signal K server is running and your NMEA 2000 instruments are feeding data. The key inputs are:

- **Apparent wind angle and speed** — from your wind instrument (e.g., iTC5)
- **Speed through water** — from your speed sensor (e.g., DST810)
- **Heading** — magnetic or true heading (e.g., EV-1)
- **Position** — GPS latitude/longitude

Check the **Settings → SignalK** tab to confirm connection status and device sources.

### Step 4: Read the Polar Diagram

Navigate to **Sailing → Polars**. The polar rose shows theoretical boat speed curves for each TWS. Key elements:

| Element | Meaning |
|---|---|
| Colored rings | Speed contours (every 2 kts) |
| Colored lines | Polar speed curves at each TWS; the highlighted line is the active TWS, filled with a translucent polygon |
| Yellow dot | Your current boat speed and TWA (actual performance) |
| Green dot | Polar target speed at current TWA/TWS (what the boat *should* be doing) |
| Purple lines | Course bearing to the next waypoint (port and starboard) |
| Cyan diamonds | Best VMC angle (the TWA that maximizes progress toward the waypoint) |
| Teal circles | Best VMG angles (upwind and downwind) |

Select different TWS columns by clicking the TWS buttons in the panel, clicking the polar diagram, or pressing `W`/`S` (or `↑`/`↓`). Switch between polar profiles by clicking the profile buttons (labeled with sail-derived display names, e.g. `1:Jib`) or pressing `1`/`2`/`3`/`4`. Selecting a sail **does not** change the active polar — set the polar explicitly with the profile buttons. A warning is shown on the Polars panel when the active polar does not match your active sails.

### Step 5: Use the Recommendation Box

The **Recommendation** section at the bottom of the Polars panel is your primary tactical tool. When wind data and a waypoint are available, it computes:

**With an active route (VMC mode):**
- **TACK** or **GYBE** — when the optimal VMC angle is on the opposite tack
- **HEAD UP** — when you should sail closer to the wind to optimize progress
- **BEAR AWAY** — when you should sail lower to optimize progress
- **HOLD** — when you're already on the optimal heading (within 5°)

Each recommendation shows the heading to sail and the resulting VMC in knots. The improvement over your current VMC is shown in parentheses.

**Without a route (VMG mode):**
- Compares your current TWA to the optimal upwind or downwind VMG angle and suggests adjustments if you're more than 10° off.

### Step 6: Use VMC and VMG Data

The **Performance**, **VMG**, and **Waypoint** sections on the Polars panel provide detailed numbers:

| Metric | Meaning |
|---|---|
| **TWA** | Current true wind angle |
| **TWS** | Current true wind speed in knots |
| **Target** | Polar-predicted boat speed at current conditions |
| **Actual** | Your actual speed through water |
| **Perf** | Target percentage (actual/target × 100); green ≥ 95%, red < 80% |
| **1m/5m/10m/30m avg** | Rolling average Perf % over each window, with sample count `(N)` |
| **Up TWA / Up VMG** | Optimal upwind TWA and resulting VMG |
| **Dn TWA / Dn VMG** | Optimal downwind TWA and resulting VMG |
| **WP Brng** | Bearing to the next waypoint, true |
| **Distance** | Distance to the next waypoint (nm, or m when close) |
| **XTE** | Cross-track error from the active leg |
| **Course TWA** | The TWA you'd sail pointing directly at the waypoint |
| **VMC** | Best velocity-made-good on course toward the waypoint |
| **VMC TWA** | The TWA that maximizes VMC |
| **VMC Speed** | Boat speed at the optimal VMC angle |
| **HDG to sail** | The true heading to steer for optimal VMC |
| **SK VMG** | Signal K server's own VMG (if published by instruments) |

The **Recommended Sail** section shows the sail name (color-coded) computed from the `.sailselect` matrix at the current TWA/TWS.

### Step 7: Log Your Sailing

Switch to the **Log** tab to record performance data:

1. **Set your polar profile** — Click the Polar Profile buttons (or press `1`–`4`) to select the polar that matches your current sail configuration. Then **select your sails** — Click sail buttons to mark which sails are set. Within each group only one sail can be active at a time; selecting one deselects the others. Groups come from your `[[sail.groups]]` config, or default to a single `sails` group derived from the `.saildef`.
2. **Set sailing state** — Press `1` for sailing, `2` for motoring, `3` for idle. Performance entries are only written while in the `sailing` state; motoring/idle still log state-change events.
3. **Start the log** — Click "START LOG" or press `L`. This begins recording 1 Hz entries to `sailing_YYYYMMDD_HHMMSS.jsonl` in `sailing_logs/` (configurable via `[paths] log_dir`). Each entry includes position, headings, SOG/STW, TWA/TWS/TWD, AWA/AWS, sailing state, active sails, polar name, target speed, and performance percentage.
4. **Stop the log** — Click "STOP LOG" or press `L` again.

The Polars page shows cumulative `Avg Perf:` on the logging indicator and rolling 1m/5m/10m/30m averages (with sample counts) in the Performance section so you can track whether you're improving.

### Step 8: Track Progress on the Chart

On the **Navigation** page, the active route is overlaid on the chart:

- **Completed legs** are drawn in a dim color
- **The active leg** (current segment) is highlighted in bright yellow
- **The next waypoint** has a glowing halo
- Your vessel position is shown on the chart

Press `C` to re-center the chart on your GPS position. Use scroll or `+`/`-` to zoom in on marks.

### Step 9: Advance Legs

On the **Route** tab, when you round a mark:

- Click **"ADVANCE LEG [N]"** or press `N` to advance to the next waypoint (the button reads **"FINISH"** on the last leg)
- Click **"PREVIOUS LEG [P/B]"** or press `P`/`B` to go back to the previous leg
- The Route tab updates leg bearing, distance, VMC, VMC TWA, VMC speed, and ETA for the new leg

### Putting It All Together: A Typical Race Workflow

1. **Before the start**: Load polar files and GPX course. Confirm Signal K connection on the Settings page.
2. **At the start line**: Select the appropriate polar profile (e.g. Jib for upwind, Asym for downwind — sail names come from your `.saildef`). Start the sailing log.
3. **Upwind leg**: Watch the Polars page. The recommendation will tell you whether to HEAD UP or BEAR AWAY for optimal VMG. Track your performance percentage — green (≥ 95%) means you're sailing to the polar.
4. **Approaching a mark**: The Route tab shows distance and bearing to the next waypoint. When the recommendation says TACK or GYBE with a heading, it's time to maneuver.
5. **Downwind leg**: Switch to the downwind polar (or let VMC guide you). The VMC recommendation accounts for the course to the next mark — it may tell you to sail higher or lower than pure VMG to optimize progress toward the mark.
6. **At the finish**: Stop the log. Review your average performance percentages to see how closely you matched the polar targets.

### Step 10: Build a Measured Polar

PolarPrism can build a **measured polar** from your recorded sailing logs and compare it to your theoretical polar. The pipeline runs entirely offline via the `log_analysis.py` CLI:

```
raw log (skserver-raw_*.log)  --convert-->  sailing log (sailing_*.jsonl)  --polar-->  measured polar CSV + PNG
```

**From a Signal K raw log** (if you run the `skserver-raw` recorder, or if you enable `[logging] auto_convert_raw = true` to import raw logs automatically on startup):

```bash
python log_analysis.py convert --raw-dir logs/raw --tz-offset -4 --full-range --output-dir sailing_logs
# or a specific time window:
python log_analysis.py convert --raw-dir logs/raw --tz-offset -4 \
    --date 2026-06-05 --start 05:40 --end 18:30
```

Raw log filenames use the recorder's local time, so `--tz-offset` (hours) is required (e.g. `-4` for EDT, `+1` for CET, `0` for UTC).

**From a sailing log to a measured polar:**

```bash
python log_analysis.py polar \
    --input sailing_logs/sailing_20260605_054000.jsonl \
    --comparison-polar MyBoat_Jib.csv
```

This bins observed `(TWA, TWS, STW)` samples (TWA every 5° over 30–180°, TWS every 2 kts over 6–30 kts, minimum 3 samples per bin, min STW 2 kts, min AWS 4 kts), fills gaps by inverse-distance interpolation, and writes `Measured.csv` plus `Measured_vs_MyBoat_Jib.png` to `polars/` (or `--output-dir`). Without `--input` the most recent `sailing_logs/*.jsonl` is used; without `--comparison-polar` the first polar in `--polars-dir` is used.

The measured polar CSV is in the same format as theoretical polars, so you can load it as a regular polar to compare your actual performance to the designer's predictions. The comparison PNG requires `matplotlib` (optional `plot` extra in `pyproject.toml`).