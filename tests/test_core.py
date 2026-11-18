"""Tests rápidos (sin modelos): presets, nombres de stems, mezcla y exportación."""
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from stemforge import engine, presets


def test_every_mode_outputs_have_labels_and_sources():
    for mode in presets.MODES.values():
        produced = {"mix"}
        for step in mode.steps:
            assert step.source in produced, f"{mode.key}: paso usa {step.source} antes de existir"
            produced |= step.targets
        produced |= set(mode.derived)
        for out in mode.outputs:
            assert out in presets.STEM_LABELS
            assert out in produced, f"{mode.key}: nadie produce {out}"


def test_steps_are_well_formed():
    for mode in presets.MODES.values():
        for step in mode.steps:
            assert step.uses and step.combine in ("fallback", "ensemble")
            for use in step.uses:
                assert use.weight > 0 and use.mapping


def test_build_plan_drumsep_only_when_drums():
    _, steps, outputs = presets.build_plan("stems4", drumsep=True)
    assert steps[-1].models == [presets.DRUMSEP] and "kick" in outputs
    _, steps, outputs = presets.build_plan("instrumental", drumsep=True)
    assert all(presets.DRUMSEP not in s.models for s in steps) and "kick" not in outputs
    with pytest.raises(ValueError):
        presets.build_plan("nope")


@pytest.mark.parametrize("name,expected", [
    ("mix_(Vocals)_model_bs_roformer_ep_317_sdr_12.9755", "vocals"),
    ("mix_(Instrumental)_model_bs_roformer_(Drums)_htdemucs_ft", "drums"),  # cadena: vale el último
    ("drums_(hh)_MDX23C-DrumSep", "hihat"),
    ("song_(No Vocals)_x", "instrumental"),
    ("sin_parentesis", None),
])
def test_stem_from_filename(name, expected):
    assert engine.stem_from_filename(Path(name + ".wav")) == expected


def test_safe_name():
    assert engine.safe_name('a/b:c*?"<>|') == "a_b_c______"
    assert engine.safe_name("...") == "audio"


def _tone(path: Path, freq: float, secs: float, amp=0.25):
    t = np.arange(int(engine.SAMPLE_RATE * secs)) / engine.SAMPLE_RATE
    y = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), np.stack([y, y], 1), engine.SAMPLE_RATE, subtype="FLOAT")
    return path


def test_mix_files_pads_and_sums(tmp_path):
    a = _tone(tmp_path / "a.wav", 220, 1.0)
    b = _tone(tmp_path / "b.wav", 330, 0.5)
    out = engine.mix_files([a, b], tmp_path / "sum.wav")
    data, sr = sf.read(str(out))
    ref_a, _ = sf.read(str(a))
    ref_b, _ = sf.read(str(b))
    assert sr == engine.SAMPLE_RATE and data.shape == ref_a.shape
    np.testing.assert_allclose(data[: len(ref_b)], ref_a[: len(ref_b)] + ref_b, atol=1e-6)
    np.testing.assert_allclose(data[len(ref_b):], ref_a[len(ref_b):], atol=1e-6)


@pytest.mark.parametrize("fmt", ["wav", "flac", "mp3"])
def test_decode_and_export_roundtrip(tmp_path, fmt):
    src = _tone(tmp_path / "src.wav", 440, 0.5)
    mix = tmp_path / "mix.wav"
    dur = engine.decode_to_wav(src, mix)
    assert abs(dur - 0.5) < 0.01
    out = engine.export(mix, tmp_path / f"out.{fmt}", fmt)
    info = sf.info(str(out)) if fmt != "mp3" else None
    assert out.stat().st_size > 1000
    if fmt == "wav":
        assert info.subtype == "PCM_24"
    if fmt == "flac":
        assert info.subtype == "PCM_24"


def test_quality_params():
    ov = lambda q, d: engine.quality_params(q, d)["mdxc_params"]["overlap"]
    assert ov("balanced", 4) == 2 and ov("balanced", 1) == 1      # nunca más lento que el modelo
    assert ov("max", 1) == 4 and ov("max", 8) == 8                # nunca menos que el modelo
    assert ov("balanced", None) is None and ov("max", None) == 4
    assert engine.quality_params("balanced")["demucs_params"]["shifts"] == 1
    assert engine.quality_params("max")["demucs_params"]["shifts"] == 2


