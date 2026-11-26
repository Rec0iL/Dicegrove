#!/usr/bin/env python3
"""
DiceMaker - multi-color inlay dice for 3D printing, made from SVG files.

Every face gets one SVG. The colors of all SVGs are collected, merged down to
MAX_COLORS filaments, and the die is split into parts that fit together exactly:

    part 1   die core  (with pockets INLAY_DEPTH_MM deep where the colors go)
    part 2+  one inlay part per color (fills the pockets flush with the surface)

All parts share one origin. Load them in the slicer as ONE object with several
parts (the .3mf already is one) and give every part its filament.

Usage:
    python dicemaker.py                          # uses the CONFIG below
    python dicemaker.py --sides 20               # d20, faces without SVG get numbers
    python dicemaker.py --sides 6 --svgs a.svg b.svg c.svg d.svg e.svg f.svg
    python dicemaker.py --svgs path/to/folder    # 1.svg, 2.svg, ... in that folder

Needs: numpy scipy shapely>=2 manifold3d svgelements trimesh matplotlib pillow
"""

# =============================================================================
#  CONFIG  - change things here (command-line options override some of them)
# =============================================================================

DIE_SIDES = 6            # 4, 6, 8, 10, 12 or 20 - or 2 for a COIN (heads / tails)
DIE_SIZE_MM = None       # mm, distance face to opposite face (d4: height base -> tip)
                         # None = typical size: d4 20, d6 16, d8 16, d10 16, d12 18, d20 20
                         # coin: the diameter (None = 30)

# One entry per face, in face-number order (face 1 first).
#  - a path to an .svg file
#  - None  -> the face number is generated as text (NUMBER_* settings below)
# Can also be a folder path (string): its SVGs are used sorted by the number in
# their file name (1.svg, 2.svg, ... / face_01.svg ...).
FACE_SVGS = [
    "examples/d6/1.svg",
    "examples/d6/2.svg",
    "examples/d6/3.svg",
    "examples/d6/4.svg",
    "examples/d6/5.svg",
    "examples/d6/6.svg",
]

# --- colors / parts ----------------------------------------------------------
INLAY_DEPTH_MM = 0.4     # how deep the colors are cut into the core
LAYER_HEIGHT_MM = 0.2    # only used to warn when the depth is not a multiple of it
MAX_COLORS = 4           # SVG colors are merged down to this many (similar ones join)
PALETTE = None           # e.g. ["#ffffff", "#d32f2f", "#212121", "#1e88e5"]:
                         # every SVG color snaps to the nearest of YOUR filaments,
                         # color numbers are then the palette positions (1 = first)
CORE_SHARES_COLOR = True # True: the core is printed in one of the SVG colors,
                         #       that color is not cut out (the core shows through)
CORE_COLOR_INDEX = 1     # which color the core shares (number from the color table
                         # the script prints; without PALETTE 1 = largest area)
CORE_COLOR = "#f0f0f0"   # core preview color when CORE_SHARES_COLOR = False
IGNORE_COLORS = []       # SVG colors to treat as "background" (core shows there),
                         # e.g. ["#ffffff"] for a white background rectangle

# --- image placement ---------------------------------------------------------
FIT_TO = "content"       # "content": scale the drawn shapes to fill the face
                         # "viewbox": scale the whole SVG page (keeps your framing)
IMAGE_SCALE = 0.90       # 1.0 = as large as fits inside the flat face area
UNIFORM_SCALE = False    # True: all SVGs get the same mm-per-SVG-unit (useful when
                         # they share one viewBox / icon set); auto numbers always do
FACE_MARGIN_MM = 0.5     # keep this distance from the face edge / rounding
FACE_ROTATIONS = {}      # extra rotation per face in degrees, e.g. {3: 90, 5: -45}
MIN_FEATURE_MM = 0.4     # details thinner than this are removed (nozzle width),
                         # 0 = keep everything
THIN_DETAILS = "merge"   # what happens to a color strip thinner than MIN_FEATURE_MM:
                         # "merge"  -> it joins the neighboring color (keeps the shape)
                         # "remove" -> it becomes core color
                         # "keep"   -> nothing is filtered, you only get a warning
                         #             with the die size at which it would print
INCLUDE_STROKES = True   # turn SVG strokes (outlines/lines) into areas too

# --- die shape ---------------------------------------------------------------
EDGE_ROUNDING = "minkowski"   # "none", "minkowski" (round edges and corners)
                              # or "sphere" (classic die: cube cut by a sphere)
ROUNDING_MM = 1.0             # edge radius for "minkowski"
SPHERE_FACTOR = 0.90          # "sphere": sphere radius as share of corner radius
OPPOSITE_SUM = True           # opposite faces add up to sides+1 (not for d4)

# --- coin (DIE_SIDES = 2, DIE_SIZE_MM = diameter) -------------------------------
COIN_THICKNESS_MM = 3.0       # total thickness
COIN_EDGE_MM = 0.6            # rounding of the coin edge (0 = sharp)
COIN_LABELS = ["H", "T"]      # text for a coin side without SVG (heads, tails)

# --- auto numbers (faces with None) -------------------------------------------
NUMBER_COLOR = "#202020"
NUMBER_FONT = "DejaVu Sans"   # any font matplotlib can find
NUMBER_DOT_6_9 = True         # "6." and "9." so they can be told apart

# --- output ------------------------------------------------------------------
OUTPUT_DIR = "out"
WRITE_STL = True
WRITE_3MF = True
WRITE_PREVIEW = True
DENSITY_G_CM3 = 1.24          # for the filament weight estimate (PLA = 1.24)

# =============================================================================
#  end of CONFIG
# =============================================================================

import argparse
import itertools
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import manifold3d as mf
import shapely
from shapely import affinity
from shapely.geometry import LineString, LinearRing, Polygon, MultiPolygon, Point
from shapely.ops import polygonize, unary_union
import svgelements as se
from scipy.spatial import ConvexHull

PHI = (1 + 5 ** 0.5) / 2
PINCH_HOLE_MM = 0.02  # hole radius where regions touch in one point
GRID_MM = 0.001  # 2D regions are snapped to this grid before they become 3D
EPS_UP = 0.05  # cutters reach this far above the surface (avoids coplanar cuts)


def log(msg=""):
    print(msg, flush=True)


def warn(msg):
    print(f"  ! {msg}", flush=True)


# -----------------------------------------------------------------------------
#  small helpers
# -----------------------------------------------------------------------------

def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def rotation_between(a, b):
    """Rotation matrix that turns unit vector a onto unit vector b."""
    a, b = unit(a), unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        if c > 0:
            return np.eye(3)
        axis = unit(np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0]))
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def polys_only(g):
    """All polygons of a geometry as a list (drops lines/points)."""
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    if hasattr(g, "geoms"):
        out = []
        for x in g.geoms:
            out += polys_only(x)
        return out
    return []


def as_area(g):
    ps = polys_only(g)
    if not ps:
        return Polygon()
    return unary_union(ps) if len(ps) > 1 else ps[0]


def hex_of(rgb):
    return "#%02x%02x%02x" % tuple(int(round(max(0, min(255, c)))) for c in rgb)


def rgb_of(hexstr):
    c = se.Color(hexstr)
    return (c.red, c.green, c.blue)


