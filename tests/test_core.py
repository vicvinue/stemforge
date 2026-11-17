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
            produced |= {v for v in step.mapping.values() if v}
        produced |= set(mode.derived)
        for out in mode.outputs:
            assert out in presets.STEM_LABELS
            assert out in produced, f"{mode.key}: nadie produce {out}"


def test_fallback_points_to_existing_mode():
    for mode in presets.MODES.values():
        if mode.fallback:
            assert mode.fallback in presets.MODES


def test_build_plan_drumsep_only_when_drums():
    _, steps, outputs = presets.build_plan("stems4", drumsep=True)
    assert steps[-1].model == presets.DRUMSEP and "kick" in outputs
    _, steps, outputs = presets.build_plan("instrumental", drumsep=True)
    assert all(s.model != presets.DRUMSEP for s in steps) and "kick" not in outputs
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
    assert engine.quality_params("max")["mdxc_params"]["overlap"] is None
    assert engine.quality_params("balanced")["mdxc_params"]["overlap"] == 2
    assert engine.quality_params("balanced")["demucs_params"]["shifts"] == 1