def test_model_default_overlap(tmp_path):
    (tmp_path / "a.yaml").write_text("inference:\n  batch_size: 1\n  num_overlap: 4\n")
    (tmp_path / "config_b.yaml").write_text("inference:\n  num_overlap: 1\n")
    assert engine.model_default_overlap(tmp_path, "a.ckpt") == 4
    assert engine.model_default_overlap(tmp_path, "b.ckpt") == 1
    assert engine.model_default_overlap(tmp_path, "c.ckpt") is None


def test_modes_ranked_low_to_high_and_tiered():
    ordered = presets.modes_by_quality()
    ranks = [m.rank for m in ordered]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks) and ranks[0] >= 1
    public = presets.public_modes()
    assert [m["key"] for m in public] == [m.key for m in ordered]
    tier_keys = [t["key"] for t in presets.public_tiers()]
    seen = [tier_keys.index(m["tier"]) for m in public]
    assert seen == sorted(seen), "las categorías deben ir de menor a mayor"
    assert all(m["quality_note"] and m["speed"] for m in public)


def _models(steps):
    return [s.models[0] for s in steps]


def test_plan_all_when_nothing_selected():
    _, steps, outputs = presets.plan_for("stems4", False, None)
    assert len(steps) == 2 and "instrumental" in outputs


def test_plan_prunes_unneeded_steps():
    _, steps, outputs = presets.plan_for("stems4", False, ["vocals"])
    assert _models(steps) == [presets.MELBAND_KIM] and outputs == ["vocals"]
    _, steps, outputs = presets.plan_for("stems4", False, ["Batería", "bajo"])   # etiquetas
    assert _models(steps) == [presets.MELBAND_KIM, presets.ROFORMER_SW] and outputs == ["drums", "bass"]


def test_plan_derived_instrumental_needs_its_parts():
    _, steps, outputs = presets.plan_for("stems6", False, ["instrumental"])
    assert _models(steps) == [presets.ROFORMER_SW] and outputs == ["instrumental"]


def test_plan_drum_parts_pull_whole_chain():
    _, steps, outputs = presets.plan_for("stems4", True, ["kick", "hh"])
    assert _models(steps) == [presets.MELBAND_KIM, presets.ROFORMER_SW, presets.DRUMSEP]
    assert outputs == ["kick", "hihat"]
    _, steps, _ = presets.plan_for("stems4", True, ["vocals"])
    assert presets.DRUMSEP not in _models(steps)


def test_plan_rejects_unavailable_selection():
    with pytest.raises(ValueError):
        presets.plan_for("instrumental", False, ["guitar"])


def test_instrumental_mode_uses_one_specialist_per_stem():
    _, steps, _ = presets.plan_for("instrumental", False, ["vocals"])
    assert _models(steps) == [presets.MELBAND_KIM]
    _, steps, _ = presets.plan_for("instrumental", False, ["instrumental"])
    assert _models(steps) == [presets.BS_GABOX]


def test_ultra_is_ensemble_then_sw():
    mode = presets.MODES["ultra"]
    ens, sw = mode.steps
    assert ens.combine == "ensemble" and len(ens.uses) >= 3
    vocal_models = [u for u in ens.uses if "vocals" in u.mapping.values()]
    assert len(vocal_models) >= 3
    assert sw.source == "instrumental" and sw.models[0] == presets.ROFORMER_SW
    assert mode.rank == max(m.rank for m in presets.MODES.values())


def test_average_files_weighted(tmp_path):
    a = _tone(tmp_path / "a.wav", 220, 0.5, amp=0.2)
    b = _tone(tmp_path / "b.wav", 220, 0.5, amp=0.6)
    out = engine.average_files([(a, 1.0), (b, 3.0)], tmp_path / "avg.wav")
    data, _ = sf.read(str(out)); ra, _ = sf.read(str(a)); rb, _ = sf.read(str(b))
    np.testing.assert_allclose(data, (ra + 3 * rb) / 4, atol=1e-6)


