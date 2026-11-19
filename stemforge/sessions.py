"""Sesiones del mezclador: las pistas de un trabajo recién terminado o de una carpeta ya extraída.

Una carpeta se abre con TODAS sus pistas de audio (sin subcarpetas). Si trae `stemforge.json`
(lo escribe cada separación) se usa para reconocer cada pista y su tempo; si no, se deduce del
nombre de archivo («Canción - Voz.wav») y el tempo se calcula al abrirla.

Solo hay un mezclador: al abrir una sesión nueva se descartan las anteriores y su caché de audio
transpuesto.
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis, config
from .presets import DRUMSEP_OUTPUTS, MIX_KEY, STEM_LABELS, STEM_ORDER, resolve_stem

MAX_TRACKS = 24
META_FILE = "stemforge.json"
# Formatos que el WebView decodifica directamente (los demás se convierten a WAV al servirlos)
BROWSER_FORMATS = {".wav", ".flac", ".mp3", ".m4a", ".aac"}
# Preferencia cuando la misma pista está en varios formatos (p. ej. «Voz.wav» y «Voz.mp3»)
FORMAT_RANK = {".wav": 0, ".flac": 1, ".aiff": 2, ".aif": 2, ".m4a": 3, ".mp3": 4, ".ogg": 5, ".opus": 5}
# Pistas sin tono definido: no se transponen (se ahorran artefactos)
UNPITCHED = {"drums", *DRUMSEP_OUTPUTS}
PITCH_DIR = config.WORK_DIR / "pitch"


@dataclass
class Track:
    key: str
    label: str
    path: Path

    @property
    def pitched(self) -> bool:
        base = self.key if self.key.startswith("x-") else self.key.split("-")[0]   # «drums-2» -> drums
        return base not in UNPITCHED

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "file": self.path.name, "pitched": self.pitched}


@dataclass
class Session:
    id: str
    title: str
    folder: Path
    tracks: list[Track]
    source: str                              # "job" | "folder"
    bpm: float | None = None
    beats: list[float] = field(default_factory=list)
    tempo_state: str = "done"                # pending | running | done | error
    skipped: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "folder": str(self.folder), "source": self.source,
                "tracks": [t.to_dict() for t in self.tracks], "bpm": self.bpm,
                "tempo_state": self.tempo_state, "skipped": self.skipped}

    def tempo(self) -> dict:
        return {"bpm": self.bpm, "beats": self.beats, "state": self.tempo_state}

    def track(self, key: str) -> Track | None:
        return next((t for t in self.tracks if t.key == key), None)

    # -- audio para el mezclador ------------------------------------------------------
    def audio_file(self, key: str, semitones: int = 0) -> Path:
        """Archivo listo para el WebView: el original, o una copia transpuesta / convertida (en caché)."""
        track = self.track(key)
        if track is None or not track.path.is_file():
            raise FileNotFoundError(key)
        if not track.pitched:
            semitones = 0
        if semitones == 0 and track.path.suffix.lower() in BROWSER_FORMATS:
            return track.path
        dst = PITCH_DIR / self.id / f"{_slug(key)}_{semitones:+d}.wav"
        with self._lock:                     # dos pedidos iguales a la vez: se procesa una sola vez
            if not dst.is_file():
                analysis.render(track.path, dst, semitones)
        return dst

    # -- tempo ---------------------------------------------------------------------------
    def tempo_sources(self) -> list[Path]:
        """Las pistas que suenan por defecto en el mezclador (sin duplicar sonido)."""
        keys = {t.key for t in self.tracks}
        skip = {MIX_KEY}
        if keys & {"drums", "bass", "guitar", "piano", "other", *DRUMSEP_OUTPUTS}:
            skip.add("instrumental")
        if "drums" in keys:
            skip.update(DRUMSEP_OUTPUTS)
        chosen = [t.path for t in self.tracks if t.key not in skip]
        return chosen or [t.path for t in self.tracks]

    def analyze_tempo_async(self) -> None:
        if self.tempo_state not in ("pending", "error"):
            return
        self.tempo_state = "running"
        threading.Thread(target=self._analyze, name="stemforge-tempo", daemon=True).start()

    def _analyze(self) -> None:
        try:
            result = analysis.analyze_tempo(self.tempo_sources())
        except Exception:  # noqa: BLE001 — el mezclador funciona igual sin tempo
            self.tempo_state = "error"
            return
        self.bpm, self.beats, self.tempo_state = result["bpm"], result["beats"], "done"
        _save_tempo(self.folder, result)


# ------------------------------------------------------------------------- registro
class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        shutil.rmtree(PITCH_DIR, ignore_errors=True)

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def add(self, session: Session) -> Session:
        """Registra la sesión y descarta las demás (un solo mezclador abierto)."""
        with self._lock:
            for old in self._sessions:
                shutil.rmtree(PITCH_DIR / old, ignore_errors=True)
            self._sessions = {session.id: session}
        if session.tempo_state == "pending":
            session.analyze_tempo_async()
        return session


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _slug(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:40]


def session_from_job(job) -> Session:
    tracks = [Track(s["key"], s["label"], Path(s["path"])) for s in job.stems if Path(s["path"]).is_file()]
    if not tracks:
        raise FileNotFoundError("Las pistas de este trabajo ya no están en la carpeta de salida")
    folder = Path(job.output_folder) if job.output_folder else tracks[0].path.parent
    session = Session(_new_id(), Path(job.filename).stem, folder, tracks, "job", bpm=job.bpm, beats=list(job.beats))
    if job.bpm is None and not job.beats:
        session.tempo_state = "pending"
    return session


def session_from_folder(folder: Path) -> Session:
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"No existe la carpeta {folder}")
    meta = _read_meta(folder)
    known = {name: key for key, name in (meta.get("stems") or {}).items() if isinstance(name, str)}
    files = sorted((p for p in folder.iterdir()
                    if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in config.AUDIO_EXTENSIONS),
                   key=lambda p: p.name.lower())
    if not files:
        raise ValueError("La carpeta no tiene archivos de audio")

    # Una pista por etiqueta: si está en varios formatos, la del json o la de mejor formato.
    by_label: dict[str, tuple[str, Path]] = {}
    for p in files:
        key, label = identify(p, known)
        current = by_label.get(label.lower())
        if current is None or _better(p, current[1], known):
            by_label[label.lower()] = (key, p)
    used: set[str] = set()
    tracks: list[Track] = []
    for key, p in by_label.values():
        _, label = identify(p, known)
        unique = key
        n = 2
        while unique in used:                    # dos archivos que se llaman igual (p. ej. «Voz 2»)
            unique, n = f"{key}-{n}", n + 1
        used.add(unique)
        tracks.append(Track(unique, label, p))
    tracks.sort(key=lambda t: (_order(t.key), t.label.lower()))
    skipped = [t.path.name for t in tracks[MAX_TRACKS:]]
    tracks = tracks[:MAX_TRACKS]

    session = Session(_new_id(), folder.name, folder, tracks, "folder", skipped=skipped)
    if "bpm" in meta:                            # ya analizada (bpm None = sin pulso claro)
        session.bpm, session.beats = meta.get("bpm"), list(meta.get("beats") or [])
    else:
        session.tempo_state = "pending"
    return session


def identify(path: Path, known: dict[str, str] | None = None) -> tuple[str, str]:
    """(clave, etiqueta) de una pista según stemforge.json o su nombre «Canción - Etiqueta.ext»."""
    tail = path.stem.rsplit(" - ", 1)[-1].strip() or path.stem
    key = (known or {}).get(path.name)
    if key is None:
        if tail.lower().startswith("mezcla"):
            key = MIX_KEY
        else:
            guess = resolve_stem(tail)
            key = guess if guess in STEM_LABELS else None
    if key == MIX_KEY:
        return MIX_KEY, tail
    if key in STEM_LABELS:
        return key, STEM_LABELS[key]
    return "x-" + _slug(tail.lower()), tail


def _order(key: str) -> int:
    base = key.split("-")[0] if not key.startswith("x-") else key
    if base in STEM_ORDER:
        return STEM_ORDER.index(base)
    return len(STEM_ORDER) + (1 if base == MIX_KEY else 0)


def _better(new: Path, old: Path, known: dict[str, str]) -> bool:
    if (new.name in known) != (old.name in known):
        return new.name in known
    return FORMAT_RANK.get(new.suffix.lower(), 9) < FORMAT_RANK.get(old.suffix.lower(), 9)


def _read_meta(folder: Path) -> dict:
    try:
        data = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_tempo(folder: Path, tempo: dict) -> None:
    """Guarda el tempo calculado en el stemforge.json de la carpeta (si lo tiene) para la próxima vez."""
    meta_path = folder / META_FILE
    if not meta_path.is_file():
        return
    meta = _read_meta(folder)
    if not meta:
        return
    meta["bpm"], meta["beats"] = tempo["bpm"], tempo["beats"]
    try:
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(meta_path)
    except OSError:
        pass
