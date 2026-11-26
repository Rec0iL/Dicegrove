#!/usr/bin/env python3
"""Builds every die type (and a coin) and checks the parts.

Checks per die: every part is a closed (watertight) solid, no two parts overlap,
and core + inlays add up to the full die volume.
Run:  python tests/verify.py
"""
import itertools
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import trimesh  # noqa: E402
import dicemaker as dm  # noqa: E402


def check(label, argv):
    cfg = dm.load_config(argv)
    parts, faces, die, out_dir = dm.make_die(cfg, base_dir=ROOT)
    problems = []
    for p in parts:
        tm = trimesh.Trimesh(p["V"], p["F"], process=True)
        if not tm.is_watertight:
            problems.append(f"{p['label']} is not watertight")
        if p["mesh"].status() != dm.mf.Error.NoError:
            problems.append(f"{p['label']} manifold status {p['mesh'].status()}")
    for a, b in itertools.combinations(parts, 2):
        ov = (a["mesh"] ^ b["mesh"]).volume()
        if ov > 1e-3:  # 0.001 mm³ ≈ a 0.1 mm cube: far below what a slicer resolves
            problems.append(f"{a['label']} and {b['label']} overlap by {ov:.5f} mm³")
    total = die.volume()
    s = sum(p["volume"] for p in parts)
    if abs(s - total) > 1e-4 * total:
        problems.append(f"volumes {s:.4f} != die {total:.4f}")
    inlays = len(parts) - 1
    ok = not problems and inlays > 0
    print(f"\n### {label}: {'OK' if ok else 'FAIL'}  ({len(parts)} parts, die {total:.1f} mm³)")
    for pr in problems:
        print("    -", pr)
    if inlays == 0:
        print("    - no inlay parts")
    return ok


if __name__ == "__main__":
    out = tempfile.mkdtemp(prefix="dicemaker_verify_")
    runs = [("d6 example SVGs", ["--out", out])]
    for n in (4, 6, 8, 10, 12, 20):
        for r in ("minkowski", "sphere", "none"):
            if r != "minkowski" and n not in (6, 20):
                continue
            runs.append((f"d{n} numbers, {r}",
                         ["--sides", str(n), "--svgs", "--separate-core", "--rounding", r,
                          "--out", out, "--no-preview"]))
    runs += [
        ("coin, 2 SVGs", ["--coin", "--svgs", "examples/d6/1.svg", "examples/d6/3.svg",
                          "--out", out, "--no-preview"]),
        ("coin, H/T labels", ["--coin", "--svgs", "--separate-core", "--out", out, "--no-preview"]),
        ("d6 example, thin=keep", ["--thin", "keep", "--out", out, "--no-preview"]),
        ("d6 example, thin=remove", ["--thin", "remove", "--out", out, "--no-preview"]),
    ]
    results = [check(lbl, argv) for lbl, argv in runs]
    print(f"\n{sum(results)}/{len(results)} OK   (output in {out})")
    sys.exit(0 if all(results) else 1)
