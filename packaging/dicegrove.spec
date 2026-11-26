# PyInstaller spec: Dicegrove.exe - the drag & drop app as one self-contained file.
#   pyinstaller packaging/dicegrove.spec
# Works on Windows (the release build) and Linux (for testing the spec).
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "Dicegrove")

datas = [
    (os.path.join(APP, "qml"), "qml"),
    (os.path.join(APP, "shaders", "bg.frag.qsb"), "shaders"),
    (os.path.join(APP, "packaging", "dicegrove.svg"), "packaging"),
]
datas += collect_data_files("trimesh")

hidden = [
    "dicegrove.engine",            # imported lazily when the first die is made
    "scipy.spatial", "scipy.spatial._qhull",
    "shapely", "manifold3d", "svgelements", "trimesh",
    "matplotlib.textpath", "matplotlib.font_manager",
    "PySide6.QtSvg",               # SVG thumbnails in the face fields
]

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=collect_dynamic_libs("manifold3d"),
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "IPython", "PyQt5", "PyQt6", "pytest",
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
    name="Dicegrove",
    console=False,
    icon=os.path.join(APP, "packaging", "dicegrove.ico"),
    upx=False,
)
