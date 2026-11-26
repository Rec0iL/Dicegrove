"""QObject exposed to QML: job queue + settings."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import (Property, QAbstractListModel, QModelIndex, QObject,
                            Qt, QThread, QUrl, Signal, Slot)
from PySide6.QtGui import QDesktopServices

from . import core
from .settings import Store
from .worker import Worker


class JobModel(QAbstractListModel):
    _FIELDS = ["jobId", "name", "source", "sourceDir", "output", "progress", "status", "message"]
    ROLE = {Qt.UserRole + 1 + i: f.encode() for i, f in enumerate(_FIELDS)}

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []

    def roleNames(self):  # noqa: N802
        return self.ROLE

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        name = self.ROLE.get(role)
        return self.rows[index.row()].get(name.decode()) if name else None

    def append(self, row: dict[str, Any]) -> None:
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows))
        self.rows.append(row)
        self.endInsertRows()

    def find(self, job_id: int) -> int:
        for i, r in enumerate(self.rows):
            if r["jobId"] == job_id:
                return i
        return -1

    def update(self, job_id: int, **fields: Any) -> None:
        i = self.find(job_id)
        if i < 0:
            return
        self.rows[i].update(fields)
        idx = self.index(i)
        roles = [r for r, n in self.ROLE.items() if n.decode() in fields]
        self.dataChanged.emit(idx, idx, roles)

    def remove_where(self, pred) -> None:
        for i in range(len(self.rows) - 1, -1, -1):
            if pred(self.rows[i]):
                self.beginRemoveRows(QModelIndex(), i, i)
                del self.rows[i]
                self.endRemoveRows()


class Backend(QObject):
    settingsChanged = Signal()
    stateChanged = Signal()
    toast = Signal(str)
    fillFaces = Signal("QVariantList")   # SVG paths for the face fields (drop / Open with)
    _startJob = Signal(int, str, dict)

    def __init__(self) -> None:
        super().__init__()
        self.store = Store()
        self.model = JobModel()
        self._next_id = 1
        self._running: int | None = None

        self.thread = QThread()
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self._startJob.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.thread.start()

    # ------------------------------------------------------------------ lifecycle
    def shutdown(self) -> None:
        self.worker.cancel_event.set()
        self.thread.quit()
        self.thread.wait(5000)

    # ------------------------------------------------------------------ properties
    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return dict(self.store.data)

    @Property(QObject, constant=True)
    def jobs(self):
        return self.model

    @Property(float, notify=stateChanged)
    def overallProgress(self):  # noqa: N802
        rows = self.model.rows
        if not rows:
            return 0.0
        return sum(1.0 if r["status"] in ("done", "error", "skipped") else r["progress"]
                   for r in rows) / len(rows)

    @Property(bool, notify=stateChanged)
    def busy(self):
        return any(r["status"] in ("queued", "working") for r in self.model.rows)

    @Property(int, notify=stateChanged)
    def jobCount(self):  # noqa: N802
        return len(self.model.rows)

    @Property(int, notify=stateChanged)
    def doneCount(self):  # noqa: N802
        return sum(1 for r in self.model.rows if r["status"] in ("done", "error", "skipped"))

    @Property(str, notify=stateChanged)
    def mascotState(self):  # noqa: N802
        rows = self.model.rows
        if any(r["status"] in ("queued", "working") for r in rows):
            return "working"
        if any(r["status"] == "error" for r in rows):
            return "error"
        if any(r["status"] == "done" for r in rows):
            return "done"
        return "idle"



    # ------------------------------------------------------------------ settings
    @Slot(str, "QVariant")
    def setSetting(self, key: str, value: Any) -> None:  # noqa: N802
        if self.store.set(key, value):
            self.settingsChanged.emit()

    # ------------------------------------------------------------------ queue
    @Slot("QVariantList")
    def addUrls(self, urls: list) -> None:  # noqa: N802
        paths: list[str] = []
        for u in urls:
            s = u.toLocalFile() if isinstance(u, QUrl) else QUrl(str(u)).toLocalFile() or str(u)
            if s:
                paths.append(s)
        self.addPaths(paths)

    def addPaths(self, paths: list[str]) -> None:  # noqa: N802
        """Dropped / Open-with paths fill the face fields; only .dicejob files are
        queued directly (the "Make die" button and retries go through makeDie)."""
        if not paths:
            return
        if not any(p.endswith(core.JOB_SUFFIX) for p in paths):
            svgs = [str(f) for f in core.face_files(paths)]
            if not svgs:
                self.toast.emit("No SVG files found")
                return
            self.store.set("lastDir", str(Path(svgs[0]).parent))
            self.settingsChanged.emit()
            self.fillFaces.emit(svgs)
            return
        items = core.expand_inputs(paths)
        if not items:
            self.toast.emit("No SVG files found")
            return
        first_parent = str(Path(paths[0]).parent)
        self.store.set("lastDir", first_parent)
        self.settingsChanged.emit()
        for p in items:
            self.model.append({
                "jobId": self._next_id, "name": p.stem if p.suffix == core.JOB_SUFFIX else p.name, "source": str(p),
                "sourceDir": str(p.parent), "output": "", "progress": 0.0,
                "status": "queued", "message": "Waiting…",
            })
            self._next_id += 1
        self.stateChanged.emit()
        self._pump()

    @Slot("QVariantList", result="QVariantList")
    def expandFaces(self, urls: list) -> list:  # noqa: N802
        """URLs dropped on one face field -> SVG paths in face order (folders sorted)."""
        paths = [QUrl(str(u)).toLocalFile() or str(u) for u in urls]
        svgs = [str(f) for f in core.face_files(paths)]
        if svgs:
            self.store.set("lastDir", str(Path(svgs[0]).parent))
            self.settingsChanged.emit()
        else:
            self.toast.emit("No SVG files found")
        return svgs

    @Slot(int, "QVariantList", "QVariantList")
    def makeDie(self, sides: int, faces: list, rotations: list) -> None:  # noqa: N802
        """Queue one die/coin: faces[k] = SVG for face k+1 ("" = its number)."""
        try:
            job = core.write_job(sides, [str(f or "") for f in faces], [int(r) for r in rotations])
        except (core.CoreError, OSError) as exc:
            self.toast.emit(str(exc))
            return
        self.addPaths([str(job)])

    @Slot(int)
    def removeJob(self, job_id: int) -> None:  # noqa: N802
        i = self.model.find(job_id)
        if i >= 0 and self.model.rows[i]["status"] != "working":
            self.model.remove_where(lambda r: r["jobId"] == job_id)
            self.stateChanged.emit()

    @Slot()
    def clearFinished(self) -> None:  # noqa: N802
        self.model.remove_where(lambda r: r["status"] in ("done", "error", "skipped"))
        self.stateChanged.emit()

    @Slot()
    def retryFailed(self) -> None:  # noqa: N802
        for r in self.model.rows:
            if r["status"] == "error":
                self.model.update(r["jobId"], status="queued", progress=0.0, output="", message="Waiting…")
        self.stateChanged.emit()
        self._pump()

    def _out_dir_for(self, src: str) -> str:
        s = self.store.data
        if s["outputMode"] == "custom" and s["customDir"]:
            return s["customDir"]
        return str(Path(src).parent)  # next to where it came from

    def _pump(self) -> None:
        if self._running is not None:
            return
        for r in self.model.rows:
            if r["status"] == "queued":
                self._running = r["jobId"]
                s = self.store.data
                self.model.update(r["jobId"], status="working", message="Starting…")
                self.stateChanged.emit()
                opts = {k: s[k] for k in core.OPTION_DEFAULTS}
                opts.update({"outDir": self._out_dir_for(r["source"]), "overwrite": s["overwrite"]})
                self._startJob.emit(r["jobId"], r["source"], opts)
                return
        self.stateChanged.emit()

    @Slot(int, float, str)
    def _on_progress(self, job_id: int, frac: float, msg: str) -> None:
        self.model.update(job_id, progress=frac, message=msg)
        self.stateChanged.emit()

    @Slot(int, str, str, str, bool)
    def _on_finished(self, job_id: int, status: str, output: str, message: str, in_place: bool) -> None:
        i = self.model.find(job_id)
        self._running = None
        if i >= 0:
            row = self.model.rows[i]
            self.model.update(job_id, status=status, output=output, message=message,
                              progress=1.0 if status != "error" else row["progress"])
        self.stateChanged.emit()
        self._pump()
        if not self.busy:
            self._notify_done()

    def _notify_done(self) -> None:
        """Desktop notification when the queue is empty (dice take a while)."""
        rows = self.model.rows
        done = sum(1 for r in rows if r["status"] == "done")
        failed = sum(1 for r in rows if r["status"] == "error")
        if not rows or not shutil.which("notify-send"):
            return
        body = f"{done} finished" + (f", {failed} failed" if failed else "")
        last = next((r for r in reversed(rows) if r["status"] == "done"), None)
        if last:
            body += f" - {last['message']}"
        try:
            subprocess.Popen(["notify-send", "-a", "Dicegrove", "-i", "dicegrove",
                              "Your dice are ready!" if not failed else "Dicegrove", body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    # ------------------------------------------------------------------ misc
    @Slot(str)
    def reveal(self, path: str) -> None:
        if not path:
            return
        p = Path(path)
        target = p.parent if p.is_file() or not p.exists() else p
        if not target.exists():
            target = target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


    @Slot(str, result=str)
    def toLocalPath(self, url: str) -> str:  # noqa: N802
        return QUrl(url).toLocalFile()
