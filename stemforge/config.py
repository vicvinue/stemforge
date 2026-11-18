"""Rutas y ajustes persistentes de StemForge."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import osutil

APP_NAME = osutil.APP_NAME
SUPPORT_DIR = osutil.support_dir()
MODELS_DIR = SUPPORT_DIR / "models"
WORK_DIR = SUPPORT_DIR / "work"
SETTINGS_FILE = SUPPORT_DIR / "settings.json"
DEFAULT_OUTPUT_DIR = osutil.music_dir() / APP_NAME

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif", ".wma", ".opus", ".mp4"}
OUTPUT_FORMATS = ("wav", "flac", "mp3")


@dataclass
class Settings:
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    output_format: str = "wav"   # wav | flac | mp3
    mp3_bitrate: str = "320k"
    default_mode: str = "stems4"
    quality: str = "balanced"     # balanced | max
    drumsep: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)


def ensure_dirs() -> None:
    for d in (SUPPORT_DIR, MODELS_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
    ensure_ffmpeg()


def ensure_ffmpeg() -> str | None:
    """Garantiza un `ffmpeg` en el PATH (audio-separator lo invoca por nombre).

    Usa el del sistema si existe; si no, el binario estático que trae el paquete imageio-ffmpeg
    (la app empaquetada no depende de Homebrew). Devuelve la ruta usada.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None
    bin_dir = SUPPORT_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / ("ffmpeg.exe" if osutil.IS_WINDOWS else "ffmpeg")
    if not _point_to(link, exe):
        return None
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return str(link)


def _point_to(link: Path, exe: Path) -> bool:
    """Deja en `link` el ejecutable `exe`: symlink si se puede, si no una copia (Windows)."""
    try:
        if link.is_symlink():
            if link.resolve() == exe.resolve():
                return True
            link.unlink()
        elif link.exists():
            if link.stat().st_size == exe.stat().st_size:
                return True
            link.unlink()
        if not osutil.IS_WINDOWS:
            try:
                link.symlink_to(exe)
                return True
            except OSError:
                pass
        shutil.copy2(exe, link)
        return True
    except OSError:
        return False