def lab_of(hexstr):
    """sRGB hex -> CIELAB (D65); used to judge how similar two colors look."""
    rgb = np.array(rgb_of(hexstr), float) / 255
    rgb = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]])
    xyz = m @ rgb / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def norm_hex(c):
    try:
        col = se.Color(c)
        return hex_of((col.red, col.green, col.blue))
    except Exception:
        return None


# -----------------------------------------------------------------------------
#  die geometry
# -----------------------------------------------------------------------------

def die_vertices(sides):
    if sides == 4:
        v = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
    elif sides == 6:
        v = list(itertools.product([-1, 1], repeat=3))
    elif sides == 8:
        v = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    elif sides == 10:
        # pentagonal trapezohedron; H chosen so the kite faces are flat
        z0 = 0.1056
        c = math.cos(math.pi / 5)
        H = z0 * (1 + c) / (1 - c)
        v = [(0, 0, H), (0, 0, -H)]
        v += [(math.cos(k * math.pi / 5), math.sin(k * math.pi / 5),
               z0 if k % 2 == 0 else -z0) for k in range(10)]
    elif sides == 12:
        v = list(itertools.product([-1, 1], repeat=3))
        for a, b in itertools.product([-1, 1], repeat=2):
            v += [(0, a / PHI, b * PHI), (a / PHI, b * PHI, 0), (b * PHI, 0, a / PHI)]
    elif sides == 20:
        v = []
        for a, b in itertools.product([-1, 1], repeat=2):
            v += [(0, a, b * PHI), (a, b * PHI, 0), (b * PHI, 0, a)]
    else:
        raise SystemExit(f"DIE_SIDES must be 2 (coin), 4, 6, 8, 10, 12 or 20 (got {sides})")
    return np.array(v, float)


def hull_faces(V):
    """Planar faces of a convex point set: list of (normal, offset, ordered vertex idx)."""
    hull = ConvexHull(V)
    scale = np.abs(V).max()
    faces, seen = [], []
    for eq in hull.equations:
        n = unit(eq[:3])
        if any(np.dot(n, s) > 1 - 1e-6 for s in seen):
            continue
        seen.append(n)
        h = -eq[3] / np.linalg.norm(eq[:3])
        idx = np.where(np.abs(V @ n - h) < 1e-6 * scale)[0]
        c = V[idx].mean(0)
        e1 = unit(V[idx[0]] - c)
        e2 = np.cross(n, e1)
        ang = [math.atan2(np.dot(V[i] - c, e2), np.dot(V[i] - c, e1)) for i in idx]
        faces.append((n, h, idx[np.argsort(ang)]))
    return faces


class Face:
    pass


def build_geometry(cfg):
    """Die vertices (scaled, one face down), faces with frames and numbers."""
    sides = cfg.DIE_SIDES
    V = die_vertices(sides)
    faces = hull_faces(V)
    if len(faces) != sides:
        raise RuntimeError(f"expected {sides} faces, got {len(faces)}")

    # put a face on the print bed (-Z)
    lowest = min(faces, key=lambda f: f[0][2])
    R = rotation_between(lowest[0], [0, 0, -1])
    V = V @ R.T
    faces = hull_faces(V)

    inr = min(f[1] for f in faces)
    target = cfg.DIE_SIZE_MM / (4 if sides == 4 else 2)
    V = V * (target / inr)
    faces = hull_faces(V)
    inr = min(f[1] for f in faces)
    circ = float(np.linalg.norm(V, axis=1).max())

    out = []
    for n, h, idx in faces:
        f = Face()
        f.n, f.h = n, h
        f.verts = V[idx]
        f.foot = n * h
        out.append(f)

    # face numbers: opposite faces add up to sides + 1
    order = sorted(range(len(out)), key=lambda i: (round(-out[i].n[2], 4),
                                                   math.atan2(out[i].n[1], out[i].n[0])))
    if cfg.OPPOSITE_SUM and sides != 4:
        nxt = 1
        for i in order:
            f = out[i]
            if hasattr(f, "number"):
                continue
            opp = max(out, key=lambda g: -np.dot(g.n, f.n))
            f.number, opp.number = nxt, sides + 1 - nxt
            nxt += 1
    else:
        for k, i in enumerate(order):
            out[i].number = k + 1
    out.sort(key=lambda f: f.number)

    # face frames: u = image "up", r = image "right", n = out of the face
    up_mode = "edge" if sides == 6 else "vertex"
    for f in out:
        ref = np.array([0.0, 0.0, 1.0])
        proj = ref - np.dot(ref, f.n) * f.n
        if np.linalg.norm(proj) < 1e-3:
            ref = np.array([0.0, 1.0, 0.0])
            proj = ref - np.dot(ref, f.n) * f.n
        proj = unit(proj)
        if up_mode == "edge":
            cand = (f.verts + np.roll(f.verts, -1, axis=0)) / 2
        else:
            cand = f.verts
        dirs = np.array([unit(c - f.foot) for c in cand])
        u = dirs[int(np.argmax(dirs @ proj))]
        rot = math.radians(cfg.FACE_ROTATIONS.get(f.number, 0))
        u = unit(u * math.cos(rot) + np.cross(f.n, u) * math.sin(rot))
        f.u = u
        f.r = np.cross(u, f.n)
        f.poly = Polygon([(np.dot(p - f.foot, f.r), np.dot(p - f.foot, f.u)) for p in f.verts])
    return V, out, inr, circ


def build_die(V, faces, inr, circ, cfg):
    """The die solid (Manifold) and the flat part of every face (2D, face frame)."""
    mode = (cfg.EDGE_ROUNDING or "none").lower()
    if mode == "minkowski" and cfg.ROUNDING_MM > 0:
        r = min(cfg.ROUNDING_MM, inr * 0.5)
        k = (inr - r) / inr
        sph = mf.Manifold.sphere(r, 48).to_mesh().vert_properties[:, :3]
        pts = [(V * k)[:, None, :] + sph[None, :, :]]
        # exact points on every face plane, so the flat faces stay exactly at inr
        for f in faces:
            pts.append((f.verts * k + f.n * r)[None])
        die = mf.Manifold.hull_points(np.concatenate([p.reshape(-1, 3) for p in pts]))
        for f in faces:
            f.flat = affinity.scale(f.poly, k, k, origin=(0, 0))
    elif mode == "sphere":
        R = max(cfg.SPHERE_FACTOR * circ, inr * 1.02)
        die = mf.Manifold.hull_points(V) ^ mf.Manifold.sphere(R, 160)
        disk = Point(0, 0).buffer(math.sqrt(R * R - inr * inr), 128)
        for f in faces:
            f.flat = f.poly.intersection(disk)
    else:
        die = mf.Manifold.hull_points(V)
        for f in faces:
            f.flat = f.poly
    return die


