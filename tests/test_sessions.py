"""Mezclador: abrir carpetas con pistas, tempo (BPM) y transposición."""
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge import analysis, sessions

SR = 44100


def _clicks(path: Path, bpm: float, secs: float = 20.0, freq: float = 440.0, start: float = 0.5) -> list[float]:
    """Pista de clics a `bpm` (cada clic es un tono corto de `freq` Hz). Devuelve los tiempos."""
    y = np.zeros(int(SR * secs), dtype=np.float32)
    n = int(0.03 * SR)
    env = np.sin(2 * np.pi * freq * np.arange(n) / SR) * np.exp(-np.arange(n) / SR / 0.008)
    times = list(np.arange(start, secs - 0.5, 60.0 / bpm))
    for t in times:
        i = int(t * SR)
        y[i:i + n] += env.astype(np.float32)
    sf.write(str(path), np.stack([y, y], 1), SR, subtype="FLOAT")
    return times


def _onsets(y: np.ndarray, times: list[float]) -> np.ndarray:
    env, out = np.abs(y), []
    for t in times:
        a = int((t - 0.1) * SR)
        seg = env[a:a + int(0.2 * SR)]
        out.append((a + np.argmax(seg > 0.3 * seg.max())) / SR)
    return np.array(out)


def _touch_audio(path: Path, secs: float = 1.0) -> Path:
    sf.write(str(path), np.zeros((int(SR * secs), 2), dtype=np.float32), SR)
    return path


# ------------------------------------------------------------------------- carpetas
@pytest.mark.parametrize("name,key,label", [
    ("Canción - Voz.wav", "vocals", "Voz"),
    ("Canción - Batería.flac", "drums", "Batería"),
    ("Canción - Hi-Hat.wav", "hihat", "Hi-Hat"),
    ("Canción - Mezcla (Voz + Bajo).mp3", "mezcla", "Mezcla (Voz + Bajo)"),
    ("guitar.wav", "guitar", "Guitarra"),
    ("01 Coros extra.wav", "x-01_coros_extra", "01 Coros extra"),
    ("Canción - Metrónomo.flac", "metronome", "Metrónomo"),
])
def test_identify(name, key, label):
    assert sessions.identify(Path(name)) == (key, label)


def test_folder_with_metadata_dedupes_formats_and_keeps_extra_tracks(tmp_path):
    for name in ("S - Voz.wav", "S - Voz.mp3", "S - Batería.wav", "S - Bajo.wav", "S - Instrumental.wav",
                 "S - Mezcla (Voz + Batería).mp3", "Coros.wav"):
        _touch_audio(tmp_path / name)
    (tmp_path / "notas.txt").write_text("no es audio")
    (tmp_path / ".oculto.wav").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    _touch_audio(tmp_path / "sub" / "S - Otros.wav")                  # sin subcarpetas
    (tmp_path / "stemforge.json").write_text(json.dumps({
        "stems": {"vocals": "S - Voz.wav", "drums": "S - Batería.wav"}, "bpm": 120.0, "beats": [0.5, 1.0]}))

    s = sessions.session_from_folder(tmp_path)
    by_key = {t.key: t for t in s.tracks}
    # Con el tempo conocido se crea el metrónomo en la carpeta (formato del json; aquí no hay: WAV)
    assert [t.key for t in s.tracks] == ["vocals", "instrumental", "drums", "bass", "x-coros", "mezcla", "metronome"]
    assert (tmp_path / "S - Metrónomo.wav").is_file() and not by_key["metronome"].pitched
    assert json.loads((tmp_path / "stemforge.json").read_text())["stems"]["metronome"] == "S - Metrónomo.wav"
    assert by_key["vocals"].path.name == "S - Voz.wav"               # el del json, no el MP3
    assert by_key["mezcla"].label == "Mezcla (Voz + Batería)"
    assert not by_key["drums"].pitched and by_key["vocals"].pitched
    assert s.bpm == 120.0 and s.beats == [0.5, 1.0] and s.tempo_state == "done"
    # El tempo se calcula con lo que suena por defecto: sin instrumental ni mezcla (duplicarían)
    assert {p.name for p in s.tempo_sources()} == {"S - Voz.wav", "S - Batería.wav", "S - Bajo.wav", "Coros.wav"}


