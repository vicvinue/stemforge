"""Genera los archivos que usa el actualizador de StemForge para una release.

- dist/stemforge-app-<versión>.zip  paquete stemforge (código + interfaz), para actualizaciones pequeñas
- dist/latest.json                 manifiesto: versión, runtime, y nombre/URL/tamaño/SHA-256 de cada archivo

Busca en dist/ los instaladores de esa versión (los que falten se omiten del manifiesto):
  StemForge-<v>.dmg · StemForge-<v>-Setup.exe · StemForge-<v>-CUDA-Setup.exe (+ -N.bin)

Uso:  .venv/bin/python tools/make_update_assets.py [--dist dist] [--base-url URL]
Luego se suben a la release todos los archivos listados (ver README, «Publicar una versión»).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "vicvinue/stemforge"


def read_const(name: str) -> str:
    text = (ROOT / "stemforge" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(rf"^{name}\s*=\s*['\"]?([^'\"\n]+)['\"]?", text, re.M)
    if not m:
        raise SystemExit(f"No se encontró {name} en stemforge/__init__.py")
    return m.group(1).strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_app_zip(out: Path) -> None:
    pkg = ROOT / "stemforge"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(pkg.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                continue
            if path.name.startswith("."):
                continue
            zf.write(path, Path("stemforge") / path.relative_to(pkg))


def asset(path: Path, base_url: str) -> dict:
    return {"name": path.name, "url": f"{base_url}/{path.name}", "size": path.stat().st_size,
            "sha256": sha256(path)}


def main(argv: list[str] | None = None) -> list[Path]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    ap.add_argument("--base-url", help="URL donde quedarán los archivos (por defecto, la release en GitHub)")
    args = ap.parse_args(argv)

    version, runtime = read_const("__version__"), int(read_const("RUNTIME"))
    base_url = (args.base_url or f"https://github.com/{REPO}/releases/download/v{version}").rstrip("/")
    dist = args.dist
    dist.mkdir(parents=True, exist_ok=True)

    app_zip = dist / f"stemforge-app-{version}.zip"
    build_app_zip(app_zip)
    files = [app_zip]

    full: dict[str, list[dict]] = {}
    candidates = {
        "mac-arm64": [dist / f"StemForge-{version}.dmg"],
        "win-cpu": [dist / f"StemForge-{version}-Setup.exe"],
        "win-cuda": [dist / f"StemForge-{version}-CUDA-Setup.exe",
                     *sorted(dist.glob(f"StemForge-{version}-CUDA-Setup-*.bin"))],
    }
    for key, paths in candidates.items():
        if paths[0].is_file():
            full[key] = [asset(p, base_url) for p in paths]
            files += paths
        else:
            print(f"(sin {paths[0].name}: «{key}» no tendrá actualización completa)", file=sys.stderr)

    manifest = {
        "version": version,
        "runtime": runtime,
        "notes_url": f"https://github.com/{REPO}/releases/tag/v{version}",
        "app": asset(app_zip, base_url),
        "full": full,
    }
    latest = dist / "latest.json"
    latest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    files.append(latest)
    print(f"StemForge {version} (runtime {runtime}): {app_zip.name} {app_zip.stat().st_size / 1024:.0f} KB")
    for f in files:
        print(f"  {f}")
    return files


if __name__ == "__main__":
    main()
