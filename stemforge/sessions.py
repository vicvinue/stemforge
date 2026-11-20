"""Sesiones del mezclador: las pistas de un trabajo recién terminado o de una carpeta ya extraída.

Una carpeta se abre con TODAS sus pistas de audio (sin subcarpetas). Si trae `stemforge.json`
(lo escribe cada separación) se usa para reconocer cada pista y su tempo; si no, se deduce del
nombre de archivo («Canción - Voz.wav») y el tempo se calcula al abrirla.

Con el tempo conocido, si la carpeta no tiene metrónomo se crea («Canción - Metrónomo.wav»).
Una versión transpuesta se guarda en una subcarpeta («Tono +2 semitonos») con su propio
stemforge.json, así que también se puede abrir después.

Solo hay un mezclador: al abrir una sesión nueva se descartan las anteriores y su caché de audio
transpuesto.
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import analysis, config
from .analysis import METRONOME_KEY, METRONOME_LABEL
from .presets import DRUMSEP_OUTPUTS, MIX_KEY, STEM_LABELS, STEM_ORDER, _fold, resolve_stem

MAX_TRACKS = 24
META_FILE = "stemforge.json"
# Formatos que el WebView decodifica directamente (los demás se convierten a WAV al servirlos)
BROWSER_FORMATS = {".wav", ".flac", ".mp3", ".m4a", ".aac"}
# Preferencia cuando la misma pista está en varios formatos (p. ej. «Voz.wav» y «Voz.mp3»)
FORMAT_RANK = {".wav": 0, ".flac": 1, ".aiff": 2, ".aif": 2, ".m4a": 3, ".mp3": 4, ".ogg": 5, ".opus": 5}
# Pistas sin tono definido: no se transponen (se ahorran artefactos)
UNPITCHED = {"drums", *DRUMSEP_OUTPUTS, METRONOME_KEY}
PITCH_DIR = config.WORK_DIR / "pitch"


@dataclass
class Track:
    key: str
    label: str
    path: Path

    @property
    def base(self) -> str:
        return self.key if self.key.startswith("x-") else self.key.split("-")[0]   # «drums-2» -> drums

    @property
    def pitched(self) -> bool:
        return self.base not in UNPITCHED

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
    fmt: str = "wav"                         # formato de las pistas (para el metrónomo)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _file_locks: dict = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "folder": str(self.folder), "source": self.source,
                "tracks": [t.to_dict() for t in self.tracks], "bpm": self.bpm,
                "tempo_state": self.tempo_state, "skipped": self.skipped}

    def tempo(self) -> dict:
        metro = self.track(METRONOME_KEY)
        return {"bpm": self.bpm, "state": self.tempo_state, "metronome": metro.to_dict() if metro else None}

    def track(self, key: str) -> Track | None:
        return next((t for t in self.tracks if t.key == key), None)

    def song_name(self) -> str:
        for t in self.tracks:
            if " - " in t.path.stem:
                return t.path.stem.rsplit(" - ", 1)[0]
        return self.title

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
        with self._lock:
            lock = self._file_locks.setdefault(dst, threading.Lock())
        with lock:                           # dos pedidos iguales a la vez: se procesa una sola vez
            if not dst.is_file():
                analysis.render(track.path, dst, semitones)
        return dst

    # -- tempo y metrónomo ----------------------------------------------------------------
    def tempo_sources(self) -> list[Path]:
        """Las pistas que suenan por defecto en el mezclador (sin duplicar sonido ni el metrónomo)."""
        bases = {t.base for t in self.tracks}
        skip = {MIX_KEY, METRONOME_KEY}
        if bases & {"drums", "bass", "guitar", "piano", "other", *DRUMSEP_OUTPUTS}:
            skip.add("instrumental")
        if "drums" in bases:
            skip.update(DRUMSEP_OUTPUTS)
        chosen = [t.path for t in self.tracks if t.base not in skip]
        return chosen or [t.path for t in self.tracks if t.base != METRONOME_KEY]

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
        self.bpm, self.beats = result["bpm"], result["beats"]
        _update_meta(self.folder, {"bpm": result["bpm"], "beats": result["beats"]})
        self.ensure_metronome()
        self.tempo_state = "done"

    def duration(self) -> float:
        import soundfile as sf

        best = 0.0
        for t in self.tracks:
            if t.base == METRONOME_KEY:
                continue
            try:
                info = sf.info(str(t.path))
                best = max(best, info.frames / info.samplerate)
            except Exception:  # formato que libsndfile no lee: se usa lo que haya
                continue
        return best or ((self.beats[-1] + 2.0) if self.beats else 0.0)

    def ensure_metronome(self) -> Track | None:
        """Crea «Canción - Metrónomo.<formato>» en la carpeta si hay pulsos y aún no existe.

        Si la carpeta no admite escritura, el metrónomo queda en la caché (se oye igual, pero no se guarda).
        """
        existing = self.track(METRONOME_KEY)
        if existing or not self.beats:
            return existing
        fmt = self.fmt if self.fmt in config.OUTPUT_FORMATS else "wav"
        dst = self.folder / f"{self.song_name()} - {METRONOME_LABEL}.{fmt}"
        try:
            path = analysis.write_metronome(self.beats, self.duration(), dst, fmt)
            _update_meta(self.folder, {"stems": {METRONOME_KEY: path.name}}, merge_key="stems")
        except Exception:  # noqa: BLE001 — carpeta de solo lectura, disco lleno…
            try:
                path = analysis.write_metronome(self.beats, self.duration(),
                                                PITCH_DIR / self.id / f"{METRONOME_LABEL}.wav", "wav")
            except Exception:  # noqa: BLE001
                return None
        track = Track(METRONOME_KEY, METRONOME_LABEL, path)
        self.tracks.append(track)
        return track

    # -- guardar una versión transpuesta ----------------------------------------------------
    def export_transposed(self, semitones: int, mp3_bitrate: str = "320k") -> dict:
        """Guarda todas las pistas transpuestas en una subcarpeta «Tono ±N semitonos».

        La batería y el metrónomo se copian tal cual. Cada pista conserva su formato (WAV, FLAC o
        MP3; otros formatos pasan a WAV). La subcarpeta lleva su stemforge.json (con el tempo).
        """
        if semitones == 0 or not -analysis.MAX_SEMITONES <= semitones <= analysis.MAX_SEMITONES:
            raise ValueError(f"Elige un tono entre -{analysis.MAX_SEMITONES} y +{analysis.MAX_SEMITONES}")
        tag = f"{semitones:+d}"
        name = f"Tono {tag} semitono{'s' if abs(semitones) > 1 else ''}"
        target = self.folder / name
        n = 2
        while target.exists():
            target = self.folder / f"{name} ({n})"
            n += 1
        target.mkdir(parents=True)
        song = self.song_name()

        def one(track: Track) -> tuple[str, Path]:
            ext = track.path.suffix.lower()
            fmt = ext[1:] if ext[1:] in config.OUTPUT_FORMATS else "wav"
            if track.pitched:
                dst = target / f"{song} - {track.label} ({tag}).{fmt}"
                src = self.audio_file(track.key, semitones)        # WAV 24 bits transpuesto (en caché)
                if fmt == "wav":
                    shutil.copyfile(src, dst)
                else:
                    from .engine import export

                    export(src, dst, fmt, mp3_bitrate)
            else:
                dst = target / f"{song} - {track.label}{ext}"
                shutil.copyfile(track.path, dst)
            return track.key, dst

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                done = list(pool.map(one, self.tracks))
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        meta = _read_meta(self.folder)
        meta.update({"stems": {k: p.name for k, p in done}, "bpm": self.bpm, "beats": self.beats,
                     "transpose": semitones, "transposed_from": str(self.folder)})
        meta.pop("selection_mix", None)
        (target / META_FILE).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"folder": str(target), "name": target.name, "files": [p.name for _, p in done]}


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
    session = Session(_new_id(), Path(job.filename).stem, folder, tracks, "job", bpm=job.bpm,
                      beats=list(job.beats), fmt=job.request.output_format)
    if job.bpm is None and not job.beats:
        session.tempo_state = "pending"
    else:
        session.ensure_metronome()
    return session


def session_from_folder(folder: Path) -> Session:
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError(f"No existe la carpeta {folder}")
    meta = _read_meta(folder)
    known = {name: key for key, name in (meta.get("stems") or {}).items() if isinstance(name, str)}
    files = sorted((p for p in folder.iterdir()
                    if p.is_file() and not p.name.startswith(".") and ".part." not in p.name
                    and p.suffix.lower() in config.AUDIO_EXTENSIONS),
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

    fmt = meta.get("format") if meta.get("format") in config.OUTPUT_FORMATS else _majority_format(tracks)
    session = Session(_new_id(), folder.name, folder, tracks, "folder", skipped=skipped, fmt=fmt)
    if "bpm" in meta:                            # ya analizada (bpm None = sin pulso claro)
        session.bpm, session.beats = meta.get("bpm"), list(meta.get("beats") or [])
        session.ensure_metronome()
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
        elif _fold(tail) in ("metronomo", "metronome", "click"):
            key = METRONOME_KEY
        else:
            guess = resolve_stem(tail)
            key = guess if guess in STEM_LABELS else None
    if key == MIX_KEY:
        return MIX_KEY, tail
    if key == METRONOME_KEY:
        return METRONOME_KEY, METRONOME_LABEL
    if key in STEM_LABELS:
        return key, STEM_LABELS[key]
    return "x-" + _slug(tail.lower()), tail


def _order(key: str) -> int:
    base = key.split("-")[0] if not key.startswith("x-") else key
    if base in STEM_ORDER:
        return STEM_ORDER.index(base)
    if base == METRONOME_KEY:
        return len(STEM_ORDER) + 2
    return len(STEM_ORDER) + (1 if base == MIX_KEY else 0)


def _better(new: Path, old: Path, known: dict[str, str]) -> bool:
    if (new.name in known) != (old.name in known):
        return new.name in known
    return FORMAT_RANK.get(new.suffix.lower(), 9) < FORMAT_RANK.get(old.suffix.lower(), 9)


def _majority_format(tracks: list[Track]) -> str:
    exts = [t.path.suffix.lower()[1:] for t in tracks if t.path.suffix.lower()[1:] in config.OUTPUT_FORMATS]
    return max(set(exts), key=exts.count) if exts else "wav"


def _read_meta(folder: Path) -> dict:
    try:
        data = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_meta(folder: Path, values: dict, merge_key: str | None = None) -> None:
    """Agrega datos al stemforge.json de la carpeta (solo si ya existe: no se crean archivos ajenos)."""
    meta_path = folder / META_FILE
    if not meta_path.is_file():
        return
    meta = _read_meta(folder)
    if not meta:
        return
    for k, v in values.items():
        if k == merge_key and isinstance(meta.get(k), dict):
            meta[k].update(v)
        else:
            meta[k] = v
    try:
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(meta_path)
    except OSError:
        pass
