"""Cola de trabajos: un solo hilo trabajador (la GPU se usa de a un trabajo)."""
from __future__ import annotations

import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .engine import Engine, JobCancelled, Progress, SeparationRequest
from .presets import STEM_LABELS, MODES


@dataclass
class Job:
    id: str
    request: SeparationRequest
    filename: str
    status: str = "queued"           # queued | running | done | error | cancelled
    progress: float = 0.0
    step_label: str = "En cola"
    downloading: bool = False
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    output_folder: str | None = None
    stems: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode_used: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    upload_dir: Path | None = None   # carpeta temporal a borrar al terminar
    bpm: float | None = None
    beats: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        req = self.request
        return {
            "id": self.id, "filename": self.filename, "status": self.status,
            "progress": self.progress, "step_label": self.step_label, "downloading": self.downloading,
            "logs": self.logs[-40:], "error": self.error, "output_folder": self.output_folder,
            "stems": self.stems, "warnings": self.warnings,
            "mode": req.mode, "mode_name": MODES[req.mode].name,
            "mode_used": self.mode_used, "mode_used_name": MODES[self.mode_used].name if self.mode_used else "",
            "drumsep": req.drumsep,
            "selected": [STEM_LABELS[k] for k in req.stems] if req.stems else None,
            "mix_selection": req.mix_selection,
            "format": req.output_format, "quality": req.quality, "bpm": self.bpm,
            "created": self.created, "started": self.started, "finished": self.finished,
            "elapsed": ((self.finished or time.time()) - self.started) if self.started else 0,
        }


class JobManager:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or Engine()
        self.jobs: dict[str, Job] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, name="stemforge-worker", daemon=True)
        self._worker.start()

    # -- API ------------------------------------------------------------------------
    def submit(self, request: SeparationRequest, filename: str, upload_dir: Path | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], request=request, filename=filename, upload_dir=upload_dir)
        with self._lock:
            self.jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created)

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in {"done", "error", "cancelled"}:
            return False
        job.cancel.set()
        if job.status == "queued":
            self._finish(job, "cancelled")
        return True

    def remove(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status in {"queued", "running"}:
            return False
        with self._lock:
            self.jobs.pop(job_id, None)
        return True

    # -- trabajador ----------------------------------------------------------------
    def _finish(self, job: Job, status: str, error: str | None = None) -> None:
        job.status = status
        job.error = error
        job.finished = time.time()
        if status == "cancelled":
            job.step_label = "Cancelado"
        if job.upload_dir:
            shutil.rmtree(job.upload_dir, ignore_errors=True)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.jobs.get(job_id)
            if job is None or job.status != "queued":
                continue
            job.status, job.started, job.step_label = "running", time.time(), "Preparando"

            def on_progress(p: Progress, job=job):
                job.progress = p.overall
                job.downloading = p.downloading
                job.step_label = "Descargando modelo…" if p.downloading else (p.step_label or job.step_label)

            def on_log(msg: str, job=job):
                job.logs.append(msg)

            try:
                res = self.engine.separate(job.request, on_progress, on_log, job.cancel)
            except JobCancelled:
                self._finish(job, "cancelled")
                continue
            except Exception as exc:  # noqa: BLE001 — se informa al usuario
                job.logs.append(f"❌ {exc}")
                self._finish(job, "error", str(exc))
                continue
            job.output_folder = str(res.output_folder)
            job.mode_used = res.mode_used
            job.warnings = res.warnings
            job.bpm, job.beats = res.bpm, res.beats
            job.stems = [
                {"key": key, "label": res.labels.get(key, STEM_LABELS.get(key, key)), "file": path.name,
                 "path": str(path)}
                for key, path in res.stems.items()
            ]
            job.progress, job.step_label = 1.0, "Completado"
            self._finish(job, "done")
