"""Análisis y procesado de audio para el mezclador: tempo (BPM + pulsos) y transposición.

- Tempo: librosa (ya viene con audio-separator: no es una dependencia nueva). Los pulsos que
  detecta sirven para el metrónomo del mezclador, que así sigue las variaciones de tempo.
- Transposición: ffmpeg (asetrate + atempo) cambia el tono sin cambiar la duración.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

ANALYSIS_SR = 22050
HOP = 256                  # resolución fina: con 512 el tempo se cuantiza demasiado
MAX_SEMITONES = 5
# atempo adelanta la señal unos 20 ms (y algo más cuanto más se sube el tono): se compensa
# para que una pista transpuesta siga en sincronía con las que no se transponen (batería).
_LATENCY_MS = 21.2
_LATENCY_MS_PER_SEMITONE = 1.15


def load_mono(paths: list[Path], sr: int = ANALYSIS_SR) -> np.ndarray:
    """Suma varias pistas (alineadas al inicio) en mono a `sr` Hz."""
    import librosa

    total: np.ndarray | None = None
    for p in paths:
        y, _ = librosa.load(str(p), sr=sr, mono=True)
        if total is None:
            total = y.astype(np.float32)
        else:
            if len(y) > len(total):
                total, y = y.astype(np.float32), total
            total[: len(y)] += y
    if total is None:
        raise ValueError("No hay audio para analizar")
    return total


def estimate_tempo(y: np.ndarray, sr: int = ANALYSIS_SR) -> dict:
    """Devuelve {"bpm": float, "beats": [segundos]} o {"bpm": None, "beats": []} si no hay pulso."""
    import librosa

    if y.size < sr * 3 or not np.any(np.abs(y) > 1e-4):
        return {"bpm": None, "beats": []}
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, units="time")
    beats = np.asarray(beats, dtype=float)
    first = float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 0.0
    if len(beats) < 8:
        return {"bpm": round(first, 2) if first > 0 else None, "beats": [round(b, 3) for b in beats]}
    # El tempo de librosa sale de una rejilla gruesa: se afina con los pulsos.
    # Regresión (periodo medio) si es coherente con la mediana; si no (pulsos perdidos), la mediana.
    median = 60.0 / float(np.median(np.diff(beats)))
    slope = float(np.polyfit(np.arange(len(beats)), beats, 1)[0])
    reg = 60.0 / slope if slope > 0 else median
    bpm = reg if abs(reg - median) / median < 0.04 else median
    return {"bpm": round(bpm, 2), "beats": [round(float(b), 3) for b in beats]}


def analyze_tempo(paths: list[Path]) -> dict:
    return estimate_tempo(load_mono(paths))


def pitch_ratio(semitones: int) -> float:
    return 2.0 ** (semitones / 12.0)


def pitch_filter(semitones: int, sample_rate: int) -> str:
    """Filtro de ffmpeg que transpone `semitones` sin cambiar el tempo."""
    if not -MAX_SEMITONES <= semitones <= MAX_SEMITONES:
        raise ValueError(f"La transposición va de -{MAX_SEMITONES} a +{MAX_SEMITONES} semitonos")
    if semitones == 0:
        return f"aresample={sample_rate}"
    r = pitch_ratio(semitones)
    delay = _LATENCY_MS + _LATENCY_MS_PER_SEMITONE * semitones
    return (f"asetrate={sample_rate * r:.4f},aresample={sample_rate},atempo={1 / r:.6f},"
            f"adelay={delay:.1f}ms:all=1")


def render(src: Path, dst: Path, semitones: int = 0) -> Path:
    """Escribe `dst` (WAV 24 bits) transpuesto `semitones`. Con 0 solo convierte a WAV."""
    import soundfile as sf

    from .engine import ffmpeg_bin

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        sr = int(sf.info(str(src)).samplerate)
    except Exception:  # formato que libsndfile no lee (m4a, opus…): primero a WAV, luego se transpone
        if semitones == 0:
            sr = 44100
        else:
            plain = dst.with_name(dst.stem + ".src.wav")
            try:
                return render(render(src, plain, 0), dst, semitones)
            finally:
                plain.unlink(missing_ok=True)
    tmp = dst.with_name(dst.stem + ".part.wav")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vn",
           "-af", pitch_filter(semitones, sr), "-ar", str(sr), "-c:a", "pcm_s24le", str(tmp)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg falló: {proc.stderr.strip()[-400:]}")
    tmp.replace(dst)
    return dst