def build_coin(cfg):
    """Coin: a disc with a rounded edge; face 1 = top (heads), face 2 = bottom."""
    R = cfg.DIE_SIZE_MM / 2
    t = cfg.COIN_THICKNESS_MM
    if 2 * cfg.INLAY_DEPTH_MM >= 0.8 * t:
        raise SystemExit(f"COIN_THICKNESS_MM {t} is too thin for two inlays of "
                         f"{cfg.INLAY_DEPTH_MM} mm")
    r = max(0.0, min(cfg.COIN_EDGE_MM, 0.45 * t, 0.5 * R))
    if r > 0:
        prof = unary_union([
            shapely.box(0, -t / 2, R - r, t / 2),
            shapely.box(0, -t / 2 + r, R, t / 2 - r),
            Point(R - r, t / 2 - r).buffer(r, 32),
            Point(R - r, -t / 2 + r).buffer(r, 32)])
        prof = as_area(prof.intersection(shapely.box(0, -t, 2 * R, t)))
    else:
        prof = shapely.box(0, -t / 2, R, t / 2)
    die = mf.Manifold.revolve(cross_section(prof), 256)
    faces = []
    for number, n in ((1, np.array([0.0, 0, 1])), (2, np.array([0.0, 0, -1]))):
        f = Face()
        f.n, f.h, f.number = n, t / 2, number
        f.foot = n * f.h
        u = np.array([0.0, 1.0, 0.0])
        rot = math.radians(cfg.FACE_ROTATIONS.get(number, 0))
        f.u = unit(u * math.cos(rot) + np.cross(n, u) * math.sin(rot))
        f.r = np.cross(f.u, n)
        f.poly = Point(0, 0).buffer(R, 256)
        f.flat = Point(0, 0).buffer(R - r, 256)
        faces.append(f)
    return die, faces


# -----------------------------------------------------------------------------
#  SVG -> colored 2D regions
# -----------------------------------------------------------------------------

def winding_number(px, py, ring):
    x0, y0 = ring[:, 0], ring[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    cross = (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)
    up = (y0 <= py) & (y1 > py) & (cross > 0)
    down = (y0 > py) & (y1 <= py) & (cross < 0)
    return int(up.sum()) - int(down.sum())


def fill_area(rings, rule="nonzero"):
    """Closed rings + SVG fill rule -> shapely area. Handles holes and self-overlap."""
    rings = [r for r in rings if len(r) >= 3]
    if not rings:
        return Polygon()
    if len(rings) == 1:
        p = Polygon(rings[0])
        if p.is_valid:
            return p
    lines = [LineString(np.vstack([r, r[:1]])) for r in rings]
    noded = unary_union(lines)
    keep = []
    for face in polygonize(noded):
        pt = face.representative_point()
        w = sum(winding_number(pt.x, pt.y, r) for r in rings)
        if (w % 2 == 1) if rule == "evenodd" else (w != 0):
            keep.append(face)
    return as_area(unary_union(keep)) if keep else Polygon()


def linearize(path, seg_len):
    """svgelements Path -> list of (Nx2 points, closed)."""
    out = []
    pts, closed = [], False

    def flush():
        nonlocal pts, closed
        if len(pts) >= 2:
            a = np.array(pts, float)
            keep = np.ones(len(a), bool)
            keep[1:] = np.any(np.abs(np.diff(a, axis=0)) > 1e-9, axis=1)
            a = a[keep]
            if closed and len(a) > 2 and np.allclose(a[0], a[-1]):
                a = a[:-1]
            out.append((a, closed))
        pts, closed = [], False

    for seg in path:
        if isinstance(seg, se.Move):
            flush()
            if seg.end is not None:
                pts = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, se.Close):
            closed = True
            flush()
        elif isinstance(seg, se.Line):
            if not pts and seg.start is not None:
                pts = [(seg.start.x, seg.start.y)]
            pts.append((seg.end.x, seg.end.y))
        else:  # curves
            if not pts and seg.start is not None:
                pts = [(seg.start.x, seg.start.y)]
            probe = np.linspace(0, 1, 9)
            try:
                pp = np.asarray(seg.npoint(probe), float)
            except Exception:
                pp = np.array([(p.x, p.y) for p in (seg.point(t) for t in probe)])
            length = float(np.linalg.norm(np.diff(pp, axis=0), axis=1).sum())
            n = int(min(256, max(4, math.ceil(length / seg_len))))
            ts = np.linspace(0, 1, n + 1)[1:]
            try:
                arr = np.asarray(seg.npoint(ts), float)
            except Exception:
                arr = np.array([(p.x, p.y) for p in (seg.point(t) for t in ts)])
            pts.extend(map(tuple, arr))
    flush()
    return out


def read_gradients(path):
    """id -> average stop color (hex) for linear/radial gradients."""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}
    stops, hrefs = {}, {}
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("linearGradient", "radialGradient"):
            continue
        gid = el.get("id")
        if not gid:
            continue
        href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href")
        if href:
            hrefs[gid] = href.lstrip("#")
        cols = []
        for s in el:
            if s.tag.split("}")[-1] != "stop":
                continue
            col = s.get("stop-color")
            style = s.get("style") or ""
            m = re.search(r"stop-color\s*:\s*([^;]+)", style)
            if m:
                col = m.group(1).strip()
            h = norm_hex(col or "#000000")
            if h:
                cols.append(rgb_of(h))
        stops[gid] = cols
    out = {}
    for gid in stops:
        g, cols, depth = gid, stops[gid], 0
        while not cols and g in hrefs and depth < 10:
            g = hrefs[g]
            cols = stops.get(g, [])
            depth += 1
        if cols:
            out[gid] = hex_of(np.mean(cols, axis=0))
    return out


def paint_color(e, attr, grads):
    raw = e.values.get(attr)
    if isinstance(raw, str) and raw.strip().startswith("url("):
        m = re.search(r"#([^)\s'\"]+)", raw)
        gid = m.group(1) if m else None
        if gid in grads:
            return grads[gid]
        warn(f"unknown paint {raw!r}, using gray")
        return "#808080"
    c = e.fill if attr == "fill" else e.stroke
    if c is None or c.value is None or c.alpha == 0:
        return None
    for key in (f"{attr}-opacity", "opacity"):
        try:
            if float(e.values.get(key, 1)) < 0.05:
                return None
        except (TypeError, ValueError):
            pass
    return hex_of((c.red, c.green, c.blue))


CAPS = {"butt": "flat", "round": "round", "square": "square"}
JOINS = {"miter": "mitre", "round": "round", "bevel": "bevel"}


def svg_layers(path, cfg):
    """Read an SVG -> (list of (area, hex) in drawing order, page rectangle). Y is up."""
    doc = se.SVG.parse(path, reify=True)
    grads = read_gradients(path)
    try:
        page = (0.0, 0.0, float(doc.width), float(doc.height))
    except Exception:
        page = None
    bb = doc.bbox()
    size = max((bb[2] - bb[0]) if bb else 0, (bb[3] - bb[1]) if bb else 0,
               max(page[2], page[3]) if page else 0, 1e-6)
    seg_len = size / 200
    layers, text_warned = [], False
    for e in doc.elements():
        if isinstance(e, se.Text) and not text_warned:
            warn(f"{os.path.basename(path)}: <text> is ignored - convert text to paths "
                 "(Inkscape: Path > Object to Path)")
            text_warned = True
            continue
        if not isinstance(e, se.Shape):
            continue
        if e.values.get("visibility") in ("hidden", "collapse") or \
                e.values.get("display") == "none":
            continue
        try:
            p = abs(se.Path(e))
        except Exception:
            continue
        subs = linearize(p, seg_len)
        if not subs:
            continue
        fill = paint_color(e, "fill", grads)
        if fill:
            rule = str(e.values.get("fill-rule", "nonzero")).strip()
            a = fill_area([s for s, _ in subs], rule)
            if not a.is_empty:
                layers.append((a, fill))
        stroke = paint_color(e, "stroke", grads) if cfg.INCLUDE_STROKES else None
        if stroke:
            try:
                w = float(e.implicit_stroke_width)
            except Exception:
                w = float(e.stroke_width or 1)
            if w > 0:
                cap = CAPS.get(str(e.values.get("stroke-linecap", "butt")), "flat")
                join = JOINS.get(str(e.values.get("stroke-linejoin", "miter")), "mitre")
                geoms = []
                for s, closed in subs:
                    if len(s) < 2:
                        continue
                    line = LinearRing(s) if closed and len(s) >= 3 else LineString(s)
                    geoms.append(line.buffer(w / 2, cap_style=cap, join_style=join,
                                             mitre_limit=4))
                a = as_area(unary_union(geoms))
                if not a.is_empty:
                    layers.append((a, stroke))
    flip = lambda g: affinity.scale(g, 1, -1, origin=(0, 0))
    layers = [(flip(a), c) for a, c in layers]
    frame = None
    if page:
        frame = flip(Polygon([(page[0], page[1]), (page[2], page[1]),
                              (page[2], page[3]), (page[0], page[3])]))
    return layers, frame


