"""Modos de separación de StemForge.

Cada modo es una cadena de pasos. Un paso ejecuta un modelo sobre la mezcla original
("mix") o sobre un stem producido por un paso anterior, y mapea los stems que devuelve el
modelo a las claves canónicas de StemForge. Un stem mapeado a una clave que ya existe se
SUMA (útil para residuos: p. ej. la "voz" que Demucs encuentra en un instrumental va a "otros").
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Claves canónicas -> etiqueta (también se usa en el nombre de archivo)
STEM_LABELS: dict[str, str] = {
    "vocals": "Voz",
    "instrumental": "Instrumental",
    "drums": "Batería",
    "bass": "Bajo",
    "guitar": "Guitarra",
    "piano": "Piano",
    "other": "Otros",
    "kick": "Bombo",
    "snare": "Caja",
    "toms": "Toms",
    "hihat": "Hi-Hat",
    "ride": "Ride",
    "crash": "Crash",
}

# Orden de presentación
STEM_ORDER = list(STEM_LABELS)

# Modelos (nombres de archivo de audio-separator)
ROFORMER_VOCALS = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"   # BS-Roformer Viperx 1297
DEMUCS_FT = "htdemucs_ft.yaml"                                  # Demucs v4 fine-tuned (4 stems)
DEMUCS = "htdemucs.yaml"                                        # Demucs v4 (rápido)
DEMUCS_6S = "htdemucs_6s.yaml"                                  # Demucs v4 6 stems
ROFORMER_SW = "BS-Roformer-SW.ckpt"                             # BS-Roformer SW (6 stems)
DRUMSEP = "MDX23C-DrumSep-aufr33-jarredou.ckpt"                 # Separación de batería

# Sinónimos de nombres de stem que devuelven los modelos
STEM_ALIASES = {
    "vocal": "vocals", "vocals": "vocals", "voice": "vocals",
    "instrumental": "instrumental", "instrum": "instrumental", "no vocals": "instrumental",
    "drum": "drums", "drums": "drums",
    "bass": "bass",
    "guitar": "guitar", "guitars": "guitar",
    "piano": "piano", "keys": "piano",
    "other": "other", "others": "other",
    "kick": "kick", "snare": "snare", "toms": "toms", "tom": "toms",
    "hh": "hihat", "hihat": "hihat", "hi-hat": "hihat",
    "ride": "ride", "crash": "crash", "cymbals": "crash",
}


@dataclass(frozen=True)
class Step:
    model: str
    source: str = "mix"                        # "mix" o clave de un stem previo
    mapping: dict[str, str | None] = field(default_factory=dict)  # stem del modelo -> clave (None = descartar)
    label: str = ""


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    description: str
    steps: tuple[Step, ...]
    outputs: tuple[str, ...]                    # stems finales que se exportan
    derived: dict[str, tuple[str, ...]] = field(default_factory=dict)  # stem = suma de otros
    fallback: str | None = None                 # modo alternativo si falla la descarga del modelo
    rank: int = 0                               # calidad de separación: 1 = menor ... 5 = mayor
    quality_note: str = ""                      # de dónde sale la valoración
    speed: str = ""                             # tiempo orientativo (M1 Pro, calidad Equilibrada)


# Categorías de calidad (de menor a mayor)
TIERS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("basica", "Básica", (1, 2)),
    ("alta", "Alta", (3,)),
    ("maxima", "Máxima", (4, 5)),
)


def tier_of(rank: int) -> tuple[str, str]:
    for key, label, ranks in TIERS:
        if rank in ranks:
            return key, label
    return "basica", "Básica"


MODES: dict[str, Mode] = {}


def _register(mode: Mode) -> Mode:
    MODES[mode.key] = mode
    return mode


_register(Mode(
    key="instrumental",
    name="Instrumental + Voz",
    description="2 pistas con BS-Roformer (máxima calidad en voz/instrumental).",
    steps=(Step(ROFORMER_VOCALS, "mix", {"vocals": "vocals", "instrumental": "instrumental"},
                "Separando voz e instrumental (BS-Roformer)"),),
    outputs=("vocals", "instrumental"),
    rank=5,
    quality_note="Modelo especializado de 2 pistas: SDR voz 11,8 dB · instrumental 16,5 dB.",
    speed="≈ 4–5 min por canción de 4 min",
))

_register(Mode(
    key="stems4",
    name="4 Stems · Alta calidad",
    description="Voz con BS-Roformer y luego Batería / Bajo / Otros con Demucs v4 fine-tuned sobre el instrumental.",
    steps=(
        Step(ROFORMER_VOCALS, "mix", {"vocals": "vocals", "instrumental": "instrumental"},
             "Separando voz e instrumental (BS-Roformer)"),
        Step(DEMUCS_FT, "instrumental",
             {"drums": "drums", "bass": "bass", "other": "other", "vocals": "other"},
             "Separando batería, bajo y otros (Demucs FT)"),
    ),
    outputs=("vocals", "drums", "bass", "other", "instrumental"),
    rank=3,
    quality_note="Voz con BS-Roformer (SDR 11,8 dB); batería/bajo con Demucs FT (≈ 9,2 dB medio en MUSDB).",
    speed="≈ 6 min por canción de 4 min",
))

_register(Mode(
    key="stems6",
    name="6 Stems · Guitarra y Piano",
    description="Voz, Batería, Bajo, Guitarra, Piano y Otros con BS-Roformer SW (alternativa: Demucs 6s).",
    steps=(Step(ROFORMER_SW, "mix",
                {"vocals": "vocals", "drums": "drums", "bass": "bass",
                 "guitar": "guitar", "piano": "piano", "other": "other"},
                "Separando 6 stems (BS-Roformer SW)"),),
    outputs=("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "guitar", "piano", "other")},
    fallback="stems6_demucs",
    rank=4,
    quality_note="BS-Roformer SW: SDR medio ≈ 13,7 dB según la tabla de MVSEP; el mejor modelo abierto de 6 stems.",
    speed="≈ 3 min por canción de 4 min",
))

_register(Mode(
    key="stems6_demucs",
    name="6 Stems · Demucs 6s",
    description="Voz, Batería, Bajo, Guitarra, Piano y Otros con Demucs v4 6s (más ligero).",
    steps=(Step(DEMUCS_6S, "mix",
                {"vocals": "vocals", "drums": "drums", "bass": "bass",
                 "guitar": "guitar", "piano": "piano", "other": "other"},
                "Separando 6 stems (Demucs 6s)"),),
    outputs=("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "guitar", "piano", "other")},
    rank=1,
    quality_note="Demucs 6s: SDR voz 9,6 dB; guitarra y piano con fugas y artefactos notorios.",
    speed="≈ 1 min por canción de 4 min",
))

_register(Mode(
    key="stems4_fast",
    name="4 Stems · Rápido",
    description="Voz / Batería / Bajo / Otros en una pasada con Demucs v4.",
    steps=(Step(DEMUCS, "mix",
                {"vocals": "vocals", "drums": "drums", "bass": "bass", "other": "other"},
                "Separando 4 stems (Demucs v4)"),),
    outputs=("vocals", "drums", "bass", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "other")},
    rank=2,
    quality_note="Demucs v4 (htdemucs): SDR voz 9,9 dB · ≈ 9,0 dB medio en MUSDB.",
    speed="< 1 min por canción de 4 min",
))

DRUMSEP_STEP = Step(
    DRUMSEP, "drums",
    {"kick": "kick", "snare": "snare", "toms": "toms", "hh": "hihat", "hihat": "hihat",
     "ride": "ride", "crash": "crash"},
    "Dividiendo la batería en piezas (MDX23C DrumSep)",
)
DRUMSEP_OUTPUTS = ("kick", "snare", "toms", "hihat", "ride", "crash")


def build_plan(mode_key: str, drumsep: bool = False) -> tuple[Mode, list[Step], list[str]]:
    """Devuelve (modo, pasos, stems de salida) incluyendo pasos opcionales."""
    if mode_key not in MODES:
        raise ValueError(f"Modo desconocido: {mode_key}")
    mode = MODES[mode_key]
    steps = list(mode.steps)
    outputs = list(mode.outputs)
    if drumsep and "drums" in outputs:
        steps.append(DRUMSEP_STEP)
        outputs += list(DRUMSEP_OUTPUTS)
    return mode, steps, outputs


def normalize_stem_name(raw: str) -> str:
    key = raw.strip().lower().replace("_", " ")
    return STEM_ALIASES.get(key, key)


def modes_by_quality() -> list[Mode]:
    """Modos ordenados de menor a mayor calidad de separación."""
    return sorted(MODES.values(), key=lambda m: m.rank)


def public_modes() -> list[dict]:
    out = []
    for m in modes_by_quality():
        tier_key, tier_label = tier_of(m.rank)
        out.append({"key": m.key, "name": m.name, "description": m.description,
                    "outputs": [STEM_LABELS[o] for o in m.outputs],
                    "has_drums": "drums" in m.outputs,
                    "rank": m.rank, "tier": tier_key, "tier_label": tier_label,
                    "quality_note": m.quality_note, "speed": m.speed})
    return out


def public_tiers() -> list[dict]:
    return [{"key": k, "label": label} for k, label, _ in TIERS]