def test_folder_without_metadata_needs_tempo(tmp_path):
    _touch_audio(tmp_path / "a - Voz.wav")
    s = sessions.session_from_folder(tmp_path)
    assert s.tempo_state == "pending" and s.bpm is None


def test_folder_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        sessions.session_from_folder(tmp_path / "no-existe")
    (tmp_path / "x.txt").write_text("hola")
    with pytest.raises(ValueError):
        sessions.session_from_folder(tmp_path)


def test_folder_track_limit(tmp_path):
    for i in range(sessions.MAX_TRACKS + 3):
        _touch_audio(tmp_path / f"pista {i:02d}.wav", secs=0.1)
    s = sessions.session_from_folder(tmp_path)
    assert len(s.tracks) == sessions.MAX_TRACKS and len(s.skipped) == 3


def test_store_keeps_one_session_and_tempo_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "PITCH_DIR", tmp_path / "pitch")
    folder = tmp_path / "song"
    folder.mkdir()
    _clicks(folder / "S - Batería.wav", 100, secs=12)
    (folder / "stemforge.json").write_text(json.dumps({"stems": {"drums": "S - Batería.wav"}}))
    store = sessions.SessionStore()
    first = store.add(sessions.session_from_folder(folder))
    first._analyze()                                                 # lo mismo que hace el hilo
    assert abs(first.bpm - 100) < 1.5 and first.tempo_state == "done"
    meta = json.loads((folder / "stemforge.json").read_text())
    assert meta["bpm"] == first.bpm and meta["beats"]
    assert meta["stems"] == {"drums": "S - Batería.wav", "metronome": "S - Metrónomo.wav"}   # se conserva lo demás
    assert first.tempo()["metronome"]["key"] == "metronome"
    # El metrónomo marca los pulsos detectados, del largo de la canción
    m, sr = sf.read(str(folder / "S - Metrónomo.wav"), dtype="float32")
    assert abs(len(m) - 12 * SR) < SR * 0.01
    hits = np.flatnonzero(np.abs(m if m.ndim == 1 else m[:, 0]) > 0.2)
    starts = hits[np.insert(np.diff(hits) > SR * 0.1, 0, True)] / SR
    assert len(starts) == len(first.beats) and np.allclose(starts, first.beats, atol=0.01)
    second = store.add(sessions.session_from_folder(folder))
    assert store.get(first.id) is None and store.get(second.id) is second
    assert second.tempo_state == "done" and second.bpm == first.bpm      # ya no se recalcula
    assert [t.key for t in second.tracks] == ["drums", "metronome"]      # ni se duplica el metrónomo
    assert second.tempo_sources() == [folder / "S - Batería.wav"]        # el metrónomo no cuenta


# ---------------------------------------------------------------------------- tempo
@pytest.mark.parametrize("bpm", [87.0, 110.0, 128.0])
def test_estimate_tempo(tmp_path, bpm):
    _clicks(tmp_path / "c.wav", bpm, secs=25)
    res = analysis.analyze_tempo([tmp_path / "c.wav"])
    assert abs(res["bpm"] - bpm) < 1.0
    assert len(res["beats"]) > 20


def test_estimate_tempo_silence():
    assert analysis.estimate_tempo(np.zeros(analysis.ANALYSIS_SR * 10, dtype=np.float32)) == {"bpm": None, "beats": []}


# ---------------------------------------------------------------------- transposición
def test_pitch_filter_limits():
    assert analysis.pitch_filter(0, SR) == f"aresample={SR}"
    with pytest.raises(ValueError):
        analysis.pitch_filter(6, SR)
    with pytest.raises(ValueError):
        analysis.pitch_filter(-6, SR)


@pytest.mark.parametrize("semitones", [-5, -2, 3, 5])
def test_pitch_shift_keeps_tempo_and_sync(tmp_path, semitones):
    times = _clicks(tmp_path / "c.wav", 120, secs=10)
    out = analysis.render(tmp_path / "c.wav", tmp_path / "o.wav", semitones)
    y, sr = sf.read(str(out), dtype="float32")
    assert sr == SR
    assert abs(len(y) - SR * 10) < SR * 0.06                          # misma duración
    drift = (_onsets(y[:, 0], times) - np.array(times)) * 1000
    assert abs(drift.mean()) < 8 and np.abs(drift).max() < 20         # sigue en sincronía (ms)
    # Tono: el pico del espectro de un clic se mueve `semitones`
    i = int(times[3] * SR)
    spec = np.abs(np.fft.rfft(y[i:i + 1024, 0] * np.hanning(1024), 1 << 15))
    f = np.argmax(spec) * SR / (1 << 15)
    assert abs(12 * np.log2(f / 440.0) - semitones) < 0.35