def number_layers(num, cfg):
    """Face number as text outline (for faces without SVG)."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    text = str(num)
    if cfg.DIE_SIDES == 2:
        labels = list(cfg.COIN_LABELS or [])
        text = labels[num - 1] if num <= len(labels) else str(num)
    if cfg.NUMBER_DOT_6_9 and num in (6, 9) and cfg.DIE_SIDES >= 9:
        text += "."
    tp = TextPath((0, 0), text, size=100,
                  prop=FontProperties(family=cfg.NUMBER_FONT, weight="bold"))
    rings = [np.asarray(r, float) for r in tp.to_polygons(closed_only=True)]
    rings = [r[:-1] if len(r) > 3 and np.allclose(r[0], r[-1]) else r for r in rings]
    return [(fill_area(rings, "nonzero"), norm_hex(cfg.NUMBER_COLOR))], None


def visible_by_color(layers, ignore):
    """Painter's algorithm: what is left visible of each shape, merged per color."""
    covered, res = None, defaultdict(list)
    for geom, col in reversed(layers):
        geom = as_area(geom if geom.is_valid else geom.buffer(0))
        if geom.is_empty:
            continue
        vis = geom if covered is None else as_area(geom.difference(covered))
        covered = geom if covered is None else covered.union(geom)
        if not vis.is_empty and col not in ignore:
            res[col].append(vis)
    return {c: as_area(unary_union(g)) for c, g in res.items()}


# -----------------------------------------------------------------------------
#  place the image on the face
# -----------------------------------------------------------------------------

def inscribed_center(poly):
    try:
        line = shapely.maximum_inscribed_circle(poly)
        return np.array(line.coords[0])
    except Exception:
        from shapely.ops import polylabel
        p = polylabel(poly, tolerance=0.01)
        return np.array([p.x, p.y])


def place_on_face(regions, frame, face, cfg, scale=None, fit_only=False):
    """Scale/center the 2D regions (SVG units) into the face's flat area (mm).

    fit_only: just return the largest scale that fits (mm per SVG unit).
    scale:    use this scale instead (never larger than what fits)."""
    content = unary_union(list(regions.values()))
    if cfg.FIT_TO == "viewbox" and frame is not None:
        ref = frame
    else:
        ref = content.convex_hull
    target = face.flat.buffer(-cfg.FACE_MARGIN_MM)
    if target.is_empty:
        raise SystemExit(f"face {face.number}: FACE_MARGIN_MM / rounding leave no room")
    center = inscribed_center(target)
    minx, miny, maxx, maxy = ref.bounds
    c0 = ((minx + maxx) / 2, (miny + maxy) / 2)
    ref0 = affinity.translate(ref, -c0[0], -c0[1])
    shapely.prepare(target)

    def fits(s):
        g = affinity.translate(affinity.scale(ref0, s, s, origin=(0, 0)), *center)
        return target.contains(g)

    span = max(maxx - minx, maxy - miny, 1e-9)
    lo, hi = 0.0, 4 * math.sqrt(face.flat.area) / span
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if fits(mid) else (lo, mid)
    if fit_only:
        return lo
    s = (lo if scale is None else min(scale, lo)) * cfg.IMAGE_SCALE

    out = {}
    for col, g in regions.items():
        g = affinity.translate(g, -c0[0], -c0[1])
        g = affinity.scale(g, s, s, origin=(0, 0))
        g = affinity.translate(g, *center)
        if cfg.FIT_TO == "viewbox":
            g = as_area(g.intersection(target))
        if not g.is_empty:
            out[col] = g
    return out, s


# -----------------------------------------------------------------------------
#  colors -> filaments
# -----------------------------------------------------------------------------

def build_palette(face_regions, cfg):
    """Map every SVG color to a color number. Returns (hex->idx, info per idx)."""
    area = defaultdict(float)
    faces_of = defaultdict(set)
    for f, regs in face_regions:
        for col, g in regs.items():
            area[col] += g.area
            faces_of[col].add(f.number)
    if not area:
        return {}, {}
    mapping, info = {}, {}
    if cfg.PALETTE:
        pal = [norm_hex(p) for p in cfg.PALETTE]
        labs = [lab_of(p) for p in pal]
        for col in area:
            d = [np.linalg.norm(lab_of(col) - l) for l in labs]
            mapping[col] = int(np.argmin(d)) + 1
        for i, p in enumerate(pal, 1):
            members = [c for c in area if mapping[c] == i]
            info[i] = dict(hex=p, area=sum(area[c] for c in members), members=members,
                           faces=sorted(set().union(*[faces_of[c] for c in members])) if members else [])
        return mapping, info

    clusters = [dict(members=[c], lab=lab_of(c), area=area[c]) for c in area]
    while len(clusters) > max(1, cfg.MAX_COLORS):
        best = None
        for i, j in itertools.combinations(range(len(clusters)), 2):
            d = np.linalg.norm(clusters[i]["lab"] - clusters[j]["lab"])
            if best is None or d < best[0]:
                best = (d, i, j)
        _, i, j = best
        a, b = clusters[i], clusters[j]
        tot = a["area"] + b["area"]
        a["lab"] = (a["lab"] * a["area"] + b["lab"] * b["area"]) / max(tot, 1e-12)
        a["members"] += b["members"]
        a["area"] = tot
        del clusters[j]
    clusters.sort(key=lambda c: -c["area"])
    for i, c in enumerate(clusters, 1):
        rep = max(c["members"], key=lambda m: area[m])
        for m in c["members"]:
            mapping[m] = i
        info[i] = dict(hex=rep, area=c["area"], members=c["members"],
                       faces=sorted(set().union(*[faces_of[m] for m in c["members"]])))
    return mapping, info


# -----------------------------------------------------------------------------
#  3D parts
# -----------------------------------------------------------------------------

def cross_section(g):
    contours = []
    for p in polys_only(g):
        contours.append(np.asarray(p.exterior.coords, float)[:-1])
        contours += [np.asarray(i.coords, float)[:-1] for i in p.interiors]
    return mf.CrossSection(contours, mf.FillRule.EvenOdd)


def face_cutter(g, face, depth):
    cs = cross_section(g)
    if cs.is_empty():
        return None
    pr = mf.Manifold.extrude(cs, depth + EPS_UP).translate((0, 0, -depth))
    M = np.column_stack([face.r, face.u, face.n, face.foot])
    return pr.transform(M)