class _FakeEngine(engine.Engine):
    """Simula modelos: los de `broken` no cargan; los demás devuelven un tono por stem."""

    def __init__(self, tmp, broken=()):
        self.tmp, self.broken, self.ran = tmp, set(broken), []

    def _run_model(self, use, source, out_dir, progress, emit, say, cancel, quality, part=(0, 1)):
        if use.model in self.broken:
            raise engine.ModelUnavailable(f"falta {use.model}")
        self.ran.append(use.model)
        out_dir.mkdir(parents=True, exist_ok=True)
        amp = 0.1 * (len(self.ran))
        return {t: _tone(out_dir / f"{t}.wav", 220, 0.2, amp=amp) for t in set(use.mapping.values()) if t}


def _run(eng, step, tmp):
    return eng._run_step(step, {"mix": tmp / "mix.wav", "instrumental": tmp / "mix.wav"}, tmp / "s",
                         engine.Progress(), lambda: None, lambda m: None, None, "balanced", [])


def test_fallback_uses_alternative(tmp_path):
    eng = _FakeEngine(tmp_path, broken={presets.MELBAND_KIM})
    step = presets.MODES["stems4"].steps[0]
    produced, used = _run(eng, step, tmp_path)
    assert used == [presets.ROFORMER_VOCALS] and set(produced) == {"vocals", "instrumental"}


def test_fallback_all_broken_raises(tmp_path):
    step = presets.MODES["stems4"].steps[0]
    eng = _FakeEngine(tmp_path, broken=set(step.models))
    with pytest.raises(RuntimeError):
        _run(eng, step, tmp_path)


def test_ensemble_skips_broken_and_averages(tmp_path):
    step = presets.MODES["ultra"].steps[0]
    eng = _FakeEngine(tmp_path, broken={presets.MELBAND_BETA4})
    produced, used = _run(eng, step, tmp_path)
    assert presets.MELBAND_BETA4 not in used and len(used) == len(step.uses) - 1
    data, _ = sf.read(str(produced["vocals"]))
    # voz = promedio de los 2 modelos de voz restantes (amplitudes 0.1 y 0.2) -> pico ≈ 0.15
    assert abs(np.abs(data).max() - 0.15) < 0.01


def test_mix_components_avoids_double_counting():
    assert presets.mix_components(["bass", "vocals"]) == (["vocals", "bass"], [])
    assert presets.mix_components(["vocals", "instrumental"]) == (["vocals", "instrumental"], [])
    assert presets.mix_components(["instrumental", "drums", "vocals"]) == (["vocals", "drums"], ["instrumental"])
    assert presets.mix_components(["drums", "kick", "bass"]) == (["drums", "bass"], ["kick"])
    assert presets.mix_components(["kick", "snare"]) == (["kick", "snare"], [])
    assert presets.mix_label(["vocals", "bass"]) == "Mezcla (Voz + Bajo)"


def test_mix_files_safe_limits_peak(tmp_path):
    a = _tone(tmp_path / "a.wav", 220, 0.3, amp=0.7)
    b = _tone(tmp_path / "b.wav", 220, 0.3, amp=0.7)
    out, gain = engine.mix_files_safe([a, b], tmp_path / "m.wav")
    data, _ = sf.read(str(out))
    assert gain < 1.0 and abs(np.abs(data).max() - 0.99) < 1e-3
    out, gain = engine.mix_files_safe([_tone(tmp_path / "c.wav", 220, 0.3, amp=0.2)], tmp_path / "m2.wav")
    assert gain == 1.0


@pytest.mark.parametrize("name,key", [("Batería", "drums"), ("bateria", "drums"), ("BAJO", "bass"),
                                      ("hi-hat", "hihat"), ("Guitarra", "guitar"), ("vocals", "vocals")])
def test_resolve_stem_accent_insensitive(name, key):
    assert presets.resolve_stem(name) == key


