# polars/ — Polar Diagram Data

PolarPrism loads every `*.csv` file in this directory as a polar diagram on
startup. The first file (alphabetically) becomes the active polar, and a saved
session may pin a specific one.

## Example data — replace before real use

This directory ships with **example** polars for a J/105 (rated under the US
Sailing ORC "US50" scheme — a sample boat used during development). The
filenames are prefixed `example_` to make it obvious they are samples, not
your boat's data:

- `example_J105_BestPerf.csv` — best-performance composite polar
- `example_J105_Jib.csv` — upwind jib polar
- `example_J105_Code0.csv` — Code 0 reacher polar
- `example_J105_Asym.csv` — asymmetric spinnaker polar
- `example_J105_BestPerf.saildef` — sail-number → sail-name mapping
- `example_J105_BestPerf.sailselect` — recommended sail matrix by TWA/TWS

They let you launch PolarPrism and immediately see how the polar diagram, sail
recommendations, and sail-selection logic behave before you supply your own
boat's data. **Replace these before relying on the app for real navigation.**

## Using your own boat's polars

1. Delete or overwrite the `example_J105_*` files in this directory.
2. Add one CSV per sail configuration (e.g. `MyBoat_Jib.csv`,
   `MyBoat_Asym.csv`). See `manual.md` → "Polar Diagrams" for the CSV format
   (TWA\\TWS header row, semicolon or comma separated).
3. Optionally add a `<polar_basename>.saildef` file with one `number;Name`
   line per sail.
4. Optionally add a `<polar_basename>.sailselect` matrix for the
   "Recommended Sail" feature.
5. Restart PolarPrism. Auto-discovery picks up the new files — no source
   edits required.

Sail groups, sail-to-polar mapping, sail colors, and a polar-name prefix can
also be set explicitly in `polarprism.toml` (see `polarprism.toml.example`).
When omitted, they are derived automatically from the `.saildef` file.