"""Motor de separación: ejecuta los pasos de un modo con audio-separator (PyTorch MPS / CoreML)."""
from __future__ import annotations

import gc
import json
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from . import config
from .presets import STEM_LABELS, STEM_ORDER, Mode, Step, plan_for, normalize_stem_name, MODES

log = logging.getLogger("stemforge")

SAMPLE_RATE = 44100
_STEM_IN_FILENAME = re.compile(r"_\(([^)]+)\)")


class JobCancelled(Exception):
    pass


class ModelUnavailable(Exception):
    pass


# ---------------------------------------------------------------------------
# Progreso: audio-separator / Demucs usan tqdm; interceptamos sus actualizaciones.
# ---------------------------------------------------------------------------
_progress_lock = threading.Lock()
_progress_cb: Callable[[float, str], None] | None = None


def _install_tqdm_hook() -> None:
    import tqdm.std

    if getattr(tqdm.std.tqdm, "_stemforge_hooked", False):
        return
    original_update = tqdm.std.tqdm.update

    def update(self, n=1):
        result = original_update(self, n)
        cb = _progress_cb
        if cb is not None and self.total:
            cb(min(1.0, self.n / self.total), str(getattr(self, "unit", "it")))
        return result

    tqdm.std.tqdm.update = update
    tqdm.std.tqdm._stemforge_hooked = True


# ---------------------------------------------------------------------------
@dataclass
class Progress:
    step: int = 0
    total_steps: int = 1
    step_label: str = ""
    step_fraction: float = 0.0
    downloading: bool = False

    @property
    def overall(self) -> float:
        # 5 % preparación, 90 % pasos, 5 % exportación
        if self.total_steps <= 0:
            return 0.0
        done = (self.step + self.step_fraction) / self.total_steps
        return round(0.05 + 0.90 * min(1.0, done), 4)


@dataclass
class SeparationRequest:
    input_path: Path
    mode: str = "stems4"
    drumsep: bool = False
    stems: list[str] | None = None   # stems a extraer (claves); None = todos
    output_dir: Path = config.DEFAULT_OUTPUT_DIR
    output_format: str = "wav"
    mp3_bitrate: str = "320k"
    quality: str = "balanced"   # balanced (≈2× más rápido) | max (ajustes por defecto del modelo)
    keep_workdir: bool = False


@dataclass
class SeparationResult:
    output_folder: Path
    stems: dict[str, Path] = field(default_factory=dict)   # clave -> archivo final
    mode_used: str = ""
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)


ProgressFn = Callable[[Progress], None]
LogFn = Callable[[str], None]


def ffmpeg_bin() -> str:
    for candidate in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("No se encontró ffmpeg. Instálalo con: brew install ffmpeg")


def _run_ffmpeg(args: list[str]) -> None:
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {proc.stderr.strip()[-500:]}")


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip().strip(".")
    return name[:150] or "audio"