def remove_thin(g, w):
    """Morphological opening: drops every part of g narrower than w (mm)."""
    if w <= 0:
        return g
    g = g.buffer(-w / 2, quad_segs=6).buffer(w / 2, quad_segs=6)
    return as_area(MultiPolygon([p for p in polys_only(g) if p.area > w * w])
                   if polys_only(g) else Polygon())


def needed_scale(shape, w, goal=0.9):
    """How much larger the image must get so that `goal` of its outline is at
    least w wide (scaling the image by k = shrinking w by k)."""
    a = shape.area
    if a <= 0 or remove_thin(shape, w).area >= goal * a:
        return 1.0
    lo, hi = 1.0, 4.0
    if remove_thin(shape, w / hi).area < goal * a:
        return hi
    for _ in range(7):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if remove_thin(shape, w / mid).area >= goal * a else (mid, hi)
    return hi


def cut_regions(faces, cfg, mapping, core_idx):
    """Per face: color number -> area to cut (similar colors already merged,
    the core color is never cut), with details thinner than MIN_FEATURE_MM:

    1. the outline of all colored areas together loses its thin parts (those
       become core color) - this is what decides whether something prints;
    2. inside that outline, a color strip thinner than the minimum
       - THIN_DETAILS = "merge": joins the neighboring color it touches most
         (a two-tone bone stays a bone, only its thin highlight changes color)
       - THIN_DETAILS = "remove": becomes core color.
    THIN_DETAILS = "keep" changes nothing and only reports what is too thin.
    """
    w = cfg.MIN_FEATURE_MM
    mode = str(cfg.THIN_DETAILS).lower()
    if mode not in ("merge", "remove", "keep"):
        raise SystemExit(f'THIN_DETAILS must be "merge", "remove" or "keep" (got {mode!r})')
    report = []
    for f in faces:
        per_idx = defaultdict(list)
        for col, g in f.regions.items():
            if mapping[col] != core_idx:
                per_idx[mapping[col]].append(g)
        cols = {i: as_area(unary_union(gs)) for i, gs in sorted(per_idx.items())}
        total = sum(g.area for g in cols.values())
        union = as_area(unary_union(list(cols.values()))) if cols else Polygon()
        f.cut = {i: g for i, g in cols.items() if not g.is_empty}
        if w <= 0 or not cols:
            report.append(dict(f=f, total=total, kept=total, moved=0.0, tiny=0, k=1.0))
            continue
        shape = remove_thin(union, w)
        tiny = sum(1 for p in polys_only(union) if p.area < w * w)
        k = needed_scale(union, w)
        if mode == "keep":
            report.append(dict(f=f, total=total, kept=shape.area, moved=0.0, tiny=tiny, k=k))
            continue
        keep = {i: remove_thin(as_area(g.intersection(shape)), w) for i, g in cols.items()}
        moved = 0.0
        left = as_area(shape.difference(unary_union(list(keep.values()))))
        if mode == "merge" and not left.is_empty:
            extra = defaultdict(list)
            for piece in polys_only(left):
                # floating-point slivers from the two openings are not details
                if piece.area < 0.01 * w * w or piece.buffer(-0.02 * w).is_empty:
                    continue
                grown = piece.buffer(w * 0.25)
                touch = [(grown.intersection(kk).area, i) for i, kk in keep.items() if not kk.is_empty]
                a, i = max(touch) if touch else (0, None)
                if a <= 0:  # touches no kept color: use the color it mostly was
                    i = max(cols, key=lambda j: piece.intersection(cols[j]).area)
                moved += piece.area - piece.intersection(cols[i]).area
                extra[i].append(piece)
            for i, ps in extra.items():
                keep[i] = as_area(unary_union([keep[i]] + ps))
        f.cut = {i: g for i, g in keep.items() if not g.is_empty}
        kept = sum(g.area for g in f.cut.values())
        report.append(dict(f=f, total=total, kept=kept, moved=moved, tiny=tiny, k=k))

    if w <= 0:
        return
    keep_mode = mode == "keep"
    log(f"\n  Thin details (< MIN_FEATURE_MM = {w} mm, THIN_DETAILS = {cfg.THIN_DETAILS}):")
    log("   face                                  "
        + ("printable   tiny blobs" if keep_mode else "shape kept   recolored"))
    for r in report:
        pct = 100 * r["kept"] / r["total"] if r["total"] > 0 else 100
        second = f"{r['tiny']:6d}" if keep_mode else f"{100 * r['moved'] / max(r['total'], 1e-12):6.0f}%"
        log(f"   {r['f'].number:>3} {r['f'].label[:32]:<32}   {pct:6.0f}%      {second}")
    k = max(r["k"] for r in report)
    worst = min(100 * r["kept"] / r["total"] for r in report if r["total"] > 0) \
        if any(r["total"] > 0 for r in report) else 100
    if keep_mode and worst < 99.5:
        warn("nothing was filtered (THIN_DETAILS = \"keep\"): the parts listed above as "
             "not 100% printable are thinner than the nozzle - the slicer will drop or "
             "smear them")
    if k > 1.0 and (keep_mode or worst < 75):
        size = cfg.DIE_SIZE_MM * k
        warn(f"to make >= 90% of every face printable, scale up about x{k:.2f}: "
             f"--size {math.ceil(size)} (now {cfg.DIE_SIZE_MM:g} mm), or set "
             f"MIN_FEATURE_MM = {w / k:.2f} if your nozzle/slicer can do that"
             + (" (> 4x: simplify the artwork)" if k >= 4 else ""))


def touch_points(geoms):
    """Points where the outline of ONE area touches itself in a single point
    (pinch): there 4 or more outline pieces meet instead of 2. Pass the area(s)
    of one color only - shared edges between colors would count otherwise."""
    rings = []
    for g in geoms:
        for p in polys_only(g):
            rings.append(LineString(p.exterior.coords))
            rings += [LineString(i.coords) for i in p.interiors]
    if not rings:
        return []
    count = defaultdict(int)
    for line in polys_or_lines(unary_union(rings)):
        c = line.coords
        count[(round(c[0][0], 6), round(c[0][1], 6))] += 1
        count[(round(c[-1][0], 6), round(c[-1][1], 6))] += 1
    return [Point(xy) for xy, n in count.items() if n >= 4]


def polys_or_lines(g):
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def clean_face_cuts(cut):
    """Make one face's 2D regions safe for a 3D file. Returns (core outline, regions).

    - all overlay math on a 1 µm grid (GRID_MM): shared edges of two colors stay
      identical, no hairline slivers
    - the core gets ONE outline (union of all colors)
    - a point contact (two areas corner to corner, or a shape touching itself)
      would become an edge shared by 4 triangles, which slicers see as broken:
      a tiny hole (PINCH_HOLE_MM) is punched at each such point
    """
    g = GRID_MM
    snapped, taken = {}, None
    for i in sorted(cut):  # one after another, minus what is placed: never overlap
        r = as_area(shapely.set_precision(cut[i], g))
        if taken is not None:
            r = as_area(shapely.difference(r, taken, grid_size=g))
        if r.is_empty:
            continue
        snapped[i] = r
        taken = r if taken is None else shapely.union(taken, r, grid_size=g)
    cut = snapped
    if not cut:
        return None, {}
    union = as_area(shapely.unary_union(list(cut.values()), grid_size=g))
    # punching can expose new contacts nearby, so repeat until none are left
    for _ in range(8):
        # each outline on its own: where 3 colors meet is a normal junction
        pts = touch_points([union])
        for r in cut.values():
            pts += touch_points([r])
        if not pts:
            break
        holes = unary_union([p.buffer(PINCH_HOLE_MM, quad_segs=4) for p in pts])
        union = as_area(shapely.difference(union, holes, grid_size=g))
        cut = {i: r for i, r in ((i, as_area(shapely.difference(r, holes, grid_size=g)))
                                 for i, r in cut.items()) if not r.is_empty}
    else:
        warn(f"{len(pts)} point contact(s) could not be removed - the slicer may "
             "report a few non-manifold edges")
    return union, cut


