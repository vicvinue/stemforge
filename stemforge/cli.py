"""CLI: stemforge cancion.mp3 --mode stems4 [--drumsep] [--format flac]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .engine import Engine, Progress, SeparationRequest
from .presets import MODES


def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    p = argparse.ArgumentParser(prog="stemforge", description="Separa canciones en stems (Apple Silicon).")
    p.add_argument("inputs", nargs="*", type=Path, help="Archivos de audio o carpetas")
    p.add_argument("-m", "--mode", default=settings.default_mode, choices=list(MODES))
    p.add_argument("--drumsep", action="store_true", help="Dividir la batería en bombo, caja, toms, hi-hat, ride y crash")
    p.add_argument("-f", "--format", default=settings.output_format, choices=config.OUTPUT_FORMATS)
    p.add_argument("-o", "--output", type=Path, default=Path(settings.output_dir))
    p.add_argument("--bitrate", default=settings.mp3_bitrate, help="Bitrate MP3 (ej. 320k)")
    p.add_argument("-q", "--quality", default=settings.quality, choices=["balanced", "max"],
                   help="balanced: ≈2× más rápido · max: máxima calidad")
    p.add_argument("--keep-work", action="store_true", help="Conservar archivos intermedios")
    p.add_argument("--list-modes", action="store_true")
    p.add_argument("--info", action="store_true", help="Mostrar aceleración disponible")
    args = p.parse_args(argv)

    if args.list_modes:
        for m in MODES.values():
            print(f"{m.key:15} {m.name}\n{'':15} {m.description}")
        return 0
    if args.info:
        print(Engine.device_info())
        return 0
    if not args.inputs:
        p.error("indica al menos un archivo de audio")

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files += sorted(f for f in item.iterdir() if f.suffix.lower() in config.AUDIO_EXTENSIONS)
        elif item.exists():
            files.append(item)
        else:
            print(f"No existe: {item}", file=sys.stderr)

    engine = Engine()
    failures = 0
    for f in files:
        def on_progress(pr: Progress):
            tag = "descargando modelo" if pr.downloading else pr.step_label
            sys.stdout.write(f"\r  {pr.overall * 100:5.1f}%  {tag[:60]:60}")
            sys.stdout.flush()

        req = SeparationRequest(input_path=f.resolve(), mode=args.mode, drumsep=args.drumsep,
                                output_dir=args.output, output_format=args.format,
                                mp3_bitrate=args.bitrate, quality=args.quality, keep_workdir=args.keep_work)
        try:
            res = engine.separate(req, on_progress=on_progress, on_log=lambda m: print(f"\n{m}"))
        except Exception as exc:  # seguir con el siguiente archivo
            failures += 1
            print(f"\n❌ {f.name}: {exc}", file=sys.stderr)
            continue
        for w in res.warnings:
            print(f"⚠️ {w}")
        for path in res.stems.values():
            print(f"   {path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
