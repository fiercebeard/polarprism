# PolarPrism

A real-time sailing navigation instrument built with pygame and asyncio. It
connects to a [Signal K](https://signalk.org) server over WebSocket and
displays heading, wind, polar performance, route progress, and nautical
charts — for use as a tactical instrument on board.

![pages](https://img.shields.io/badge/pages-heading%20%7C%20sailing%20%7C%20navigation%20%7C%20diagnostics%20%7C%20settings-blue)

## Features

- Compass, true/magnetic heading, COG, autopilot target, waypoint bearing
- True-wind computation from apparent wind + boat speed + heading
- Polar rose diagram with VMG / VMC recommendations and target performance
- Wind rose (apparent + true)
- Route tracking from GPX files (bearing, distance, VMC, ETA, leg advance)
- Tile-based nautical chart with OpenSeaMap seamarks, online tile fetching
- Sailing performance logger (1m / 5m / 10m / 30m windows)
- Signal K connection status, N2K device discovery
- In-app editing of the Signal K URL (written to `polarprism.toml`)
- Auto-import of raw Signal K server logs on startup

## Requirements

- Python **3.11+**
- A running Signal K server (default `ws://localhost:3000/signalk/v1/stream`)
- NMEA 2000 instruments feeding Signal K (wind, speed, heading, GPS)

### Runtime dependencies

`pygame`, `aiofiles`, `websockets`, `nmea2000` (installed automatically).

Optional extras:

```bash
pip install -e ".[config]"   # tomli_w — for writing polarprism.toml from the UI
pip install -e ".[plot]"     # matplotlib — for the measured-polar comparison plot
pip install -e ".[dev]"      # pytest, ruff, mypy
```

Without `tomli_w`, the in-app URL editor falls back to writing a JSON file
(`polarprism.json`) instead of TOML.

## Quickstart

```bash
git clone <this-repo> polarprism
cd polarprism
pip install -e .

# Configure (optional but recommended on first run):
cp polarprism.toml.example polarprism.toml
# edit polarprism.toml -> [signalk] url and [chart] default_lat/lon/zoom

python main.py
# or, after install:
polarprism
```

> **Note on defaults:** the shipped chart default opens on **Lake Erie**
> (a sample location used during development). Override `[chart]` in your
> `polarprism.toml` to center on your own waters, or press `C` in the app to
> snap to your GPS position.

The app also ships with **example polars** for a J/105 (US50 ORC rating) in
`polars/` (filenames prefixed `example_`) and an **example route** (the Mills
Trophy course on Lake Erie) in `routes/`. These let you explore every feature
immediately. The example polars **hide automatically** once you add your own
polar CSV to `polars/` — no need to delete them. See `polars/README.md` and
`routes/README.md`.

## Configuration

All configuration is optional and lives in `polarprism.toml` (in the project
directory or `~/.config/polarprism/`). CLI flags override config:

```bash
python main.py --signalk-url ws://192.168.1.100:3000/signalk/v1/stream
python main.py --config /path/to/polarprism.toml
python main.py --polars-dir /path/to/polars --routes-dir /path/to/routes
```

See `polarprism.toml.example` for every option, including `[signalk]`,
`[chart]`, `[paths]`, `[display]`, `[tile]`, `[logging]`, and `[sail.*]`.

You can also edit the Signal K URL from inside the app: **Settings → SignalK
tab → click the URL field**. Enter saves (and reconnects); Esc cancels.

### Auto-discovery

Polar files, sail definitions, sail selection matrices, and routes are all
discovered automatically — no source edits are needed for a new boat:

- **Polars**: every `*.csv` in `polars/` is loaded; the first becomes active.
- **Sail definitions**: `*.saildef` files in `polars/` map sail numbers to
  names. If one matches the first polar's basename, it's used.
- **Sail selection**: `*.sailselect` files are auto-discovered similarly.
- **Routes**: every `*.gpx` in `routes/` is loaded; the first becomes active.
- **Sail groups / colors / polar display names**: derived automatically from
  the `.saildef` file, or overridden in `polarprism.toml`.

Just drop your files in `polars/` and `routes/` and restart.

## Importing raw Signal K logs

The Signal K server can record raw NMEA 2000 frames to `skserver-raw_*.log`
files. PolarPrism can convert these into its sailing-log JSONL format
automatically on startup:

1. Copy your `skserver-raw_*.log` files into `logs/raw/`.
2. In `polarprism.toml`:

   ```toml
   [logging]
   auto_convert_raw = true
   local_tz_offset = -4   # your UTC offset (EDT = -4, CET = +1, UTC = 0)
   ```

3. Launch PolarPrism. New raw logs are converted; existing outputs are skipped.

For manual one-off conversions with a specific time range, see
`log_analysis.py convert --help`. To build a measured polar from a sailing log
and compare it to a theoretical polar, see `log_analysis.py polar --help`. Both
subcommands are generic tools (no boat-specific defaults).

## Documentation

- `manual.md` — full user manual (interface, pages, controls, polar format,
  route files, raw-log import, race workflow)
- `polars/README.md`, `routes/README.md` — sample-data notes and file formats

## Development

```bash
ruff check .
ruff format --check .
mypy boatpolars/ signalk/ routes/ chart/ config.py
pytest tests/ -v
```

> **Note:** the Python polar/coverage code lives in the `boatpolars/` package.
> The `polars/` directory is a *data* folder (example CSVs, `.saildef`), not an
> importable package — this avoids a name clash with the PyPI `polars` library.

## State persistence

Per-user state (heading offset, active polar, route progress, chart position,
last-used Signal K URL) is saved to `~/.local/share/polarprism/state.json` on
exit and restored on startup. This is per-user, not in the repo.

## License

TBD — add a LICENSE file before public release.