def build_parts(die, faces, cfg, mapping, info):
    """Returns ordered list of parts: dict(name, idx, hex, manifold, extruder)."""
    shares = cfg.CORE_SHARES_COLOR
    core_idx = cfg.CORE_COLOR_INDEX if shares else None
    if shares and core_idx not in info:
        raise SystemExit(f"CORE_COLOR_INDEX = {core_idx} but the colors are numbered "
                         f"{sorted(info)} - pick one from the table above")
    cut_regions(faces, cfg, mapping, core_idx)
    cutters, core_cutters = defaultdict(list), []
    for f in faces:
        core_region, f.cut = clean_face_cuts(f.cut)
        if core_region is not None:
            c = face_cutter(core_region, f, cfg.INLAY_DEPTH_MM)
            if c is not None:
                core_cutters.append(c)
        for idx, g in f.cut.items():
            c = face_cutter(g, f, cfg.INLAY_DEPTH_MM)
            if c is not None:
                cutters[idx].append(c)

    # the core is cut with ONE outline per face (not the colors one by one):
    # colors that share an edge would otherwise leave hairline slivers
    core = die - mf.Manifold.batch_boolean(core_cutters, mf.OpType.Add) if core_cutters else die

    if shares:
        core_ext = core_idx
        ext_of = {i: i for i in info}
        core_hex = info[core_idx]["hex"]
    else:
        core_ext = 1
        ext_of = {i: i + 1 for i in info}
        core_hex = norm_hex(cfg.CORE_COLOR)
    parts = [dict(name="core", idx=core_idx, hex=core_hex, mesh=core, extruder=core_ext)]
    for idx in sorted(cutters):
        inlay = mf.Manifold.batch_boolean(cutters[idx], mf.OpType.Add) ^ die
        if inlay.is_empty():
            continue
        parts.append(dict(name=f"color{idx}", idx=idx, hex=info[idx]["hex"], mesh=inlay,
                          extruder=ext_of[idx]))
    parts.sort(key=lambda p: p["extruder"])
    return parts


def to_arrays(m):
    """Manifold -> vertex/face arrays for export.

    A file has no topology: the slicer merges points by position. Where manifold
    keeps two separate points at the same spot, merging collapses a triangle to
    a line (two equal corners) - only those triangles are dropped. Thin but
    proper triangles (three different corners) must stay, or holes appear."""
    import trimesh
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(np.asarray(mesh.vert_properties[:, :3], float),
                         np.asarray(mesh.tri_verts, np.int64), process=True)
    F = tm.faces
    ok = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
    tm.update_faces(ok)
    tm.remove_unreferenced_vertices()
    return np.asarray(tm.vertices, float), np.asarray(tm.faces, np.int64)


# -----------------------------------------------------------------------------
#  output
# -----------------------------------------------------------------------------

def write_stl(path, V, F):
    import trimesh
    trimesh.Trimesh(V, F, process=False).export(path)


def write_3mf_prusa(path, parts, name):
    """PrusaSlicer layout: one object, one mesh, parts (volumes) by triangle
    ranges with an extruder each (Metadata/Slic3r_PE_model.config).
    Tested with PrusaSlicer 2.x. OrcaSlicer ignores that config (-> one part),
    so it gets its own file (write_3mf_bambu). Display colors are stored as
    3MF base materials."""
    verts, tris, ranges, tri_mat = [], [], [], []
    off = toff = 0
    for k, p in enumerate(parts):
        V, F = p["V"], p["F"]
        verts.append(V)
        tris.append(F + off)
        ranges.append((toff, toff + len(F) - 1))
        tri_mat.append(np.full(len(F), k))
        off += len(V)
        toff += len(F)
    V = np.concatenate(verts)
    F = np.concatenate(tris)
    M = np.concatenate(tri_mat)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">',
             ' <metadata name="slic3rpe:Version3mf">1</metadata>',
             f' <metadata name="Title">{name}</metadata>',
             ' <metadata name="Application">DiceMaker</metadata>',
             ' <resources>',
             '  <basematerials id="1">']
    for p in parts:
        lines.append(f'   <base name="{p["label"]}" displaycolor="{p["hex"].upper()}FF"/>')
    lines += ['  </basematerials>',
              '  <object id="2" type="model" pid="1" pindex="0">',
              '   <mesh>', '    <vertices>']
    lines += [f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in V]
    lines += ['    </vertices>', '    <triangles>']
    lines += [f'     <triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{m}"/>'
              for (a, b, c), m in zip(F, M)]
    lines += ['    </triangles>', '   </mesh>', '  </object>', ' </resources>',
              ' <build>', '  <item objectid="2" transform="1 0 0 0 1 0 0 0 1 100 100 0"/>',
              ' </build>', '</model>']
    model = "\n".join(lines)

    cfgx = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>',
            ' <object id="2" instances_count="1">',
            f'  <metadata type="object" key="name" value="{name}"/>',
            f'  <metadata type="object" key="extruder" value="{parts[0]["extruder"]}"/>']
    for p, (a, b) in zip(parts, ranges):
        cfgx += [f'  <volume firstid="{a}" lastid="{b}">',
                 f'   <metadata type="volume" key="name" value="{p["label"]}"/>',
                 '   <metadata type="volume" key="volume_type" value="ModelPart"/>',
                 f'   <metadata type="volume" key="extruder" value="{p["extruder"]}"/>',
                 '   <mesh edges_fixed="0" degenerate_facets="0" facets_removed="0" '
                 'facets_reversed="0" backwards_edges="0"/>',
                 '  </volume>']
    cfgx += [' </object>', '</config>']

    types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
             '<Default Extension="config" ContentType="text/xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/Slic3r_PE_model.config", "\n".join(cfgx))


