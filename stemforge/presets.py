"""Modos de separación de StemForge.

Cada modo es una cadena de pasos. Un paso trabaja sobre la mezcla original ("mix") o sobre un
stem producido por un paso anterior, con uno o varios modelos (`Use`):

- combine="fallback": usa el primer modelo que se pueda cargar (los demás son alternativas).
- combine="ensemble": ejecuta todos y PROMEDIA (ponderado) cada stem entre modelos.

Dentro de un mismo modelo, dos stems mapeados a la misma clave se SUMAN (residuos: p. ej. la
"voz" que encuentra un modelo de instrumentos en un instrumental va a "otros").
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
MELBAND_KIM = "vocals_mel_band_roformer.ckpt"                   # MelBand Roformer Kim (mejor voz)
MELBAND_BETA4 = "melband_roformer_big_beta4.ckpt"               # MelBand Roformer Big Beta 4 (unwa)
BS_GABOX = "bs_roformer_vocals_gabox.ckpt"                      # BS-Roformer Gabox (mejor instrumental)
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
class Use:
    """Un modelo dentro de un paso y cómo se mapean sus stems (None = descartar)."""
    model: str
    mapping: dict[str, str | None] = field(default_factory=dict)
    weight: float = 1.0


@dataclass(frozen=True)
class Step:
    uses: tuple[Use, ...]
    source: str = "mix"                        # "mix" o clave de un stem previo
    label: str = ""
    combine: str = "fallback"                  # fallback | ensemble

    @property
    def targets(self) -> set[str]:
        return {v for u in self.uses for v in u.mapping.values() if v}

    @property
    def models(self) -> list[str]:
        return [u.model for u in self.uses]


def single(model: str, source: str, mapping: dict, label: str, *fallbacks: Use) -> Step:
    return Step(uses=(Use(model, mapping), *fallbacks), source=source, label=label, combine="fallback")


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    description: str
    steps: tuple[Step, ...]
    outputs: tuple[str, ...]                    # stems finales que se exportan
    derived: dict[str, tuple[str, ...]] = field(default_factory=dict)  # stem = suma de otros
    rank: int = 0                               # calidad de separación: 1 = menor ... 6 = mayor
    quality_note: str = ""                      # de dónde sale la valoración
    speed: str = ""                             # tiempo orientativo (M1 Pro, calidad Equilibrada)


# Categorías de calidad (de menor a mayor)
TIERS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("basica", "Básica", (1, 2)),
    ("alta", "Alta", (3, 4)),
    ("maxima", "Máxima", (5, 6)),
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


# --- Mapeos reutilizables ----------------------------------------------------------
SIX = {"vocals": "vocals", "drums": "drums", "bass": "bass", "guitar": "guitar", "piano": "piano", "other": "other"}
# Instrumentos sobre un instrumental: guitarra/piano/voz residual -> "otros"
ON_INSTRUMENTAL_4 = {"drums": "drums", "bass": "bass", "other": "other",
                     "guitar": "other", "piano": "other", "vocals": "other"}
ON_INSTRUMENTAL_6 = {"drums": "drums", "bass": "bass", "guitar": "guitar", "piano": "piano",
                     "other": "other", "vocals": "other"}
VOX_SPLIT = {"vocals": "vocals", "other": "instrumental", "instrumental": "instrumental"}
ONLY_VOCALS = {"vocals": "vocals", "other": None, "instrumental": None}
ONLY_INSTRUMENTAL = {"vocals": None, "other": "instrumental", "instrumental": "instrumental"}

# 1 · Básica -----------------------------------------------------------------------
_register(Mode(
    key="stems6_demucs",
    name="6 Stems · Demucs 6s",
    description="Voz, Batería, Bajo, Guitarra, Piano y Otros con Demucs v4 6s (más ligero).",
    steps=(single(DEMUCS_6S, "mix", SIX, "Separando 6 stems (Demucs 6s)"),),
    outputs=("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "guitar", "piano", "other")},
    rank=1,
    quality_note="Demucs 6s: SDR voz 9,6 dB · batería 8,5 dB; guitarra y piano con fugas y artefactos notorios.",
    speed="≈ 1 min por canción de 4 min",
))

_register(Mode(
    key="stems4_fast",
    name="4 Stems · Rápido",
    description="Voz / Batería / Bajo / Otros en una pasada con Demucs v4.",
    steps=(single(DEMUCS, "mix", {"vocals": "vocals", "drums": "drums", "bass": "bass", "other": "other"},
                  "Separando 4 stems (Demucs v4)"),),
    outputs=("vocals", "drums", "bass", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "other")},
    rank=2,
    quality_note="Demucs v4 (htdemucs): SDR voz 9,9 dB · batería 9,5 dB · bajo 11,6 dB.",
    speed="< 1 min por canción de 4 min",
))

# 2 · Alta -------------------------------------------------------------------------
_register(Mode(
    key="stems6",
    name="6 Stems · Guitarra y Piano",
    description="Voz, Batería, Bajo, Guitarra, Piano y Otros en una pasada con BS-Roformer SW.",
    steps=(single(ROFORMER_SW, "mix", SIX, "Separando 6 stems (BS-Roformer SW)",
                  Use(DEMUCS_6S, SIX)),),
    outputs=("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental"),
    derived={"instrumental": ("drums", "bass", "guitar", "piano", "other")},
    rank=3,
    quality_note="BS-Roformer SW: el mejor modelo abierto de 6 stems (SDR medio ≈ 13,7 dB en MVSEP).",
    speed="≈ 3 min por canción de 4 min",
))

_register(Mode(
    key="stems4",
    name="4 Stems · Alta calidad",
    description="Voz con MelBand Roformer (Kim) y luego Batería / Bajo / Otros con BS-Roformer SW sobre el instrumental.",
    steps=(
        single(MELBAND_KIM, "mix", VOX_SPLIT, "Separando voz e instrumental (MelBand Roformer Kim)",
               Use(ROFORMER_VOCALS, VOX_SPLIT)),
        single(ROFORMER_SW, "instrumental", ON_INSTRUMENTAL_4, "Separando batería, bajo y otros (BS-Roformer SW)",
               Use(DEMUCS_FT, ON_INSTRUMENTAL_4)),
    ),
    outputs=("vocals", "drums", "bass", "other", "instrumental"),
    rank=4,
    quality_note="Voz con el mejor modelo abierto de voz (SDR 12,6 dB) y batería/bajo con BS-Roformer SW "
                 "sobre un instrumental ya sin voz.",
    speed="≈ 5 min por canción de 4 min",
))

# 3 · Máxima -----------------------------------------------------------------------
_register(Mode(
    key="instrumental",
    name="Instrumental + Voz",
    description="Cada pista con su especialista: Voz con MelBand Roformer (Kim) e Instrumental con BS-Roformer (Gabox).",
    steps=(
        single(MELBAND_KIM, "mix", ONLY_VOCALS, "Extrayendo la voz (MelBand Roformer Kim)",
               Use(ROFORMER_VOCALS, ONLY_VOCALS)),
        single(BS_GABOX, "mix", ONLY_INSTRUMENTAL, "Extrayendo el instrumental (BS-Roformer Gabox)",
               Use(ROFORMER_VOCALS, ONLY_INSTRUMENTAL)),
    ),
    outputs=("vocals", "instrumental"),
    rank=5,
    quality_note="Mejores modelos abiertos de cada pista: SDR voz 12,6 dB (Kim) · instrumental 17,2 dB (Gabox).",
    speed="≈ 8 min por canción de 4 min",
))

_register(Mode(
    key="ultra",
    name="Ultra · Ensemble",
    description="Promedia 3 modelos de voz y 4 de instrumental; luego BS-Roformer SW separa los instrumentos. "
                "Lo mejor posible, pero lento.",
    steps=(
        Step(uses=(
            Use(MELBAND_KIM, VOX_SPLIT),
            Use(MELBAND_BETA4, VOX_SPLIT),
            Use(ROFORMER_VOCALS, VOX_SPLIT),
            Use(BS_GABOX, ONLY_INSTRUMENTAL),
        ), source="mix", label="Ensemble de voz e instrumental (4 modelos Roformer)", combine="ensemble"),
        single(ROFORMER_SW, "instrumental", ON_INSTRUMENTAL_6, "Separando instrumentos (BS-Roformer SW)",
               Use(DEMUCS_6S, ON_INSTRUMENTAL_6)),
    ),
    outputs=("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental"),
    rank=6,
    quality_note="Ensemble (promedio de modelos), la técnica de las primeras posiciones de MVSEP: "
                 "reduce artefactos y fugas de cada modelo individual.",
    speed="≈ 20 min por canción de 4 min",
))

DRUMSEP_STEP = single(
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


def plan_for(mode_key: str, drumsep: bool = False, selected=None) -> tuple[Mode, list[Step], list[str]]:
    """Como build_plan, pero solo con los stems elegidos y los pasos imprescindibles para obtenerlos.

    selected: claves o etiquetas de stems (p. ej. ["vocals", "Bajo"]); None o vacío = todos.
    """
    mode, steps, outputs = build_plan(mode_key, drumsep)
    if not selected:
        return mode, steps, outputs
    wanted = {resolve_stem(s) for s in selected}
    chosen = [o for o in outputs if o in wanted]
    if not chosen:
        raise ValueError("Ninguno de los stems elegidos está disponible en este modo.")
    required = set(chosen)
    for key in chosen:
        required |= set(mode.derived.get(key, ()))
    needed: list[Step] = []
    for step in reversed(steps):
        if step.targets & required:
            needed.append(step)
            required.add(step.source)
    needed.reverse()
    return mode, needed, chosen


MIX_KEY = "mezcla"
INSTRUMENT_KEYS = ("drums", "bass", "guitar", "piano", "other")


def mix_components(selected) -> tuple[list[str], list[str]]:
    """Stems que entran en la mezcla de la selección, sin sonidos repetidos.

    - Si está «Batería», sus piezas (bombo, caja…) ya están dentro: se omiten.
    - Si está «Instrumental» junto a algún instrumento, el instrumental ya contiene ese
      instrumento: se omite el instrumental.
    Devuelve (componentes, omitidos).
    """
    sel = [k for k in STEM_ORDER if k in set(selected)]
    dropped: list[str] = []
    if "drums" in sel:
        dropped += [k for k in sel if k in DRUMSEP_OUTPUTS]
    if "instrumental" in sel and any(k in sel for k in (*INSTRUMENT_KEYS, *DRUMSEP_OUTPUTS)):
        dropped.append("instrumental")
    return [k for k in sel if k not in dropped], dropped


def mix_label(keys) -> str:
    return "Mezcla (" + " + ".join(STEM_LABELS[k] for k in keys) + ")"


_LABEL_TO_KEY = {v.lower(): k for k, v in STEM_LABELS.items()}


def resolve_stem(name: str) -> str:
    """Acepta clave ('drums'), etiqueta ('Batería') o sinónimo ('hh')."""
    raw = name.strip().lower()
    if raw in STEM_LABELS:
        return raw
    if raw in _LABEL_TO_KEY:
        return _LABEL_TO_KEY[raw]
    return normalize_stem_name(raw)


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
                    "output_keys": list(m.outputs),
                    "has_drums": "drums" in m.outputs,
                    "rank": m.rank, "tier": tier_key, "tier_label": tier_label,
                    "quality_note": m.quality_note, "speed": m.speed})
    return out


def public_stems() -> dict:
    return {"labels": STEM_LABELS, "drum_parts": list(DRUMSEP_OUTPUTS)}


def public_tiers() -> list[dict]:
    return [{"key": k, "label": label} for k, label, _ in TIERS]