def test_version_matches_pyproject():
    import re
    import stemforge
    toml = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert re.search(r'^version = "([^"]+)"', toml, re.M).group(1) == stemforge.__version__


# ------------------------------------------------------------- multiplataforma
from stemforge import config, osutil  # noqa: E402


@pytest.mark.parametrize("win,mac,env,expected", [
    (True, False, {"LOCALAPPDATA": "/x/AppData/Local"}, Path("/x/AppData/Local/StemForge")),
    (False, True, {}, Path.home() / "Library" / "Application Support" / "StemForge"),
    (False, False, {"XDG_DATA_HOME": "/x/share"}, Path("/x/share/StemForge")),
])
def test_support_dir_per_platform(monkeypatch, win, mac, env, expected):
    monkeypatch.setattr(osutil, "IS_WINDOWS", win)
    monkeypatch.setattr(osutil, "IS_MAC", mac)
    for k in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert osutil.support_dir() == expected


def test_ffmpeg_copied_when_symlinks_unavailable(tmp_path, monkeypatch):
    """En Windows (sin permiso para symlinks) se copia el binario, y no se recopia si ya está."""
    monkeypatch.setattr(osutil, "IS_WINDOWS", True)
    exe = tmp_path / "ffmpeg-win-x86_64.exe"
    exe.write_bytes(b"binario")
    link = tmp_path / "bin" / "ffmpeg.exe"
    link.parent.mkdir()
    assert config._point_to(link, exe)
    assert not link.is_symlink() and link.read_bytes() == b"binario"
    mtime = link.stat().st_mtime_ns
    assert config._point_to(link, exe) and link.stat().st_mtime_ns == mtime
    exe.write_bytes(b"binario nuevo")      # otra versión de imageio-ffmpeg
    assert config._point_to(link, exe) and link.read_bytes() == b"binario nuevo"


def test_ffmpeg_symlink_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(osutil, "IS_WINDOWS", False)
    exe = tmp_path / "ffmpeg-bin"
    exe.write_bytes(b"x")
    link = tmp_path / "ffmpeg"
    assert config._point_to(link, exe) and link.is_symlink()


def test_choose_folder_prefers_window_picker(monkeypatch):
    seen = []
    osutil.set_folder_picker(lambda initial: seen.append(initial) or "/elegida")
    try:
        assert osutil.choose_folder("Carpeta", "/inicial") == "/elegida"
        assert seen == ["/inicial"]
        osutil.set_folder_picker(lambda initial: None)   # cancelado
        assert osutil.choose_folder("Carpeta") is None
    finally:
        osutil.set_folder_picker(None)


def test_no_uvr_dependency():
    assert not hasattr(config, "UVR_DEMUCS_DIR") and not hasattr(config, "link_uvr_models")


def test_windows_launchers_reference_existing_files():
    root = Path(__file__).resolve().parents[1]
    assert (root / "stemforge" / "web" / "StemForge.ico").is_file()
    iss = (root / "installer" / "StemForge.iss").read_text(encoding="utf-8-sig")
    assert "-m stemforge.app" in iss and "vicvinue.StemForge" in iss
    from stemforge import app
    assert app.WINDOWS_APP_ID == "vicvinue.StemForge"


def test_device_info_reports_cuda_build_and_nvidia(monkeypatch):
    monkeypatch.setattr(engine, "_nvidia_gpu", [])
    monkeypatch.setattr(engine.shutil, "which", lambda name: None)
    assert engine.nvidia_gpu_name() is None          # sin driver NVIDIA
    info = engine.Engine.device_info()
    assert {"system", "cuda", "torch_cuda", "nvidia_gpu"} <= info.keys()


def test_nvidia_gpu_name_from_driver(monkeypatch):
    import subprocess

    monkeypatch.setattr(engine, "_nvidia_gpu", [])
    monkeypatch.setattr(engine.shutil, "which", lambda name: "/fake/nvidia-smi")
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="NVIDIA GeForce RTX 3060\n", stderr=""))
    assert engine.nvidia_gpu_name() == "NVIDIA GeForce RTX 3060"