def write_3mf_bambu(path, parts, name, app="DiceMaker"):
    """Bambu Studio / OrcaSlicer layout: every part is its own mesh object, one
    parent object combines them as components, Metadata/model_settings.config
    gives every part its name and filament (extruder)."""
    ns = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
          'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
          'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"')
    obj = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<model unit="millimeter" xml:lang="en-US" {ns} requiredextensions="p">',
           ' <metadata name="BambuStudio:3mfVersion">1</metadata>', ' <resources>']
    for k, p in enumerate(parts, 1):
        obj += [f'  <object id="{k}" type="model">', '   <mesh>', '    <vertices>']
        obj += [f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in p["V"]]
        obj += ['    </vertices>', '    <triangles>']
        obj += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in p["F"]]
        obj += ['    </triangles>', '   </mesh>', '  </object>']
    obj += [' </resources>', ' <build/>', '</model>']

    pid = len(parts) + 1
    objpath = "/3D/Objects/object_1.model"
    main = ['<?xml version="1.0" encoding="UTF-8"?>',
            f'<model unit="millimeter" xml:lang="en-US" {ns} requiredextensions="p">',
            f' <metadata name="Application">{app}</metadata>',
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
            f' <metadata name="Title">{name}</metadata>',
            ' <resources>', f'  <object id="{pid}" type="model">', '   <components>']
    main += [f'    <component p:path="{objpath}" objectid="{k}" '
             'transform="1 0 0 0 1 0 0 0 1 0 0 0"/>' for k in range(1, len(parts) + 1)]
    main += ['   </components>', '  </object>', ' </resources>',
             f' <build><item objectid="{pid}" transform="1 0 0 0 1 0 0 0 1 100 100 0" '
             'printable="1"/></build>', '</model>']

    ms = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>', f'  <object id="{pid}">',
          f'    <metadata key="name" value="{name}"/>',
          f'    <metadata key="extruder" value="{parts[0]["extruder"]}"/>']
    for k, p in enumerate(parts, 1):
        ms += [f'    <part id="{k}" subtype="normal_part">',
               f'      <metadata key="name" value="{p["label"]}"/>',
               '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>',
               f'      <metadata key="extruder" value="{p["extruder"]}"/>',
               '    </part>']
    ms += ['  </object>', '</config>']

    types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
             '<Default Extension="config" ContentType="text/xml"/>'
             '</Types>')
    rel = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
           '<Relationship Target="{}" Id="rel-1" '
           'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
           '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rel.format("/3D/3dmodel.model"))
        z.writestr("3D/_rels/3dmodel.model.rels", rel.format(objpath))
        z.writestr("3D/3dmodel.model", "\n".join(main))
        z.writestr(objpath.lstrip("/"), "\n".join(obj))
        z.writestr("Metadata/model_settings.config", "\n".join(ms))


def render_view(parts, azim, elev, size):
    """Tiny z-buffer renderer (orthographic, flat shading) -> HxWx3 uint8."""
    a, e = math.radians(azim), math.radians(elev)
    cam = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)])
    right = unit(np.cross(-cam, [0, 0, 1]))
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0, 0])
    up = np.cross(right, -cam)
    light = unit(cam * 0.7 + up * 0.5 + right * 0.3)
    allV = np.concatenate([p["V"] for p in parts])
    center = (allV.max(0) + allV.min(0)) / 2
    ext = np.abs(np.c_[(allV - center) @ right, (allV - center) @ up]).max()
    s = size * 0.46 / ext
    img = np.empty((size, size, 3), float)
    img[:] = (236, 238, 242)
    zbuf = np.full((size, size), -np.inf)
    for p in parts:
        V = p["V"] - center
        X = size / 2 + (V @ right) * s
        Y = size / 2 - (V @ up) * s
        Z = V @ cam
        T = p["F"]
        nrm = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
        nn = np.linalg.norm(nrm, axis=1)
        ok = nn > 1e-12
        nrm[ok] /= nn[ok, None]
        vis = ok & (nrm @ cam > 0)
        shade = 0.30 + 0.70 * np.clip(nrm @ light, 0, 1)
        base = np.array(rgb_of(p["hex"]), float)
        for t in np.where(vis)[0]:
            i0, i1, i2 = T[t]
            xs, ys, zs = X[[i0, i1, i2]], Y[[i0, i1, i2]], Z[[i0, i1, i2]]
            x0, x1 = max(int(xs.min()), 0), min(int(xs.max()) + 1, size - 1)
            y0, y1 = max(int(ys.min()), 0), min(int(ys.max()) + 1, size - 1)
            if x1 < x0 or y1 < y0:
                continue
            den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(den) < 1e-12:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
            w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
            w2 = 1 - w0 - w1
            m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not m.any():
                continue
            z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            m &= z > sub
            sub[m] = z[m]
            img[y0:y1 + 1, x0:x1 + 1][m] = base * shade[t]
    return np.clip(img, 0, 255).astype(np.uint8)


def write_preview(path, parts, sides):
    from PIL import Image
    size = 420
    views = [(30, 25), (120, 25), (210, 25), (300, -35)]
    if sides in (12, 20):
        views = [(30, 30), (150, 30), (270, 30), (90, -60)]
    if sides == 2:  # coin: heads from above, tails from below, two tilted views
        views = [(-90, 89), (90, -89), (-90, 35), (90, -35)]
    tiles = [render_view(parts, a, e, size) for a, e in views]
    grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
    Image.fromarray(grid).save(path)


# -----------------------------------------------------------------------------
#  main
# -----------------------------------------------------------------------------

def resolve_face_sources(cfg, base_dir):
    src = cfg.FACE_SVGS
    if isinstance(src, str):
        d = src if os.path.isabs(src) else os.path.join(base_dir, src)
        if not os.path.isdir(d):
            raise SystemExit(f"FACE_SVGS folder not found: {d}")
        files = [f for f in os.listdir(d) if f.lower().endswith(".svg")]
        num = lambda f: int(m.group(1)) if (m := re.search(r"(\d+)", f)) else 10 ** 9
        src = [os.path.join(d, f) for f in sorted(files, key=lambda f: (num(f), f))]
    src = list(src or [])
    if len(src) > cfg.DIE_SIDES:
        warn(f"{len(src)} SVGs given, a d{cfg.DIE_SIDES} only has {cfg.DIE_SIDES} faces "
             f"- the extra ones are ignored")
        src = src[:cfg.DIE_SIDES]
    if len(src) < cfg.DIE_SIDES:
        log(f"  {cfg.DIE_SIDES - len(src)} face(s) without SVG get their number as text")
        src += [None] * (cfg.DIE_SIDES - len(src))
    out = []
    for s in src:
        if s is None:
            out.append(None)
            continue
        p = s if os.path.isabs(s) else os.path.join(base_dir, s)
        if not os.path.isfile(p):
            # also try the current folder and, in the Windows exe, the bundled examples
            tries = [os.path.abspath(s)]
            if getattr(sys, "_MEIPASS", None):
                tries.append(os.path.join(sys._MEIPASS, s))
            p = next((t for t in tries if os.path.isfile(t)), None)
            if p is None:
                raise SystemExit(f"SVG not found: {s}")
        out.append(p)
    return out


TYPICAL_SIZE_MM = {2: 30.0, 4: 20.0, 6: 16.0, 8: 16.0, 10: 16.0, 12: 18.0, 20: 20.0}


