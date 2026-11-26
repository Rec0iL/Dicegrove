"""Dicegrove core: the actual work, with no Qt in it.

One job = one die (or coin). It is described by a small JSON file, a ``.dicejob``:

    {"sides": 6, "faces": ["/art/claws.svg", "", ...], "rotations": [0, 90, ...],
     "home": "/art"}

``faces[k]`` is the SVG for face k+1 ("" = the face gets its number), numbered like a
real die (opposite faces add up to sides+1; coin: 1 = heads/top, 2 = tails/bottom).
The GUI writes one per "Make die" (``write_job``); the CLI builds one from its arguments.

The geometry itself is done by ``engine`` - a copy of ``dicemaker.py`` that is used
unchanged; this module only maps the settings onto its config and reports progress.

Contract used by the GUI:
    SUPPORTED / ACCEPT_DIRS / OPTION_DEFAULTS / expand_inputs() / process() / main()
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

SUPPORTED: set[str] = {".svg"}
ACCEPT_DIRS: bool = False
OPTION_DEFAULTS: dict = {
    "dieType": 6,            # 2 = coin, 4, 6, 8, 10, 12, 20
    "sizeMm": 0.0,           # face to face (coin: diameter); 0 = typical size for the type
    "coinThickness": 3.0,
    "depthMm": 0.4,          # inlay depth
    "maxColors": 4,
    "coreShares": True,      # core is printed in one of the SVG colors
    "coreColorIndex": 1,     # ...this one (number from the color table, 1 = largest area)
    "thinDetails": "merge",  # merge | remove | keep
    "minFeatureMm": 0.4,
    "edges": "minkowski",    # none | minkowski | sphere
    "roundingMm": 1.0,
    "imageScale": 90,        # percent of the largest size that fits a face
    "fitTo": "content",      # content | viewbox
    "uniformScale": False,
    "whiteBackground": False,
    "faceMarginMm": 0.5,
    "layerHeightMm": 0.2,
    "palette": "",           # "#ffffff, #d32f2f, ..." = your filaments, "" = automatic
    "writeStl": True,
    "write3mf": True,
    "writePreview": True,
}

DIE_TYPES = (2, 4, 6, 8, 10, 12, 20)
JOB_SUFFIX = ".dicejob"
if os.name == "nt":  # Windows: %LOCALAPPDATA%\Dicegrove\jobs
    JOB_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Dicegrove" / "jobs"
else:
    JOB_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "Dicegrove" / "jobs"
HEX_RE = re.compile(r"#?[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")

Progress = Callable[[float, str], None]


class CoreError(Exception):
    """A job failed for a reason worth showing to the user."""


class Cancelled(Exception):
    """The job was cancelled (app closing)."""


@dataclass
class Result:
    status: str                    # done | error | skipped
    output: Path | None            # main output (shown, revealed, previewed)
    message: str                   # one line for the job card
    files: list[Path] = field(default_factory=list)   # everything written
    in_place: bool = False         # True if the source itself was modified


def tag_of(sides: int) -> str:
    return "coin" if sides == 2 else f"d{sides}"


# --------------------------------------------------------------------------- inputs
def is_candidate(p: Path) -> bool:
    return p.is_file() and (not SUPPORTED or p.suffix.lower() in SUPPORTED)


def _natural_key(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def face_files(paths: Iterable[str | Path]) -> list[Path]:
    """Dropped files/folders -> SVG files in face order.

    Files keep the order they were given in; a folder contributes its SVGs sorted by the
    number in their names (1.svg, 2.svg ... 10.svg), so a folder of faces fills a die."""
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw).expanduser()
        items = sorted((f for f in p.iterdir() if is_candidate(f)), key=_natural_key) \
            if p.is_dir() else ([p] if is_candidate(p) else [])
        for f in items:
            key = f.resolve()
            if key not in seen:
                seen.add(key)
                out.append(f)
    return out


def write_job(sides: int, faces: list, rotations: list | None = None,
              job_dir: Path | None = None) -> Path:
    """Write a .dicejob for one die and return its path (one folder per job, so the
    file name can stay readable on the job card)."""
    sides = int(sides)
    if sides not in DIE_TYPES:
        raise CoreError(f"Unknown die type {sides} (use {', '.join(map(str, DIE_TYPES))})")
    faces = [str(f) if f else "" for f in list(faces)[:sides]]
    faces += [""] * (sides - len(faces))
    rots = [int(r) % 360 for r in (rotations or [])][:sides]
    rots += [0] * (sides - len(rots))
    first = next((Path(f) for f in faces if f), None)
    home = str(output_home(faces))
    used = sum(1 for f in faces if f)
    if first:
        label = first.stem + (f" +{used - 1}" if used > 1 else "")
    else:
        label = "numbers"
    root = job_dir or JOB_DIR
    _prune_jobs(root)
    d = root / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{tag_of(sides)} · {label}{JOB_SUFFIX}"
    path.write_text(json.dumps({"sides": sides, "faces": faces, "rotations": rots,
                                "home": home}, indent=1), encoding="utf-8")
    return path


JOB_MAX_AGE_DAYS = 30


def _prune_jobs(root: Path) -> None:
    """Job files are tiny, but one is written per die - drop those older than a month."""
    limit = time.time() - JOB_MAX_AGE_DAYS * 86400
    try:
        for d in root.iterdir():
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def expand_inputs(paths: Iterable[str | Path]) -> list[Path]:
    """.dicejob files are jobs as they are. Plain SVGs/folders (CLI, or anything that
    bypasses the face fields) become ONE die in the given order; its type is taken
    from the settings when the job runs."""
    jobs: list[Path] = []
    plain: list[str | Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.suffix == JOB_SUFFIX and p.is_file():
            jobs.append(p)
        else:
            plain.append(raw)
    svgs = face_files(plain)
    if svgs:
        jobs.append(_plain_job(svgs))
    return jobs


def _plain_job(svgs: list[Path]) -> Path:
    path = write_job(20, [str(s) for s in svgs][:20])
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["sides"] = None  # decided by opts["dieType"] when the job runs
    spec["count"] = len(svgs)
    path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return path


def unique_path(path: Path, overwrite: str = "rename") -> Path:
    """`rename` -> name (2).ext, name (3).ext ... ; `overwrite` -> path as given."""
    if overwrite == "overwrite" or not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


# --------------------------------------------------------------------------- settings -> engine
def parse_palette(text: str) -> list[str] | None:
    cols = ["#" + c.lstrip("#").lower() for c in HEX_RE.findall(text or "")]
    return cols or None


def engine_config(engine, opts: dict, sides: int, faces: list[str], rotations: list[int],
                  staging: Path):
    cfg = engine.load_config([])
    cfg.DIE_SIDES = sides
    cfg.DIE_SIZE_MM = float(opts["sizeMm"]) or None
    cfg.COIN_THICKNESS_MM = float(opts["coinThickness"])
    cfg.INLAY_DEPTH_MM = float(opts["depthMm"])
    cfg.LAYER_HEIGHT_MM = float(opts["layerHeightMm"])
    cfg.MAX_COLORS = int(opts["maxColors"])
    cfg.PALETTE = parse_palette(opts["palette"])
    cfg.CORE_SHARES_COLOR = bool(opts["coreShares"])
    cfg.CORE_COLOR_INDEX = int(opts["coreColorIndex"])
    cfg.IGNORE_COLORS = ["#ffffff"] if opts["whiteBackground"] else []
    cfg.FIT_TO = opts["fitTo"]
    cfg.IMAGE_SCALE = float(opts["imageScale"]) / 100.0
    cfg.UNIFORM_SCALE = bool(opts["uniformScale"])
    cfg.FACE_MARGIN_MM = float(opts["faceMarginMm"])
    cfg.MIN_FEATURE_MM = float(opts["minFeatureMm"])
    cfg.THIN_DETAILS = opts["thinDetails"]
    cfg.EDGE_ROUNDING = opts["edges"]
    cfg.ROUNDING_MM = float(opts["roundingMm"])
    cfg.COIN_EDGE_MM = min(0.6, float(opts["roundingMm"])) if opts["edges"] != "none" else 0.0
    cfg.FACE_SVGS = [f or None for f in faces]
    cfg.FACE_ROTATIONS = {k + 1: r for k, r in enumerate(rotations) if r}
    cfg.OUTPUT_DIR = str(staging)
    cfg.WRITE_STL = bool(opts["writeStl"])
    cfg.WRITE_3MF = bool(opts["write3mf"])
    cfg.WRITE_PREVIEW = bool(opts["writePreview"])
    return cfg


GENERIC_DIRS = {"svg", "svgs", "art", "artwork", "faces", "images", "icons", "img"}


def output_name(faces: list[str]) -> str:
    """Name of the output folder (before _d6): the artwork folder if all faces come
    from one folder, else the first SVG's name; generic folder names (svg/, icons/)
    are skipped in favour of the folder above."""
    used = [Path(f) for f in faces if f]
    if not used:
        return "numbers"
    if len(used) > 1 and len({p.parent for p in used}) == 1:
        d = used[0].parent
        if d.name.lower() in GENERIC_DIRS and d.parent.name:
            return f"{d.parent.name}_{d.name}"
        return d.name or used[0].stem
    return used[0].stem


def output_home(faces: list[str]) -> Path:
    """Where the output folder goes: beside the artwork folder when all faces come
    from one folder (crests/ -> crests_d6/ next to it), else beside the first SVG."""
    used = [Path(f) for f in faces if f]
    if not used:
        return Path.home() / "Dicegrove"
    if len(used) > 1 and len({p.parent for p in used}) == 1:
        d = used[0].parent
        if d.name.lower() in GENERIC_DIRS and d.parent.name:
            d = d.parent  # icons/svg/ -> beside icons/
        return d.parent if d.parent != d else d
    return used[0].parent


_ENGINE_LOCK = threading.Lock()

# log lines of the engine -> overall progress
_STAGES = [("DiceMaker:", 0.04, "Reading artwork"), ("Colors", 0.40, "Matching colors"),
           ("Thin details", 0.48, "Cutting parts"), ("Parts", 0.82, "Writing files"),
           ("Written", 0.97, "Finishing")]


# --------------------------------------------------------------------------- the job
def process(src: Path, out_dir: Path, opts: dict, *, progress: Progress | None = None,
            cancel: threading.Event | None = None) -> Result:
    """Build one die/coin from a .dicejob (or a single SVG = face 1)."""
    progress = progress or (lambda f, m: None)
    src = Path(src)
    if not src.exists():
        return Result("error", None, "File not found")
    if src.suffix.lower() == ".svg":
        spec = {"sides": None, "faces": [str(src)], "rotations": [], "home": str(src.parent)}
    elif src.suffix == JOB_SUFFIX:
        try:
            spec = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CoreError(f"Can't read the job file: {exc}") from exc
    else:
        return Result("skipped", None, "Not an SVG or dice job")

    sides = int(spec.get("sides") or opts["dieType"])
    if sides not in DIE_TYPES:
        raise CoreError(f"Unknown die type {sides}")
    faces = [str(f or "") for f in spec.get("faces", [])]
    if spec.get("count", 0) > sides or sum(1 for f in faces[sides:] if f):
        raise CoreError(f"{spec.get('count') or sum(1 for f in faces if f)} SVGs for a "
                        f"{tag_of(sides)} with {sides} faces - pick a bigger die")
    faces = (faces + [""] * sides)[:sides]
    rots = ([int(r) for r in spec.get("rotations", [])] + [0] * sides)[:sides]
    for k, f in enumerate(faces, 1):
        if f and not Path(f).is_file():
            raise CoreError(f"Face {k}: {Path(f).name} not found")
    if not (opts["writeStl"] or opts["write3mf"] or opts["writePreview"]):
        raise CoreError("All outputs are switched off in Settings")

    # where to: next to the artwork, unless the user picked a custom folder
    home = Path(out_dir)
    try:
        if home.resolve() == src.parent.resolve() and src.suffix == JOB_SUFFIX:
            home = Path(spec.get("home") or Path.home() / "Dicegrove")
    except OSError:
        pass
    base = output_name(faces)
    tag = tag_of(sides)
    home.mkdir(parents=True, exist_ok=True)
    final = unique_path(home / f"{base}_{tag}", opts.get("overwrite", "rename"))
    staging = home / f".dicegrove-{uuid.uuid4().hex[:8]}"

    from . import engine  # heavy imports (numpy, manifold3d...) only when a job runs

    log_lines: list[str] = []
    warnings: list[str] = []
    n_faces = [0]

    def on_log(msg: str = "") -> None:
        check(cancel)
        log_lines.append(msg)
        for key, frac, label in _STAGES:
            if msg.strip().startswith(key):
                progress(frac, label)

    def on_warn(msg: str) -> None:
        log_lines.append(f"  ! {msg}")
        warnings.append(msg)

    def wrap_face(fn):
        def inner(*a, **kw):
            check(cancel)
            n_faces[0] += 1
            progress(0.04 + 0.32 * (n_faces[0] - 1) / sides, f"Reading face {n_faces[0]} / {sides}")
            return fn(*a, **kw)
        return inner

    with _ENGINE_LOCK:
        saved = (engine.log, engine.warn, engine.svg_layers, engine.number_layers)
        engine.log, engine.warn = on_log, on_warn
        engine.svg_layers = wrap_face(saved[2])
        engine.number_layers = wrap_face(saved[3])
        try:
            cfg = engine_config(engine, opts, sides, faces, rots, staging)
            parts, _faces, _die, built = engine.make_die(cfg, base_dir=str(home))
        except SystemExit as exc:  # the engine stops with SystemExit("message")
            shutil.rmtree(staging, ignore_errors=True)
            raise CoreError(str(exc)) from None
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            engine.log, engine.warn, engine.svg_layers, engine.number_layers = saved

    # staging/<tag>/ -> final folder
    built = Path(built)
    final.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for f in sorted(built.iterdir()):
        target = final / f.name
        os.replace(f, target)
        files.append(target)
    shutil.rmtree(staging, ignore_errors=True)
    report = final / "report.txt"
    report.write_text("\n".join(log_lines).replace(str(staging / tag), str(final)) + "\n",
                      encoding="utf-8")
    files.append(report)
    progress(1.0, "Done")

    preview = final / "preview.png"
    main_out = preview if preview.exists() else next(
        (f for f in files if f.suffix == ".3mf"), final)
    n_colors = sum(1 for p in parts if p["name"] != "core")
    msg = f"{tag} · {len(parts)} parts · {n_colors} color inlay{'s' if n_colors != 1 else ''}"
    tip = next((w for w in warnings if "scale up" in w), None)
    if tip:
        m = re.search(r"--size (\d+)", tip)
        msg += f" · thin details: try {m.group(1)} mm" if m else " · thin details lost"
    elif n_colors == 0:
        msg += " · no colors cut (all = core color)"
    return Result("done", main_out, msg, files=files)


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    """`python3 -m dicegrove.core face1.svg face2.svg ... --die d6` - terminal use."""
    import argparse
    import sys

    d = OPTION_DEFAULTS
    ap = argparse.ArgumentParser(description="Multi-color inlay dice and coins from SVG artwork. "
                                 "SVGs are faces 1, 2, 3 ... in order (a folder: sorted by number); "
                                 "missing faces get their number.")
    ap.add_argument("paths", nargs="*", help="SVG files / a folder, or .dicejob files")
    ap.add_argument("-o", "--out", help="output folder (default: next to the artwork)")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing output folder")
    ap.add_argument("--die", default=tag_of(d["dieType"]),
                    choices=[tag_of(s) for s in DIE_TYPES], help="die type (default d6)")
    ap.add_argument("--size", type=float, default=d["sizeMm"], help="mm face to face / coin diameter (0 = typical)")
    ap.add_argument("--coin-thickness", type=float, default=d["coinThickness"])
    ap.add_argument("--depth", type=float, default=d["depthMm"], help="inlay depth in mm")
    ap.add_argument("--colors", type=int, default=d["maxColors"], help="max number of colors")
    ap.add_argument("--core-color", type=int, default=d["coreColorIndex"], metavar="N",
                    help="core shares color N")
    ap.add_argument("--separate-core", action="store_true", help="core gets its own filament")
    ap.add_argument("--thin", choices=["merge", "remove", "keep"], default=d["thinDetails"])
    ap.add_argument("--min-feature", type=float, default=d["minFeatureMm"])
    ap.add_argument("--edges", choices=["none", "minkowski", "sphere"], default=d["edges"])
    ap.add_argument("--rounding", type=float, default=d["roundingMm"], help="edge radius in mm")
    ap.add_argument("--image-scale", type=int, default=d["imageScale"], help="percent")
    ap.add_argument("--fit", choices=["content", "viewbox"], default=d["fitTo"])
    ap.add_argument("--uniform-scale", action="store_true")
    ap.add_argument("--white-background", action="store_true")
    ap.add_argument("--margin", type=float, default=d["faceMarginMm"])
    ap.add_argument("--layer-height", type=float, default=d["layerHeightMm"])
    ap.add_argument("--palette", default=d["palette"], help='"#fff,#d32f2f,..." your filaments')
    ap.add_argument("--rotate", action="append", default=[], metavar="FACE:DEG",
                    help="rotate a face's image, e.g. --rotate 3:90 (repeatable)")
    ap.add_argument("--no-stl", action="store_true")
    ap.add_argument("--no-3mf", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args(argv)

    sides = {tag_of(s): s for s in DIE_TYPES}[args.die]
    opts = {**OPTION_DEFAULTS, "dieType": sides, "sizeMm": args.size,
            "coinThickness": args.coin_thickness, "depthMm": args.depth,
            "maxColors": args.colors, "coreShares": not args.separate_core,
            "coreColorIndex": args.core_color, "thinDetails": args.thin,
            "minFeatureMm": args.min_feature, "edges": args.edges, "roundingMm": args.rounding,
            "imageScale": args.image_scale, "fitTo": args.fit, "uniformScale": args.uniform_scale,
            "whiteBackground": args.white_background, "faceMarginMm": args.margin,
            "layerHeightMm": args.layer_height, "palette": args.palette,
            "writeStl": not args.no_stl, "write3mf": not args.no_3mf,
            "writePreview": not args.no_preview,
            "overwrite": "overwrite" if args.overwrite else "rename"}

    jobs = [Path(p) for p in args.paths if p.endswith(JOB_SUFFIX)]
    svgs = face_files([p for p in args.paths if not p.endswith(JOB_SUFFIX)])
    if len(svgs) > sides:
        print(f"{len(svgs)} SVGs but a {args.die} has {sides} faces - pick a bigger --die",
              file=sys.stderr)
        return 1
    if svgs or not jobs:
        rots = [0] * sides
        for r in args.rotate:
            k, _, deg = r.partition(":")
            if k.isdigit() and 1 <= int(k) <= sides:
                rots[int(k) - 1] = int(deg or 90)
        jobs.append(write_job(sides, [str(s) for s in svgs], rots))
    rc = 0
    for p in jobs:
        spec = json.loads(p.read_text(encoding="utf-8"))
        out = Path(args.out) if args.out else Path(spec.get("home") or Path.home() / "Dicegrove")
        try:
            res = process(p, out, opts, progress=lambda f, m: None)
        except CoreError as exc:
            res = Result("error", None, str(exc))
        tag = {"done": "ok  ", "skipped": "skip", "error": "FAIL"}[res.status]
        print(f"[{tag}] {p.stem}: {res.message}" + (f" -> {res.output.parent}" if res.output else ""))
        if res.status == "error":
            rc = 1
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
