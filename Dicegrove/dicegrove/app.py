"""Qt Quick bootstrap."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .backend import Backend

ROOT = Path(__file__).resolve().parent.parent


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QCoreApplication.setApplicationName("Dicegrove")
    QCoreApplication.setOrganizationName("Dicegrove")
    QQuickStyle.setStyle("Basic")  # fully custom-styled controls
    app = QGuiApplication(argv)
    app.setDesktopFileName("dicegrove")
    icon = ROOT / "packaging" / "dicegrove.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    backend = Backend()
    app.aboutToQuit.connect(backend.shutdown)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    # DICEGROVE_SELFTEST=<file>: load the UI, write QML problems to <file>, quit with 0/1
    # (used by the Windows build to check that every Qt/QML module made it into the exe)
    selftest = os.environ.get("DICEGROVE_SELFTEST")
    problems: list[str] = []
    if selftest:
        engine.warnings.connect(lambda ws: problems.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(str(ROOT / "qml" / "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()  # stop the worker thread, else Qt aborts on exit
        if selftest:
            Path(selftest).write_text("FAILED: Main.qml did not load\n" + "\n".join(problems), encoding="utf-8")
        return 1
    if selftest:
        # waits for jobs given on the command line (.dicejob files), max ~10 min
        waited = [0]

        def finish() -> None:
            if backend.busy and waited[0] < 600:
                waited[0] += 1
                QTimer.singleShot(1000, finish)
                return
            jobs = [f"{r['status']}: {r['name']} | {r['message']}" for r in backend.model.rows]
            ok = not problems and all(r["status"] == "done" for r in backend.model.rows)
            Path(selftest).write_text("\n".join(["OK" if ok else "FAILED", *problems, *jobs]),
                                      encoding="utf-8")
            app.exit(0 if ok else 1)
        QTimer.singleShot(4000, finish)

    # Files passed on the command line (droplet / "Open with") are queued right away.
    cli = [a for a in argv[1:] if not a.startswith("-")]
    if cli:
        backend.addPaths(cli)
    rc = app.exec()
    # Tear the engine down while `backend` is still alive, otherwise bindings
    # re-evaluate against a null context object and spam TypeErrors on exit.
    del engine
    return rc
