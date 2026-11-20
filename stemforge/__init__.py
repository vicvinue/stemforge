"""StemForge: separador de stems para macOS (Apple Silicon) y Windows.

IMPORTANTE: este archivo debe seguir siendo mínimo y estable. Las actualizaciones pequeñas
(ver updater.py) reemplazan el resto del paquete, pero este __init__ sigue siendo siempre el de
la instalación: lo que se agregue aquí no llegará por una actualización pequeña.
"""

__version__ = "0.4.3"

# Versión del «runtime» (Python + dependencias). Súbela cuando cambien las dependencias de
# pyproject.toml o la versión de Python: las instalaciones con otro RUNTIME no pueden recibir
# solo el código nuevo y necesitan el instalador completo. tests/test_updater.py lo vigila.
RUNTIME = 1

BUNDLED_VERSION = __version__  # la versión instalada, aunque se esté usando una actualización


def _vtuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in str(version).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _support_dir():
    """Igual que osutil.support_dir() (no se importa osutil para que también se actualice)."""
    import os
    import sys
    from pathlib import Path

    if os.environ.get("STEMFORGE_HOME"):
        return Path(os.environ["STEMFORGE_HOME"])
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "StemForge"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "StemForge"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "StemForge"


def _find_overlay(base, bundled_version: str, runtime: int, mark_trial: bool = True):
    """Devuelve (versión, carpeta del paquete) de la actualización pequeña a usar, o None.

    Solo se usa si es más nueva que la instalada y es para este mismo runtime. Si es la primera vez
    (sin confirmar) se deja una marca; si el arranque anterior dejó la marca y no confirmó, esa
    versión falló al arrancar y se vuelve a la instalada.
    """
    import json

    try:
        data = json.loads((base / "current.json").read_text(encoding="utf-8"))
        version, need = str(data["version"]), int(data["runtime"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if need != runtime or _vtuple(version) <= _vtuple(bundled_version):
        return None
    pkg = base / version / "stemforge"
    if not (pkg / "__init__.py").is_file():
        return None
    if not data.get("confirmed"):
        trial = base / "trial-boot"
        if trial.exists():
            return None
        if mark_trial:
            try:
                trial.write_text(version, encoding="utf-8")
            except OSError:
                return None
    return version, pkg


def _apply_update() -> None:
    global __version__
    from pathlib import Path
    import os

    here = Path(__file__).resolve().parent
    if (here.parent / ".git").exists() or os.environ.get("STEMFORGE_NO_UPDATES"):
        return  # copia de desarrollo: se actualiza con git, nunca con paquetes descargados
    try:
        found = _find_overlay(_support_dir() / "updates", __version__, RUNTIME)
    except Exception:
        return
    if found:
        __version__ = found[0]
        __path__[:] = [str(found[1])]


_apply_update()
