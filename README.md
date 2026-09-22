# First Layer Squish for Klipper

An interactive Klipper calibration that prints first-layer patches one at a
time. After each patch, adjust Z from Mainsail, Fluidd, KlipperScreen, the
console, or an optional physical LCD menu, then print the next patch. The
default layout is nine 30 mm squares distributed in a 3x3 grid.

The workflow is based on [Ellis' First Layer Squish guide](https://ellis3dp.com/Print-Tuning-Guide/articles/first_layer_squish.html):
use a reasonably thick first layer, a line width of at least 120% of nozzle
diameter, and inspect solid patches while adjusting Z live.

## Current scope

- Cartesian and CoreXY printers
- Probe/virtual-endstop and dedicated Z-endstop configurations
- Interactive free adjustment rather than a predetermined offset series
- Rectangular perimeters with configurable diagonal solid infill (45° default)
- Configurable temperatures, geometry, extrusion, speeds, and start/end G-code
- Mainsail, Fluidd, and KlipperScreen macro controls
- Optional physical LCD menu
- Remembers the adjustment used for every printed square
- Applies with `Z_OFFSET_APPLY_PROBE` or `Z_OFFSET_APPLY_ENDSTOP`, then runs
  `SAVE_CONFIG`

## Installation

Clone this repository beside your other Klipper add-ons and run:

```bash
./scripts/install.sh
```

Alternatively, symlink `klippy/extras/first_layer_squish.py` into
`~/klipper/klippy/extras/first_layer_squish.py`.

Copy `config/first_layer_squish.cfg` into the printer configuration directory,
customize its `start_gcode`, and add this to `printer.cfg`:

```ini
[include first_layer_squish.cfg]
```

For a physical LCD, also copy and include
`config/first_layer_squish_menu.cfg`.

Because this add-on installs Python code, restart the **Klipper system service**
after installing or updating it:

```bash
sudo systemctl restart klipper
```

`RESTART` and `FIRMWARE_RESTART` reload printer configuration inside the
existing Python process and may continue using an already-imported version of
the add-on.

The example start G-code heats and homes the printer. Most CoreXY machines
should customize it to call their normal gantry-leveling, probe-docking, mesh,
and heat-soak routines. Calibration refuses to begin unless XYZ are homed when
the start G-code finishes.

## Usage

1. Clean the build surface and run `FIRST_LAYER_SQUISH`.
2. Inspect the first patch.
3. Run `SQUISH_MORE Z=0.01` to lower the nozzle or
   `SQUISH_LESS Z=0.01` to raise it.
4. Run `SQUISH_NEXT` and repeat.
5. If an earlier patch was best, run `SQUISH_SELECT SQUARE=6` (for example).
6. Run `SQUISH_ACCEPT`. The plugin applies the appropriate probe/endstop offset,
   executes `SAVE_CONFIG`, and Klipper restarts.

Run `SQUISH_ABORT` at any time to restore the original live offset. The default
maximum adjustment in either direction is 0.5 mm.

Start-time overrides are supported, for example:

```gcode
FIRST_LAYER_SQUISH BED_TEMP=105 EXTRUDER_TEMP=245 SIZE=25 FLOW=0.98 INFILL_ANGLE=45
```

Negative Z adjustment means more squish, matching Klipper's
`SET_GCODE_OFFSET Z_ADJUST=...` convention.

## Moonraker update manager

After choosing a permanent checkout path, this optional Moonraker section lets
the repository update with the rest of the printer software:

```ini
[update_manager first-layer-squish]
type: git_repo
path: ~/first-layer-squish-klipper-calibration
origin: https://github.com/YOUR_ACCOUNT/first-layer-squish-klipper-calibration.git
primary_branch: main
managed_services: klipper
```

## Development

The geometry and extrusion tests use Python's standard test runner:

```bash
python -m unittest discover -s tests -v
```

## Safety

Watch the first run closely and keep emergency-stop access available. Verify
bed bounds, temperatures, start G-code, and Z direction before allowing the
printer to continue through all nine patches.