def make_die(cfg, base_dir="."):
    sides = cfg.DIE_SIDES
    if not cfg.DIE_SIZE_MM:
        cfg.DIE_SIZE_MM = TYPICAL_SIZE_MM.get(sides, 16.0)
    tag = "coin" if sides == 2 else f"d{sides}"
    log(f"DiceMaker: {tag}, {cfg.DIE_SIZE_MM} mm"
        + (f" x {cfg.COIN_THICKNESS_MM} mm" if sides == 2 else "")
        + f", inlay depth {cfg.INLAY_DEPTH_MM} mm")
    if cfg.LAYER_HEIGHT_MM > 0:
        ratio = cfg.INLAY_DEPTH_MM / cfg.LAYER_HEIGHT_MM
        if abs(ratio - round(ratio)) > 1e-6:
            warn(f"INLAY_DEPTH_MM {cfg.INLAY_DEPTH_MM} is not a multiple of the layer height "
                 f"{cfg.LAYER_HEIGHT_MM} - top/bottom faces get uneven color layers")
    sources = resolve_face_sources(cfg, base_dir)

    if sides == 2:
        die, faces = build_coin(cfg)
    else:
        V, faces, inr, circ = build_geometry(cfg)
        die = build_die(V, faces, inr, circ, cfg)
    ignore = {norm_hex(c) for c in cfg.IGNORE_COLORS}

    # read every face first, so faces can share one scale
    loaded = []
    for f, src in zip(faces, sources):
        if src is None:
            layers, frame = number_layers(f.number, cfg)
            f.label, f.kind = f"number {f.number}", "number"
        else:
            layers, frame = svg_layers(src, cfg)
            f.label, f.kind = os.path.basename(src), "svg"
        regions = visible_by_color(layers, ignore)
        if not regions:
            warn(f"face {f.number} ({f.label}): nothing to print (no filled shapes)")
        loaded.append((f, regions, frame))

    # numbers always get the same text size; SVGs only with UNIFORM_SCALE
    common = {}
    for kind in ("number", "svg"):
        if kind == "svg" and not cfg.UNIFORM_SCALE:
            continue
        fits = [place_on_face(r, fr, f, cfg, fit_only=True)
                for f, r, fr in loaded if f.kind == kind and r]
        if fits:
            common[kind] = min(fits)

    face_regions = []
    for f, regions, frame in loaded:
        f.regions = {}
        if regions:
            f.regions, _ = place_on_face(regions, frame, f, cfg, scale=common.get(f.kind))
        face_regions.append((f, f.regions))

    mapping, info = build_palette(face_regions, cfg)
    if not info:
        raise SystemExit("no colors found in any face")

    log("\n  Colors (merged over all faces):")
    log("   no.  color    area mm²  faces            SVG colors")
    for i, d in info.items():
        mem = ", ".join(d["members"][:6]) + (" ..." if len(d["members"]) > 6 else "")
        log(f"   {i:>3}  {d['hex']}  {d['area']:8.1f}  "
            f"{','.join(map(str, d['faces'])) or '-':<16} {mem}")

    parts = build_parts(die, faces, cfg, mapping, info)
    if len(parts) == 1:
        warn("only the core is left - every color equals the core color. "
             "Set CORE_SHARES_COLOR = False or another CORE_COLOR_INDEX.")

    # put the die on the bed (z = 0)
    zmin = die.bounding_box()[2]
    for p in parts:
        p["V"], p["F"] = to_arrays(p["mesh"])
        p["V"][:, 2] -= zmin
        p["volume"] = p["mesh"].volume()
        p["label"] = (f"{p['extruder']}_core_{p['hex'][1:]}" if p["name"] == "core"
                      else f"{p['extruder']}_color{p['idx']}_{p['hex'][1:]}")

    out_dir = os.path.join(base_dir, cfg.OUTPUT_DIR, tag) \
        if not os.path.isabs(cfg.OUTPUT_DIR) else os.path.join(cfg.OUTPUT_DIR, tag)
    os.makedirs(out_dir, exist_ok=True)

    log("\n  Parts (filament = slot/extruder in the slicer):")
    total = die.volume()
    for p in parts:
        g = p["volume"] / 1000 * cfg.DENSITY_G_CM3
        what = "die core" if p["name"] == "core" else f"color {p['idx']}"
        log(f"   filament {p['extruder']}  {p['hex']}  {what:<9} {p['volume']:8.1f} mm³  "
            f"~{g:5.2f} g (100% infill)")
    s = sum(p["volume"] for p in parts)
    if abs(s - total) > 1e-3 * total:
        warn(f"part volumes {s:.2f} != die volume {total:.2f}")

    written = []
    if cfg.WRITE_STL:
        for p in parts:
            fn = os.path.join(out_dir, p["label"] + ".stl")
            write_stl(fn, p["V"], p["F"])
            written.append(fn)
    if cfg.WRITE_3MF:
        fn = os.path.join(out_dir, f"dice_{tag}_prusa.3mf")
        write_3mf_prusa(fn, parts, f"dice_{tag}")
        written.append(fn)
        fn = os.path.join(out_dir, f"dice_{tag}_orca_bambu.3mf")
        write_3mf_bambu(fn, parts, f"dice_{tag}")
        written.append(fn)
    if cfg.WRITE_PREVIEW:
        fn = os.path.join(out_dir, "preview.png")
        write_preview(fn, parts, sides)
        written.append(fn)
    log("\n  Written:")
    for fn in written:
        log(f"   {fn}")
    log("\n  Slicer: open the .3mf for your slicer (one object, every part already has its\n"
        "  filament), or load all STLs at once and answer 'load as one object with\n"
        "  multiple parts' -> yes, then set the filament per part.")
    return parts, faces, die, out_dir


def load_config(argv=None):
    g = globals()
    cfg = SimpleNamespace(**{k: g[k] for k in list(g) if k.isupper() and not k.startswith("EPS")
                             and k not in ("PHI", "CAPS", "JOINS", "TYPICAL_SIZE_MM", "GRID_MM", "PINCH_HOLE_MM")})
    ap = argparse.ArgumentParser(description="Multi-color inlay dice from SVG files.")
    ap.add_argument("--sides", type=int, help="4, 6, 8, 10, 12 or 20 (2 = coin)")
    ap.add_argument("--coin", action="store_true", help="make a coin (same as --sides 2); "
                    "--size is then the diameter")
    ap.add_argument("--thin", choices=["merge", "remove", "keep"],
                    help="what to do with details thinner than MIN_FEATURE_MM")
    ap.add_argument("--size", type=float, help="die size in mm (face to face)")
    ap.add_argument("--svgs", nargs="*", help="SVG files in face order, or one folder; "
                    "missing faces get numbers. '--svgs' alone = numbers only")
    ap.add_argument("--depth", type=float, help="inlay depth in mm")
    ap.add_argument("--colors", type=int, help="max number of colors")
    ap.add_argument("--core-color", type=int, metavar="N",
                    help="core shares color N (sets CORE_SHARES_COLOR = True)")
    ap.add_argument("--separate-core", action="store_true",
                    help="core gets its own filament (CORE_SHARES_COLOR = False)")
    ap.add_argument("--rounding", choices=["none", "minkowski", "sphere"])
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args(argv)
    if a.coin:
        a.sides = 2
    if a.thin:
        cfg.THIN_DETAILS = a.thin
    if a.sides:
        cfg.DIE_SIDES = a.sides
        if a.svgs is None:  # config list was made for another die
            cfg.FACE_SVGS = cfg.FACE_SVGS if len(cfg.FACE_SVGS or []) == a.sides else []
    if a.size:
        cfg.DIE_SIZE_MM = a.size
    if a.svgs is not None:
        cfg.FACE_SVGS = a.svgs[0] if len(a.svgs) == 1 and os.path.isdir(a.svgs[0]) else a.svgs
    if a.depth:
        cfg.INLAY_DEPTH_MM = a.depth
    if a.colors:
        cfg.MAX_COLORS = a.colors
    if a.core_color:
        cfg.CORE_SHARES_COLOR, cfg.CORE_COLOR_INDEX = True, a.core_color
    if a.separate_core:
        cfg.CORE_SHARES_COLOR = False
    if a.rounding:
        cfg.EDGE_ROUNDING = a.rounding
    if a.out:
        cfg.OUTPUT_DIR = a.out
    if a.no_preview:
        cfg.WRITE_PREVIEW = False
    return cfg


if __name__ == "__main__":
    config = load_config()
    here = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):  # single-file exe: output goes to the current folder
        here = os.getcwd()
    make_die(config, base_dir=here)
