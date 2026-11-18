"""API local (solo 127.0.0.1) + interfaz web de StemForge."""
from __future__ import annotations

import secrets
import uuid
import zipfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel

from . import __version__, config, osutil
from .engine import Engine, SeparationRequest
from .jobs import JobManager
from .presets import public_modes, public_stems, public_tiers, plan_for, MODES

WEB_DIR = Path(__file__).parent / "web"
TOKEN = secrets.token_urlsafe(24)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}

config.ensure_dirs()
settings = config.Settings.load()
manager = JobManager(Engine())
app = FastAPI(title="StemForge", docs_url=None, redoc_url=None, openapi_url=None)


def guard(request: Request) -> None:
    """Protege la API local frente a otras webs (CSRF / DNS rebinding)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        raise HTTPException(403, "Host no permitido")
    token = request.headers.get("x-stemforge-token") or request.query_params.get("token")
    if not token or not secrets.compare_digest(token, TOKEN):
        raise HTTPException(403, "Token inválido")


def _job_or_404(job_id: str):
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    return job


# ---------------------------------------------------------------------------- UI
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    host = (request.headers.get("host") or "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        raise HTTPException(403)
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__STEMFORGE_TOKEN__", TOKEN),
                        headers={"Cache-Control": "no-store"})


@app.get("/static/{name}")
def static(name: str):
    path = (WEB_DIR / name).resolve()
    if path.parent != WEB_DIR.resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------------------- API
class SettingsIn(BaseModel):
    output_dir: str | None = None
    output_format: str | None = None
    mp3_bitrate: str | None = None
    default_mode: str | None = None
    quality: str | None = None
    drumsep: bool | None = None


@app.get("/api/info", dependencies=[Depends(guard)])
def info():
    return {"modes": public_modes(), "tiers": public_tiers(), "stems": public_stems(), "settings": settings.__dict__, "device": Engine.device_info(),
            "version": __version__,
            "formats": list(config.OUTPUT_FORMATS)}


@app.post("/api/settings", dependencies=[Depends(guard)])
def update_settings(body: SettingsIn):
    data = body.model_dump(exclude_none=True)
    if "output_format" in data and data["output_format"] not in config.OUTPUT_FORMATS:
        raise HTTPException(400, "Formato no válido")
    if "default_mode" in data and data["default_mode"] not in MODES:
        raise HTTPException(400, "Modo no válido")
    if "quality" in data and data["quality"] not in ("balanced", "max"):
        raise HTTPException(400, "Calidad no válida")
    if "output_dir" in data:
        out = Path(data["output_dir"]).expanduser()
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(400, f"No se puede usar la carpeta: {exc}") from exc
        data["output_dir"] = str(out)
    for k, v in data.items():
        setattr(settings, k, v)
    settings.save()
    return settings.__dict__


@app.post("/api/choose-folder", dependencies=[Depends(guard)])
def choose_folder():
    """Abre el selector nativo de carpetas (macOS, Windows o Linux)."""
    path = osutil.choose_folder("Carpeta de salida de StemForge", settings.output_dir)
    if not path:
        return {"path": None}
    update_settings(SettingsIn(output_dir=path))
    return {"path": settings.output_dir}


@app.post("/api/jobs", dependencies=[Depends(guard)])
async def create_jobs(
    files: list[UploadFile] = File(...),
    mode: str = Form("stems4"),
    drumsep: bool = Form(False),
    stems: str = Form(""),          # "" o "all" = todos; si no, claves separadas por coma
    mix_selection: bool = Form(False),
    quality: str = Form("balanced"),
    output_format: str = Form("wav"),
):
    if mode not in MODES:
        raise HTTPException(400, "Modo no válido")
    if output_format not in config.OUTPUT_FORMATS:
        raise HTTPException(400, "Formato no válido")
    selected = [s for s in stems.split(",") if s.strip()] if stems.strip().lower() not in ("", "all") else None
    try:
        _, _, chosen = plan_for(mode, drumsep, selected)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    selected = chosen if selected else None
    created = []
    for upload in files:
        name = Path(upload.filename or "audio").name
        if Path(name).suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        updir = config.WORK_DIR / "uploads" / uuid.uuid4().hex
        updir.mkdir(parents=True, exist_ok=True)
        dst = updir / name
        with dst.open("wb") as fh:
            while chunk := await upload.read(1 << 20):
                fh.write(chunk)
        req = SeparationRequest(input_path=dst, mode=mode, drumsep=drumsep, stems=selected,
                                mix_selection=bool(mix_selection and selected), quality=quality,
                                output_dir=Path(settings.output_dir), output_format=output_format,
                                mp3_bitrate=settings.mp3_bitrate)
        created.append(manager.submit(req, name, upload_dir=updir).to_dict())
    if not created:
        raise HTTPException(400, "Ningún archivo de audio compatible")
    return created


@app.get("/api/jobs", dependencies=[Depends(guard)])
def list_jobs():
    return [j.to_dict() for j in manager.list()]


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(guard)])
def cancel_job(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.cancel(job_id)}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(guard)])
def delete_job(job_id: str):
    _job_or_404(job_id)
    return {"ok": manager.remove(job_id)}


def _stem_path(job_id: str, key: str) -> Path:
    job = _job_or_404(job_id)
    for s in job.stems:
        if s["key"] == key:
            p = Path(s["path"])
            if p.is_file():
                return p
    raise HTTPException(404, "Stem no encontrado")


@app.get("/api/jobs/{job_id}/stems/{key}", dependencies=[Depends(guard)])
def get_stem(job_id: str, key: str):
    p = _stem_path(job_id, key)
    return FileResponse(p, filename=p.name)


@app.get("/api/jobs/{job_id}/zip", dependencies=[Depends(guard)])
def zip_job(job_id: str):
    job = _job_or_404(job_id)
    if job.status != "done":
        raise HTTPException(400, "El trabajo no ha terminado")
    zips = config.WORK_DIR / "zips"
    zips.mkdir(parents=True, exist_ok=True)
    tmp = zips / f"{job.id}-{uuid.uuid4().hex[:6]}.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
        for s in job.stems:
            p = Path(s["path"])
            if p.is_file():
                zf.write(p, arcname=p.name)
    name = Path(job.output_folder or "stems").name + ".zip"
    return FileResponse(tmp, media_type="application/zip", filename=name,
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@app.post("/api/jobs/{job_id}/reveal", dependencies=[Depends(guard)])
def reveal(job_id: str):
    job = _job_or_404(job_id)
    if not job.output_folder or not Path(job.output_folder).exists():
        raise HTTPException(404, "Carpeta no encontrada")
    return {"ok": osutil.open_folder(job.output_folder)}


@app.post("/api/open-output", dependencies=[Depends(guard)])
def open_output():
    out = Path(settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    return {"ok": osutil.open_folder(out)}