def test_session_audio_file_cache_and_unpitched(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "PITCH_DIR", tmp_path / "pitch")
    _clicks(tmp_path / "S - Voz.wav", 120, secs=4)
    _clicks(tmp_path / "S - Batería.wav", 120, secs=4)
    s = sessions.session_from_folder(tmp_path)
    assert s.audio_file("vocals", 0) == tmp_path / "S - Voz.wav"      # original, sin convertir
    shifted = s.audio_file("vocals", 2)
    assert shifted.parent == tmp_path / "pitch" / s.id and shifted.is_file()
    mtime = shifted.stat().st_mtime_ns
    assert s.audio_file("vocals", 2).stat().st_mtime_ns == mtime     # en caché
    assert s.audio_file("drums", 4) == tmp_path / "S - Batería.wav"   # la batería no se transpone
    with pytest.raises(FileNotFoundError):
        s.audio_file("nope", 0)


def test_metronome_falls_back_to_cache_when_folder_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "PITCH_DIR", tmp_path / "pitch")
    folder = tmp_path / "song"
    folder.mkdir()
    _touch_audio(folder / "S - Voz.wav", secs=3)
    s = sessions.Session("abc", "S", folder, [sessions.Track("vocals", "Voz", folder / "S - Voz.wav")], "folder",
                         bpm=120.0, beats=[0.5, 1.0, 1.5])
    real = analysis.write_metronome

    def fail_in_folder(beats, duration, dst, *a, **kw):
        if dst.parent == folder:
            raise PermissionError("solo lectura")
        return real(beats, duration, dst, *a, **kw)

    monkeypatch.setattr(analysis, "write_metronome", fail_in_folder)
    track = s.ensure_metronome()
    assert track.path.parent == tmp_path / "pitch" / "abc" and track.path.is_file()
    assert not list(folder.glob("*Metr*"))


def test_export_transposed(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "PITCH_DIR", tmp_path / "pitch")
    folder = tmp_path / "song"
    folder.mkdir()
    _clicks(folder / "S - Voz.wav", 120, secs=4)
    _clicks(folder / "S - Batería.wav", 120, secs=4)
    import subprocess
    from stemforge.engine import ffmpeg_bin
    subprocess.run([ffmpeg_bin(), "-loglevel", "error", "-y", "-i", str(folder / "S - Voz.wav"),
                    str(folder / "S - Bajo.mp3")], check=True)
    (folder / "stemforge.json").write_text(json.dumps({"stems": {"vocals": "S - Voz.wav"}, "format": "wav",
                                                       "bpm": 120.0, "beats": [0.5, 1.0, 1.5, 2.0]}))
    s = sessions.session_from_folder(folder)
    with pytest.raises(ValueError):
        s.export_transposed(0)
    res = s.export_transposed(2)
    out = Path(res["folder"])
    assert out == folder / "Tono +2 semitonos" and res["name"] == "Tono +2 semitonos"
    assert sorted(p.name for p in out.iterdir()) == sorted([
        "S - Voz (+2).wav", "S - Bajo (+2).mp3",           # con tono: transpuestas, mismo formato
        "S - Batería.wav", "S - Metrónomo.wav",             # sin tono: copias exactas
        "stemforge.json"])
    assert (out / "S - Batería.wav").read_bytes() == (folder / "S - Batería.wav").read_bytes()
    assert sf.info(str(out / "S - Voz (+2).wav")).subtype == "PCM_24"
    meta = json.loads((out / "stemforge.json").read_text())
    assert meta["transpose"] == 2 and meta["bpm"] == 120.0 and meta["stems"]["vocals"] == "S - Voz (+2).wav"
    # La versión guardada se abre como cualquier carpeta, con sus pistas reconocidas
    again = sessions.session_from_folder(out)
    assert {t.key for t in again.tracks} == {"vocals", "bass", "drums", "metronome"} and again.bpm == 120.0
    # Guardar otra vez el mismo tono no pisa la anterior
    assert s.export_transposed(2)["name"] == "Tono +2 semitonos (2)"
    assert s.export_transposed(-1)["name"] == "Tono -1 semitono"
