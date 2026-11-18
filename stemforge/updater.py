"""Actualizaciones automáticas desde las releases de GitHub.

Cada release publica `latest.json` (ver tools/make_update_assets.py):

    {"version": "0.3.1", "runtime": 1, "notes_url": "...",
     "app":  {"name": "stemforge-app-0.3.1.zip", "url": "...", "sha256": "...", "size": 312345},
     "full": {"mac-arm64": [{...DMG...}], "win-cpu": [{...Setup.exe...}],
              "win-cuda": [{...CUDA-Setup.exe...}, {...-1.bin...}]}}

Métodos de actualización, del más liviano al más pesado:

- «app»: mismo runtime (Python + dependencias). Se baja solo el paquete stemforge (≈ 0,3 MB) a
  <datos>/updates/<versión>/ y stemforge/__init__.py lo carga desde ahí al reiniciar. No se toca la
  instalación (la firma del .app de macOS sigue válida). Si no arranca, se vuelve a la instalada.
- «full»: cambió el runtime. Se baja el instalador de esta plataforma (DMG, Setup.exe CPU o CUDA),
  se instala al cerrar la app y se vuelve a abrir.
- «git»: copia de desarrollo: git pull (+ reinstalar dependencias si cambiaron).
- «manual»: no se puede automatizar (p. ej. carpeta portable de Windows): se abre la página de la release.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

import stemforge

from . import osutil

REPO = "vicvinue/stemforge"
RELEASES_URL = f"https://github.com/{REPO}/releases"
MANIFEST_URL = f"{RELEASES_URL}/latest/download/latest.json"
CHECK_CACHE_SECONDS = 6 * 3600
WINDOWS_APP_ARGS = ["-I", "-B", "-X", "utf8", "-m", "stemforge.app"]

_quit_handler: Callable[[], None] | None = None


def set_quit_handler(handler: Callable[[], None] | None) -> None:
    """app.py registra cómo cerrar la ventana/servidor de forma ordenada."""
    global _quit_handler
    _quit_handler = handler


def vtuple(version: str) -> tuple[int, ...]:
    return stemforge._vtuple(version)


def updates_dir() -> Path:
    return osutil.support_dir() / "updates"


def manifest_url() -> str:
    return os.environ.get("STEMFORGE_UPDATE_URL") or MANIFEST_URL


# --------------------------------------------------------------------- instalación
def install_kind() -> str:
    """mac-app | win-installer | win-portable | git | python"""
    pkg = Path(stemforge.__file__).resolve().parent      # el paquete instalado (no la actualización)
    if (pkg.parent / ".git").exists():
        return "git"
    exe = Path(sys.executable).resolve()
    if osutil.IS_MAC and app_bundle() is not None:
        return "mac-app"
    if osutil.IS_WINDOWS:
        root = exe.parent.parent                          # {app}\python\pythonw.exe -> {app}
        if exe.parent.name.lower() == "python" and (root / "StemForge.ico").is_file():
            return "win-installer" if any(root.glob("unins*.exe")) else "win-portable"
    return "python"


def app_bundle() -> Path | None:
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def platform_key() -> str | None:
    if osutil.IS_MAC:
        return "mac-arm64"
    if osutil.IS_WINDOWS:
        try:
            import torch

            return "win-cuda" if torch.version.cuda else "win-cpu"
        except Exception:
            return "win-cpu"
    return None


def plan(manifest: dict, current: str, runtime: int, kind: str, pkey: str | None,
         failed: set[str] | frozenset = frozenset()) -> dict:
    """Decide cómo actualizar. Función pura (se prueba sin red)."""
    latest = str(manifest.get("version", ""))
    out = {"latest": latest, "available": bool(latest) and vtuple(latest) > vtuple(current),
           "notes_url": manifest.get("notes_url") or f"{RELEASES_URL}/tag/v{latest}",
           "method": None, "files": [], "size": 0}
    if not out["available"]:
        return out
    app_asset = manifest.get("app")
    full = (manifest.get("full") or {}).get(pkey or "") or []
    if kind == "git":
        out["method"] = "git"
    elif app_asset and manifest.get("runtime") == runtime and latest not in failed:
        out["method"], out["files"] = "app", [app_asset]
    elif kind in ("mac-app", "win-installer") and full:
        out["method"], out["files"] = "full", list(full)
    else:
        out["method"] = "manual"
    out["size"] = sum(int(f.get("size") or 0) for f in out["files"])
    return out


# ------------------------------------------------------------------------ estado
def _state_file() -> Path:
    return updates_dir() / "state.json"


def _load_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(data: dict) -> None:
    updates_dir().mkdir(parents=True, exist_ok=True)
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _state_file())


def confirm_boot() -> None:
    """La versión actual arrancó bien: si es una actualización pequeña, queda confirmada."""
    base = updates_dir()
    if stemforge.__version__ == stemforge.BUNDLED_VERSION:
        return
    try:
        cur = base / "current.json"
        data = json.loads(cur.read_text(encoding="utf-8"))
        if str(data.get("version")) == stemforge.__version__ and not data.get("confirmed"):
            data["confirmed"] = True
            _write_json(cur, data)
        (base / "trial-boot").unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def housekeeping() -> None:
    """Detecta una actualización pequeña que no arrancó y borra versiones viejas descargadas."""
    base = updates_dir()
    if not base.is_dir():
        return
    state = _load_state()
    cur_file = base / "current.json"
    try:
        cur = json.loads(cur_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cur = None
    trial = base / "trial-boot"
    if cur and not cur.get("confirmed") and trial.exists() and stemforge.__version__ != cur.get("version"):
        failed = set(state.get("failed", [])) | {str(cur.get("version"))}
        state["failed"] = sorted(failed)
        _save_state(state)
        cur_file.unlink(missing_ok=True)
        trial.unlink(missing_ok=True)
        cur = None
    keep = {str(cur.get("version"))} if cur else set()
    if stemforge.__version__ != stemforge.BUNDLED_VERSION:
        keep.add(stemforge.__version__)
    for child in base.iterdir():
        if child.is_dir() and child.name not in keep and child.name != "downloads":
            if vtuple(child.name) > (0,):
                shutil.rmtree(child, ignore_errors=True)
    shutil.rmtree(base / "downloads", ignore_errors=True)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------------- red
def _ssl_context():
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": f"StemForge/{stemforge.__version__}",
                                               "Cache-Control": "no-cache"})
    if url.startswith("https://"):
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest() -> dict:
    with _open(manifest_url(), timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError("latest.json no válido")
    return data


def download(asset: dict, dest_dir: Path, on_bytes: Callable[[int], None] | None = None) -> Path:
    """Descarga un asset y verifica su SHA-256. Devuelve la ruta final."""
    name = Path(str(asset["name"])).name
    if not name or name in (".", ".."):
        raise ValueError("Nombre de archivo no válido en latest.json")
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    part = dest_dir / (name + ".part")
    digest = hashlib.sha256()
    with _open(str(asset["url"]), timeout=60) as resp, open(part, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            digest.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    if digest.hexdigest().lower() != str(asset.get("sha256", "")).lower():
        part.unlink(missing_ok=True)
        raise ValueError(f"{name}: la suma SHA-256 no coincide (descarga dañada o alterada)")
    os.replace(part, final)
    return final


def extract_app(zip_path: Path, version: str) -> Path:
    """Descomprime el paquete en updates/<versión>/ sin permitir rutas fuera de esa carpeta."""
    base = updates_dir()
    target = base / version
    tmp = base / f"{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    root = tmp.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            dest = (tmp / member.filename).resolve()
            if dest != root and root not in dest.parents:
                raise ValueError(f"Ruta no permitida en el paquete: {member.filename}")
        zf.extractall(tmp)
    if not (tmp / "stemforge" / "__init__.py").is_file():
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("El paquete de actualización no contiene stemforge/")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return target


# --------------------------------------------------------------------- Updater
class Updater:
    """Estado compartido de la actualización (lo consulta la interfaz)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._manifest: dict | None = None
        self._plan: dict = {}
        self._checked_at = 0.0
        self._files: list[Path] = []
        self.status: dict = self._base_status()

    def _base_status(self) -> dict:
        return {"current": stemforge.__version__, "installed": stemforge.BUNDLED_VERSION,
                "kind": install_kind(), "state": "idle", "available": False, "latest": None,
                "method": None, "size": 0, "notes_url": None, "progress": 0.0, "error": None,
                "checked_at": None}

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.status)

    def _set(self, **kw) -> None:
        with self._lock:
            self.status.update(kw)

    # -- buscar --------------------------------------------------------------------
    def check(self, force: bool = False) -> dict:
        with self._lock:
            busy = self.status["state"] in ("downloading", "ready", "applying")
            fresh = self._manifest is not None and time.time() - self._checked_at < CHECK_CACHE_SECONDS
        if busy or (fresh and not force):
            return self.snapshot()
        self._set(state="checking", error=None)
        try:
            manifest = fetch_manifest()
        except Exception as exc:
            self._set(state="error", error=f"No se pudo consultar GitHub: {exc}")
            return self.snapshot()
        failed = set(_load_state().get("failed", []))
        p = plan(manifest, stemforge.__version__, stemforge.RUNTIME, install_kind(), platform_key(), failed)
        with self._lock:
            self._manifest, self._checked_at = manifest, time.time()
            self.status.update(state="available" if p["available"] else "uptodate", available=p["available"],
                               latest=p["latest"], method=p["method"], size=p["size"],
                               notes_url=p["notes_url"], progress=0.0, error=None,
                               checked_at=time.strftime("%Y-%m-%d %H:%M"))
            self._plan = p
        return self.snapshot()

    # -- descargar -----------------------------------------------------------------
    def start_download(self) -> dict:
        with self._lock:
            if self.status["state"] != "available" or self.status["method"] in (None, "manual"):
                return dict(self.status)
            self.status.update(state="downloading", progress=0.0, error=None)
            p = self._plan
        threading.Thread(target=self._download, args=(p,), name="stemforge-update", daemon=True).start()
        return self.snapshot()

    def _download(self, p: dict) -> None:
        try:
            if p["method"] == "git":
                self._git_update()
            else:
                total = max(1, p["size"])
                done = [0]

                def on_bytes(n: int) -> None:
                    done[0] += n
                    self._set(progress=min(1.0, done[0] / total))

                dest = updates_dir() / "downloads" / p["latest"]
                self._files = [download(f, dest, on_bytes) for f in p["files"]]
                if p["method"] == "app":
                    extract_app(self._files[0], p["latest"])
                    _write_json(updates_dir() / "current.json",
                                {"version": p["latest"], "runtime": stemforge.RUNTIME, "confirmed": False})
                    (updates_dir() / "trial-boot").unlink(missing_ok=True)
            self._set(state="ready", progress=1.0)
        except Exception as exc:
            self._set(state="error", error=str(exc))

    def _git_update(self) -> None:
        root = Path(stemforge.__file__).resolve().parent.parent

        def git(*args: str) -> str:
            proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if proc.returncode != 0:
                raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip() or proc.stdout.strip()}")
            return proc.stdout.strip()

        if git("status", "--porcelain", "--untracked-files=no"):
            raise RuntimeError("Hay cambios sin guardar en el repositorio: actualiza a mano con git pull.")
        if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
            raise RuntimeError("El repositorio no está en la rama main: actualiza a mano.")
        before = git("rev-parse", "HEAD")
        git("pull", "--ff-only", "origin", "main")
        if git("diff", "--name-only", before, "HEAD", "--", "pyproject.toml"):
            uv = shutil.which("uv")
            if not uv:
                raise RuntimeError("Código actualizado, pero cambiaron las dependencias: ejecuta setup otra vez.")
            proc = subprocess.run([uv, "pip", "install", "--python", sys.executable, "-e", str(root)],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"No se pudieron instalar las dependencias: {proc.stderr.strip()[-300:]}")

    # -- aplicar -------------------------------------------------------------------
    def apply(self) -> dict:
        with self._lock:
            if self.status["state"] != "ready":
                return dict(self.status)
            self.status["state"] = "applying"
            method = self.status["method"]
        try:
            if method == "full":
                self._launch_installer()
            else:
                self._relaunch()
        except Exception as exc:
            self._set(state="error", error=f"No se pudo reiniciar: {exc}")
            return self.snapshot()
        threading.Timer(0.8, quit_app).start()   # deja responder a la petición antes de cerrar
        return self.snapshot()

    def _relaunch(self) -> None:
        bundle = app_bundle() if osutil.IS_MAC else None
        if bundle is not None:
            _after_exit_posix(f'open "{_sh(bundle)}"')
        elif osutil.IS_WINDOWS:
            args = ", ".join(_ps(a) for a in sys.orig_argv[1:]) or ", ".join(_ps(a) for a in WINDOWS_APP_ARGS)
            _after_exit_windows(f"Start-Process -FilePath {_ps(sys.executable)} -ArgumentList {args} "
                                f"-WorkingDirectory {_ps(os.getcwd())}")
        else:
            cmd = " ".join(f'"{_sh(a)}"' for a in [sys.executable, *sys.orig_argv[1:]])
            _after_exit_posix(f'cd "{_sh(os.getcwd())}" && {cmd} >/dev/null 2>&1 &')

    def _launch_installer(self) -> None:
        installer = self._files[0]
        if osutil.IS_WINDOWS:
            _after_exit_windows(f"Start-Process -FilePath {_ps(installer)} -ArgumentList "
                                "'/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/RELAUNCH=1'")
            return
        bundle = app_bundle()
        if bundle is None or not os.access(bundle.parent, os.W_OK):
            subprocess.run(["open", str(installer)], check=False)   # que el usuario la arrastre
            return
        _after_exit_posix(mac_install_script(bundle, installer))


