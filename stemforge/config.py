"""Rutas y ajustes persistentes de StemForge."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "StemForge"
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
MODELS_DIR = SUPPORT_DIR / "models"
WORK_DIR = SUPPORT_DIR / "work"
SETTINGS_FILE = SUPPORT_DIR / "settings.json"
DEFAULT_OUTPUT_DIR = Path.home() / "Music" / APP_NAME

# Modelos Demucs que trae la app UVR instalada: se enlazan para no descargarlos otra vez.
UVR_DEMUCS_DIR = Path(
    "/Applications/Ultimate Vocal Remover.app/Contents/Resources/models/Demucs_Models/v3_v4_repo"
)

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
            data = json.loads(SETTINGS_FILE.read_text())
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            return cls(**known)
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        os.replace(tmp, SETTINGS_FILE)


def ensure_dirs() -> None:
    for d in (SUPPORT_DIR, MODELS_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
    link_uvr_models()


def link_uvr_models() -> int:
    """Enlaza (symlink) los pesos Demucs de UVR en la carpeta de modelos. Devuelve cuántos enlazó."""
    if not UVR_DEMUCS_DIR.is_dir():
        return 0
    count = 0
    for src in UVR_DEMUCS_DIR.iterdir():
        if src.suffix not in {".th", ".yaml"}:
            continue
        dst = MODELS_DIR / src.name
        if not dst.exists():
            try:
                dst.symlink_to(src)
                count += 1
            except OSError:
                pass
    return count