def decode_to_wav(src: Path, dst: Path) -> float:
    """Decodifica cualquier formato a WAV float32 estéreo 44.1 kHz. Devuelve la duración en s."""
    _run_ffmpeg(["-i", str(src), "-vn", "-ac", "2", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_f32le", str(dst)])
    info = sf.info(str(dst))
    if info.frames == 0:
        raise RuntimeError("El archivo de audio está vacío o no se pudo decodificar.")
    return info.frames / info.samplerate


def _read(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if sr != SAMPLE_RATE:
        raise RuntimeError(f"Frecuencia de muestreo inesperada {sr} en {path.name}")
    return data


def mix_files(paths: list[Path], dst: Path) -> Path:
    """Suma varios WAV (alineados al inicio) en un WAV float32."""
    arrays = [_read(p) for p in paths]
    length = max(a.shape[0] for a in arrays)
    channels = max(a.shape[1] for a in arrays)
    total = np.zeros((length, channels), dtype=np.float32)
    for a in arrays:
        if a.shape[1] != channels:
            a = np.repeat(a[:, :1], channels, axis=1)
        total[: a.shape[0]] += a
    sf.write(str(dst), total, SAMPLE_RATE, subtype="FLOAT")
    return dst


def export(src: Path, dst: Path, fmt: str, mp3_bitrate: str = "320k") -> Path:
    if fmt == "wav":
        codec = ["-c:a", "pcm_s24le"]
    elif fmt == "flac":
        codec = ["-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
    elif fmt == "mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", mp3_bitrate]
    else:
        raise ValueError(f"Formato no soportado: {fmt}")
    _run_ffmpeg(["-i", str(src), *codec, str(dst)])
    return dst


def stem_from_filename(path: Path) -> str | None:
    matches = _STEM_IN_FILENAME.findall(path.stem)
    return normalize_stem_name(matches[-1]) if matches else None


# ---------------------------------------------------------------------------
class Engine:
    """Ejecuta separaciones. No es reentrante: usar un solo trabajador a la vez."""

    def __init__(self, models_dir: Path = config.MODELS_DIR):
        self.models_dir = models_dir
        self._lock = threading.Lock()
        _install_tqdm_hook()

    # -- utilidades -----------------------------------------------------------------
    @staticmethod
    def device_info() -> dict:
        import platform

        info = {"machine": platform.machine(), "mps": False, "coreml": False}
        try:
            import torch

            info["mps"] = bool(torch.backends.mps.is_available())
            info["torch"] = torch.__version__
        except Exception:  # pragma: no cover
            pass
        try:
            import onnxruntime as ort

            info["coreml"] = "CoreMLExecutionProvider" in ort.get_available_providers()
        except Exception:  # pragma: no cover
            pass
        return info

    def model_present(self, model: str) -> bool:
        return (self.models_dir / model).exists()

    # -- separación -----------------------------------------------------------------
    def separate(
        self,
        req: SeparationRequest,
        on_progress: ProgressFn | None = None,
        on_log: LogFn | None = None,
        cancel: threading.Event | None = None,
    ) -> SeparationResult:
        with self._lock:
            mode_key = req.mode
            while True:
                try:
                    return self._separate(req, mode_key, on_progress, on_log, cancel)
                except ModelUnavailable as exc:
                    fallback = MODES[mode_key].fallback
                    if not fallback:
                        raise RuntimeError(str(exc)) from exc
                    if on_log:
                        on_log(f"⚠️ {exc}. Usando alternativa: {MODES[fallback].name}")
                    mode_key = fallback

    def _separate(self, req, mode_key, on_progress, on_log, cancel) -> SeparationResult:
        global _progress_cb
        t0 = time.time()
        say = on_log or (lambda m: log.info(m))
        mode, steps, outputs = plan_for(mode_key, req.drumsep, req.stems)
        progress = Progress(total_steps=len(steps))
        warnings: list[str] = []

        def emit():
            if on_progress:
                on_progress(progress)

        def check_cancel():
            if cancel is not None and cancel.is_set():
                raise JobCancelled()

        config.ensure_dirs()
        song = safe_name(req.input_path.stem)
        workdir = config.WORK_DIR / f"{song}-{int(t0 * 1000)}"
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            say(f"Preparando «{req.input_path.name}» · modo {mode.name}")
            if req.stems:
                say("Extraer: " + ", ".join(STEM_LABELS[k] for k in outputs)
                    + f" · {len(steps)} paso(s) necesario(s)")
            mix = workdir / "mix.wav"
            duration = decode_to_wav(req.input_path, mix)
            say(f"Duración: {int(duration // 60)}:{int(duration % 60):02d}")
            stems: dict[str, Path] = {"mix": mix}
            emit()

            for i, step in enumerate(steps):
                check_cancel()
                progress.step, progress.step_fraction, progress.step_label = i, 0.0, step.label
                emit()
                say(f"[{i + 1}/{len(steps)}] {step.label}")
                stems.update(self._run_step(step, stems, workdir / f"step{i + 1}", progress, emit, say, cancel,
                                            req.quality))

            # Stems derivados (p. ej. instrumental = suma de no-vocales)
            for key, parts in mode.derived.items():
                available = [stems[p] for p in parts if p in stems]
                if available:
                    stems[key] = mix_files(available, workdir / f"{key}.wav")

            check_cancel()
            progress.step, progress.step_fraction, progress.step_label = len(steps), 0.0, "Exportando"
            emit()

            out_folder = Path(req.output_dir).expanduser() / safe_name(f"{song} [{mode.name}]")
            out_folder.mkdir(parents=True, exist_ok=True)
            final: dict[str, Path] = {}
            ordered = sorted(outputs, key=STEM_ORDER.index)
            for key in ordered:
                if key not in stems:
                    warnings.append(f"El modelo no generó el stem «{STEM_LABELS[key]}».")
                    continue
                dst = out_folder / f"{song} - {STEM_LABELS[key]}.{req.output_format}"
                final[key] = export(stems[key], dst, req.output_format, req.mp3_bitrate)

            elapsed = time.time() - t0
            (out_folder / "stemforge.json").write_text(json.dumps({
                "source": str(req.input_path), "mode": mode.key, "mode_name": mode.name,
                "models": [s.model for s in steps], "drumsep": req.drumsep,
                "selected": "all" if not req.stems else list(outputs),
                "format": req.output_format, "quality": req.quality, "seconds": round(elapsed, 1),
                "stems": {k: p.name for k, p in final.items()},
            }, indent=2, ensure_ascii=False))
            progress.step_fraction = 1.0
            emit()
            say(f"✅ Listo en {elapsed:.0f} s → {out_folder}")
            return SeparationResult(out_folder, final, mode.key, elapsed, warnings)
        finally:
            _progress_cb = None
            if not req.keep_workdir:
                shutil.rmtree(workdir, ignore_errors=True)
            _free_memory()

    def _run_step(self, step: Step, stems, step_dir: Path, progress: Progress, emit, say, cancel,
                  quality: str = "balanced") -> dict[str, Path]:
        global _progress_cb
        from audio_separator.separator import Separator

        source = stems.get(step.source)
        if source is None:
            raise RuntimeError(f"El paso «{step.label}» necesita el stem «{step.source}», que no existe.")
        step_dir.mkdir(parents=True, exist_ok=True)

        if not self.model_present(step.model):
            say(f"Descargando modelo {step.model} (solo la primera vez)…")
            progress.downloading = True

        last_emit = [0.0]

        def on_tqdm(fraction: float, unit: str):
            if cancel is not None and cancel.is_set():
                raise JobCancelled()
            is_download = unit.lower().endswith("b")  # B, iB, KiB...
            progress.downloading = is_download
            if not is_download:
                progress.step_fraction = max(progress.step_fraction, fraction)
            now = time.monotonic()
            if now - last_emit[0] > 0.25:
                last_emit[0] = now
                emit()

        with _progress_lock:
            _progress_cb = on_tqdm
        try:
            separator = Separator(
                log_level=logging.WARNING,
                model_file_dir=str(self.models_dir),
                output_dir=str(step_dir),
                output_format="WAV",
                normalization_threshold=0.98,
                sample_rate=SAMPLE_RATE,
                use_soundfile=True,
                **quality_params(quality),
            )
            try:
                separator.load_model(model_filename=step.model)
            except JobCancelled:
                raise
            except Exception as exc:  # descarga o carga fallida
                raise ModelUnavailable(f"No se pudo cargar el modelo {step.model}: {exc}") from exc
            progress.downloading = False
            outputs = separator.separate(str(source))
        finally:
            _progress_cb = None
            progress.downloading = False

        produced: dict[str, Path] = {}
        pending_sum: dict[str, list[Path]] = {}
        for out in outputs:
            path = Path(out)
            if not path.is_absolute():
                path = step_dir / path
            raw = stem_from_filename(path)
            if raw is None:
                say(f"  (ignorado: {path.name})")
                continue
            target = step.mapping.get(raw, None) if step.mapping else raw
            if target is None:
                continue
            pending_sum.setdefault(target, []).append(path)

        for key, paths in pending_sum.items():
            produced[key] = paths[0] if len(paths) == 1 else mix_files(paths, step_dir / f"{key}_sum.wav")

        del separator
        _free_memory()
        progress.step_fraction = 1.0
        return produced


def quality_params(quality: str) -> dict:
    """Parámetros de inferencia según la calidad elegida."""
    high = quality == "max"
    return {
        "mdxc_params": {"segment_size": 256, "override_model_segment_size": False, "batch_size": None,
                        "overlap": None if high else 2, "pitch_shift": 0},
        "demucs_params": {"segment_size": "Default", "shifts": 2 if high else 1, "overlap": 0.25,
                          "segments_enabled": True},
    }


def _free_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # pragma: no cover
        pass
