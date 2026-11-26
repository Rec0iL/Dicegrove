"""Write a .dicejob for the CI self-test of Dicegrove.exe.

    python packaging/make_smoke_job.py OUT.dicejob

A d6 with three of the example faces (one rotated); the exe is started with this file and
must build the die (output: examples/d6_d6/ next to the example folder).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Dicegrove"))

from dicegrove import core  # noqa: E402

out = Path(sys.argv[1]).resolve()
faces = [str(ROOT / "examples" / "d6" / f"{i}.svg") for i in (1, 2, 3)]
job = core.write_job(6, faces, [0, 90, 0], job_dir=out.parent / "jobs")
out.parent.mkdir(parents=True, exist_ok=True)
job.replace(out)
print(out)