def mac_install_script(bundle: Path, dmg_path: Path) -> str:
    """Script que reemplaza StemForge.app por la del DMG y la vuelve a abrir (si falla, abre el DMG)."""
    app, dmg = _sh(bundle), _sh(dmg_path)
    return f'''
MNT="$(mktemp -d)"
if hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "{dmg}" >/dev/null; then
  rm -rf "{app}.new" "{app}.old"
  if ditto "$MNT/StemForge.app" "{app}.new"; then
    mv "{app}" "{app}.old" && mv "{app}.new" "{app}" && rm -rf "{app}.old"
  fi
  hdiutil detach "$MNT" -quiet
  rm -f "{dmg}"
  open "{app}"
else
  open "{dmg}"
fi
'''


def _sh(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _ps(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _after_exit_posix(script: str) -> None:
    pid = os.getpid()
    full = f"while kill -0 {pid} 2>/dev/null; do sleep 0.3; done\n{script}\n"
    subprocess.Popen(["/bin/sh", "-c", full], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def _after_exit_windows(command: str) -> None:
    pid = os.getpid()
    script = f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 500; {command}"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                      "-Command", script], creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def quit_app() -> None:
    """Cierra la app (ventana + servidor). Si algo se cuelga, salida forzada a los 4 s."""
    threading.Timer(4.0, lambda: os._exit(0)).start()
    if _quit_handler is not None:
        try:
            _quit_handler()
            return
        except Exception:
            pass
    os._exit(0)


updater = Updater()
