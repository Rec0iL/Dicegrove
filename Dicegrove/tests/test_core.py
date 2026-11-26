"""Tests for Dicegrove's core: job files, face order, output location and real builds."""
import json
import tempfile
import unittest
from pathlib import Path

from dicegrove import core

# a small two-color face: white rounded square with a red ring and a black bar
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
       '<rect x="4" y="4" width="92" height="92" rx="12" fill="#ffffff"/>'
       '<path fill="#d32f2f" fill-rule="evenodd" d="M50 18a32 32 0 1 0 0.01 0Z M50 34a16 16 0 1 0 0.01 0Z"/>'
       '<rect x="20" y="80" width="60" height="8" fill="#212121"/></svg>')

FAST = {"writePreview": False, "writeStl": False}  # keep the suite quick


def opts(**over):
    return {**core.OPTION_DEFAULTS, "overwrite": "rename", **FAST, **over}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.art = self.tmp / "crests"
        self.art.mkdir()
        for name in ("10.svg", "2.svg", "1.svg"):
            (self.art / name).write_text(SVG)
        (self.art / "notes.txt").write_text("x")
        self.jobs = self.tmp / "jobs"
        self._job_dir = core.JOB_DIR
        core.JOB_DIR = self.jobs                   # never write into the real ~/.cache

    def tearDown(self):
        core.JOB_DIR = self._job_dir
        self._t.cleanup()

    def job(self, sides, faces, rots=None):
        return core.write_job(sides, [str(f) for f in faces], rots, job_dir=self.jobs)

    # ---- inputs ---------------------------------------------------------------
    def test_unique_path(self):
        p = self.tmp / "a.txt"
        self.assertEqual(core.unique_path(p), p)
        p.write_text("x")
        self.assertEqual(core.unique_path(p).name, "a (2).txt")
        self.assertEqual(core.unique_path(p, "overwrite"), p)

    def test_face_files_natural_order_and_filter(self):
        got = [f.name for f in core.face_files([self.art])]
        self.assertEqual(got, ["1.svg", "2.svg", "10.svg"])          # numbers, not text order
        got = [f.name for f in core.face_files([self.art / "2.svg", self.art / "1.svg"])]
        self.assertEqual(got, ["2.svg", "1.svg"])                    # files keep the given order

    def test_expand_inputs_makes_one_job_from_plain_svgs(self):
        jobs = core.expand_inputs([self.art, self.tmp / "missing.txt"])
        self.assertEqual(len(jobs), 1)
        spec = json.loads(jobs[0].read_text())
        self.assertIsNone(spec["sides"])                             # taken from the settings
        self.assertEqual(spec["count"], 3)
        self.assertEqual(core.expand_inputs([self.tmp / "nothing.txt"]), [])

    def test_write_job_pads_faces_and_rotations(self):
        spec = json.loads(self.job(6, [self.art / "1.svg"], [90]).read_text())
        self.assertEqual(spec["sides"], 6)
        self.assertEqual(len(spec["faces"]), 6)
        self.assertEqual(spec["faces"][1:], [""] * 5)
        self.assertEqual(spec["rotations"], [90, 0, 0, 0, 0, 0])
        with self.assertRaises(core.CoreError):
            self.job(7, [])

    def test_output_location(self):
        faces = [str(self.art / "1.svg"), str(self.art / "2.svg")]
        self.assertEqual(core.output_home(faces), self.tmp)          # beside the art folder
        self.assertEqual(core.output_name(faces), "crests")
        self.assertEqual(core.output_name([str(self.art / "1.svg")]), "1")
        self.assertEqual(core.output_name([]), "numbers")

    def test_old_job_files_are_pruned(self):
        import os
        old = self.job(6, [])
        stale = old.stat().st_mtime - 40 * 86400
        os.utime(old, (stale, stale))
        os.utime(old.parent, (stale, stale))
        new = self.job(6, [])
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_parse_palette(self):
        self.assertEqual(core.parse_palette("#FFF000, d32f2f;#123"), ["#fff000", "#d32f2f", "#123"])
        self.assertIsNone(core.parse_palette(""))

    # ---- errors / skips -------------------------------------------------------
    def test_missing_job_file(self):
        res = core.process(self.tmp / "nope.dicejob", self.tmp, opts())
        self.assertEqual(res.status, "error")

    def test_missing_face_svg(self):
        job = self.job(6, [self.art / "gone.svg"])
        with self.assertRaisesRegex(core.CoreError, "Face 1"):
            core.process(job, job.parent, opts())

    def test_too_many_svgs_for_the_die(self):
        job = core.expand_inputs([self.art])[0]                      # 3 SVGs
        with self.assertRaisesRegex(core.CoreError, "bigger die"):
            core.process(job, job.parent, opts(dieType=2))

    def test_unsupported_file_is_skipped(self):
        f = self.tmp / "x.txt"
        f.write_text("x")
        self.assertEqual(core.process(f, self.tmp, opts()).status, "skipped")

    def test_all_outputs_off(self):
        job = self.job(6, [self.art / "1.svg"])
        with self.assertRaises(core.CoreError):
            core.process(job, job.parent, opts(write3mf=False))

    def test_cancel(self):
        import threading
        ev = threading.Event()
        ev.set()
        job = self.job(6, [self.art / "1.svg"])
        with self.assertRaises(core.Cancelled):
            core.process(job, job.parent, opts(), cancel=ev)

    # ---- real builds ------------------------------------------------------------
    def test_d6_next_to_art_with_progress(self):
        job = self.job(6, [self.art / "1.svg", self.art / "2.svg"], [0, 90])
        steps = []
        res = core.process(job, job.parent, opts(writePreview=True),
                           progress=lambda f, m: steps.append((f, m)))
        self.assertEqual(res.status, "done", res.message)
        out = self.tmp / "crests_d6"                                 # beside crests/
        self.assertEqual(res.output, out / "preview.png")
        names = {p.name for p in res.files}
        self.assertTrue({"dice_d6_orca_bambu.3mf", "dice_d6_prusa.3mf", "preview.png",
                         "report.txt"} <= names, names)
        self.assertIn("d6 · ", res.message)
        self.assertEqual(steps[-1][0], 1.0)
        self.assertTrue(any("Reading face" in m for _, m in steps))
        self.assertFalse(any(p.name.startswith(".dicegrove-") for p in self.tmp.iterdir()))

    def test_rename_vs_overwrite(self):
        job = self.job(6, [self.art / "1.svg", self.art / "2.svg"])
        a = core.process(job, job.parent, opts())
        b = core.process(job, job.parent, opts())
        c = core.process(job, job.parent, opts(overwrite="overwrite"))
        self.assertEqual(a.output.parent.name, "crests_d6")
        self.assertEqual(b.output.parent.name, "crests_d6 (2)")
        self.assertEqual(c.output.parent.name, "crests_d6")

    def test_coin_and_separate_core(self):
        job = self.job(2, [self.art / "1.svg", self.art / "2.svg"])
        res = core.process(job, job.parent, opts(coreShares=False, writeStl=True))
        self.assertEqual(res.status, "done", res.message)
        stls = sorted(p.name for p in res.files if p.suffix == ".stl")
        self.assertTrue(stls[0].startswith("1_core_f0f0f0"), stls)   # own filament = slot 1
        self.assertEqual(len(stls), 4)                               # core + white, red, black
        self.assertIn("coin", res.message)

    def test_numbers_only_d20(self):
        job = self.job(20, [])
        self.assertEqual(json.loads(job.read_text())["home"], str(Path.home() / "Dicegrove"))
        out = self.tmp / "custom"                  # never write into the real ~/Dicegrove
        res = core.process(job, out, opts(coreShares=False))
        self.assertEqual(res.status, "done", res.message)
        self.assertEqual(res.output.parent, out / "numbers_d20")

    def test_max_colors_and_white_background(self):
        job = self.job(6, [self.art / "1.svg"])
        res = core.process(job, job.parent, opts(maxColors=1, coreShares=False, writeStl=True))
        self.assertEqual(sum(1 for p in res.files if p.suffix == ".stl"), 2)   # core + 1 color
        res = core.process(job, job.parent, opts(whiteBackground=True, writeStl=True))
        report = (res.output.parent / "report.txt").read_text()
        self.assertNotIn("#ffffff", report.split("Parts")[0])        # white was not a color

    def test_settings_reach_the_engine(self):
        from dicegrove import engine
        o = opts(sizeMm=24, edges="sphere", thinDetails="keep", palette="#fff,#000",
                 imageScale=75, fitTo="viewbox", depthMm=0.6, coinThickness=4.0)
        cfg = core.engine_config(engine, o, 8, ["a.svg", ""], [90, 0], self.tmp)
        self.assertEqual((cfg.DIE_SIDES, cfg.DIE_SIZE_MM, cfg.EDGE_ROUNDING), (8, 24.0, "sphere"))
        self.assertEqual((cfg.THIN_DETAILS, cfg.PALETTE, cfg.IMAGE_SCALE), ("keep", ["#fff", "#000"], 0.75))
        self.assertEqual((cfg.FIT_TO, cfg.INLAY_DEPTH_MM, cfg.COIN_THICKNESS_MM), ("viewbox", 0.6, 4.0))
        self.assertEqual(cfg.FACE_SVGS, ["a.svg", None])
        self.assertEqual(cfg.FACE_ROTATIONS, {1: 90})
        self.assertIsNone(core.engine_config(engine, opts(), 6, [], [], self.tmp).DIE_SIZE_MM)


if __name__ == "__main__":
    unittest.main()
