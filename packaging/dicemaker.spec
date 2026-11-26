# PyInstaller spec: dicemaker.exe - the command line tool as one self-contained file.
#   pyinstaller packaging/dicemaker.spec
# Output goes to the current folder (out/<die>/); the d6 example SVGs are bundled,
# so `dicemaker.exe` without arguments builds the example die.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "dicemaker.py")],
    pathex=[ROOT],
    binaries=collect_dynamic_libs("manifold3d"),
    datas=[(os.path.join(ROOT, "examples", "d6"), os.path.join("examples", "d6"))]
          + collect_data_files("trimesh"),
    hiddenimports=["scipy.spatial", "scipy.spatial._qhull", "shapely", "manifold3d",
                   "svgelements", "trimesh", "matplotlib.textpath", "matplotlib.font_manager"],
    excludes=["tkinter", "IPython", "PySide6", "PyQt5", "PyQt6", "pytest",
              # optional extras of trimesh/scipy/matplotlib that are never used here
              "torch", "tensorflow", "jax", "vtk", "vtkmodules", "open3d", "cv2", "sklearn",
              "pyglet", "numba", "sympy", "pandas", "embreex", "rtree"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="dicemaker",
    console=True,
    icon=os.path.join(ROOT, "Dicegrove", "packaging", "dicegrove.ico"),
    upx=False,
)
