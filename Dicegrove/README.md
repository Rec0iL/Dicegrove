# Dicegrove

Multi-color inlay dice and coins for 3D printing from SVG artwork

Pick the die in the header (Coin · d4 · d6 · d8 · d10 · d12 · d20), drop one SVG on each face
field, press **Make**. Faces are numbered like real dice: stacked fields are opposite faces and add
up to sides + 1 (1 ⟷ 6 on a d6); a coin has heads (top) and tails (underneath).

## Install

```bash
./install.sh                 # per-user: ~/.local (menu entry + icon + `dicegrove` command)
./install.sh --link          # per-user, symlinked to this checkout (development)
sudo ./install.sh --system   # system-wide: /usr/local
./uninstall.sh [--system] [--purge]   # --purge also removes settings
```

Requires PySide6 (Fedora/Nobara: `sudo dnf install python3-pyside6`) plus:

```bash
pip install -r requirements.txt
python3 main.py            # or: python3 main.py face1.svg face2.svg ... (fills the faces)
```

## How to use

- **Face fields** - drop an SVG on a field, or click it to pick one. Dropping several SVGs (or a
  folder) on a field fills it and the following faces, sorted by the number in the file names.
  Dropping anywhere else fills the next empty faces. "Open with → Dicegrove" on SVGs does the same.
- **↻** turns a face's image by 90°, **✕** clears it. Empty faces get their number (coin: H / T).
- **Make** queues the die; jobs run one after another with progress, a preview thumbnail and
  "show in folder". A desktop notification tells you when the queue is done.

## What it writes

A folder per die beside your artwork - `crests/` → `crests_d6/` (a single SVG: beside it):

- `1_core_<color>.stl`, `2_color2_<color>.stl` … - one part per filament, all with one origin
- `dice_d6_orca_bambu.3mf` - OrcaSlicer / Bambu Studio: one object, parts already on filaments
- `dice_d6_prusa.3mf` - the same for PrusaSlicer
- `preview.png` - four views; `report.txt` - color table, thin-detail table, warnings

## Settings

**Die**
- *Size* - face to face (coin: diameter); 0 = typical (d4 20, d6/d8/d10 16, d12 18, d20 20, coin 30 mm).
- *Coin thickness* - coins only.
- *Edges* - Sharp, Rounded (even radius) or Classic (corners cut by a sphere); *Rounding radius* for Rounded.
- *Inlay depth* - how deep the colors go; a multiple of your *Layer height* (which is only used for that warning).

**Colors**
- *Max colors* - similar SVG colors merge until this many are left.
- *Core* - shares one SVG color (that color is not cut, the core shows) or gets its own filament;
  *Core = color N* uses the numbers from `report.txt` (1 = largest area).
- *Filament palette* - your real filaments (`#ffffff, #d32f2f`); SVG colors snap to them.
- *White = background* - white areas are not cut.

**Artwork**
- *Image size* - % of the largest size that fits on a face; *Face margin* - distance to the edge.
- *Fit to* - the drawn shapes or the whole SVG page; *Same scale for all SVGs* - for icon sets.
- *Thin details* - strips thinner than *Min feature width*: Merge (join the neighboring color),
  Remove (become core color) or Keep (nothing changed, the report recommends a size).

**Files** - switch the STLs, 3MFs and preview on or off. Output folder (beside the source or a
fixed folder) and rename vs overwrite are under General.

## Terminal

```bash
python3 -m dicegrove.core crests/ --die d6 --size 20 --rotate 3:90
python3 -m dicegrove.core heads.svg tails.svg --die coin --size 35 --separate-core
python3 -m dicegrove.core --die d20                 # numbers only
```
`--help` lists every option (same as the settings).

## Notes

- The dice engine is `dicegrove/engine.py`, a copy of `../dicemaker.py`. After changing the script,
  copy it over again (`cp ../dicemaker.py dicegrove/engine.py`).
- `<text>` in SVGs is ignored - convert text to paths first (Inkscape: Path → Object to Path).
- The face fields (`qml/FaceBoard.qml`, `qml/FaceSlot.qml`) and their hooks in `qml/Main.qml` and
  `dicegrove/backend.py` are hand-written; `/droopy update` re-renders Main.qml and backend.py, so
  re-apply those hooks after an update.

## Files

- Settings live in `~/.config/Dicegrove/settings.json`.
- Shader source: `shaders/bg.frag`. Recompile after editing:
  `qsb-qt6 --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/bg.frag.qsb shaders/bg.frag`
- Tests: `python3 -m unittest tests.test_core`

Generated with `/droopy`; `droopy.json` records the choices so `/droopy update .` can refresh the scaffold.
