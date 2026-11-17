# StemForge

Separador de stems para **macOS con Apple Silicon** (M1/M2/M3/M4), inspirado en Ultimate Vocal Remover.
Usa la GPU del Mac (PyTorch **MPS / Metal**) y **CoreML** para los modelos ONNX.

## Qué hace

Modos ordenados **de menor a mayor calidad de separación**:

| # | Categoría | Modo | Salida | Modelos | Tiempo (canción de 4 min)* |
|---|---|---|---|---|---|
| 1 | Básica | **6 Stems · Demucs 6s** | Voz, Batería, Bajo, Guitarra, Piano, Otros, Instrumental | Demucs v4 6s | ≈ 1 min |
| 2 | Básica | **4 Stems · Rápido** | Voz, Batería, Bajo, Otros, Instrumental | Demucs v4 | < 1 min |
| 3 | Alta | **6 Stems · Guitarra y Piano** | Voz, Batería, Bajo, Guitarra, Piano, Otros, Instrumental | BS-Roformer SW | ≈ 3 min |
| 4 | Alta | **4 Stems · Alta calidad** | Voz, Batería, Bajo, Otros, Instrumental | MelBand Roformer Kim → BS-Roformer SW sobre el instrumental | ≈ 5 min |
| 5 | Máxima | **Instrumental + Voz** | Voz, Instrumental | Voz: MelBand Roformer Kim · Instrumental: BS-Roformer Gabox | ≈ 8 min |
| 6 | Máxima | **Ultra · Ensemble** | Voz, Batería, Bajo, Guitarra, Piano, Otros, Instrumental | Promedio de 3 modelos de voz y 4 de instrumental (Kim, unwa Big Beta 4, Viperx 1297, Gabox) → BS-Roformer SW | ≈ 20 min |

Si un modelo no se puede descargar, cada paso usa una alternativa (p. ej. Viperx 1297 en lugar de Kim,
Demucs en lugar de SW) y el trabajo lo avisa. En Ultra, un modelo que falle se omite del promedio.

\* M1 Pro, calidad *Equilibrada*. La valoración se basa en los SDR publicados (lista de modelos de
audio-separator, README de Demucs y tabla de MVSEP). Entre los modos «Máxima» la comparación es
aproximada, porque los SDR de 2 pistas y de 6 pistas no son directamente comparables.

**Flujo:** arrastra una o varias canciones → quedan *preparadas* (puedes quitarlas) → eliges modo y
opciones → pulsa **«Agregar a la cola y separar»**. Recién ahí se envían y empieza la conversión.

Opcional en todos los modos con batería: **dividir la batería** en Bombo, Caja, Toms, Hi-Hat, Ride y Crash (MDX23C DrumSep).

- **Calidad**: *Equilibrada* (solapamiento ≤ 2 en Roformer, 1 shift en Demucs; nunca más lento que el ajuste del modelo) o *Máxima* (solapamiento ≥ 4 y 2 shifts: ≈ 2× más lenta).
- **Formatos**: WAV 24-bit, FLAC 24-bit, MP3 (320k por defecto). Internamente todo se procesa en float32 44,1 kHz.
- **Mezclador** integrado: escucha los stems sincronizados, con mute/solo/volumen y forma de onda.
- **Qué extraer**: «Todo» o solo los stems que elijas (p. ej. solo Voz y Bajo, o solo Bombo y Caja). Solo se ejecutan los modelos necesarios: pedir solo la Voz en «4 Stems · Alta calidad» no ejecuta Demucs.
- **Mezclar la selección**: además de cada pista por separado, un archivo extra con las pistas elegidas
  sumadas, p. ej. `Canción - Mezcla (Voz + Bajo).wav`. No suma dos veces el mismo sonido (si eliges
  Instrumental junto con Batería, el Instrumental se entrega aparte pero no entra en la mezcla) y baja el
  volumen solo si la suma saturaría. Se activa al elegir dos o más pistas (con «Todo» equivaldría al original).
- **Cola**: arrastra varias canciones; se procesan de a una (la GPU no se comparte).

Los archivos se guardan en `~/Music/StemForge/<Canción> [<Modo>]/<Canción> - <Stem>.wav` junto a un
`stemforge.json` con los modelos y ajustes usados.

## Instalación

```bash
./setup.sh          # instala ffmpeg/uv si faltan, crea .venv (Python 3.12) y StemForge.app
```

Luego abre **StemForge.app** (puedes arrastrarlo al Dock) o ejecuta `./run.sh` (`./run.sh --browser` para usar el navegador).

Los modelos se descargan solos la primera vez que se usan (≈ 0,5–0,7 GB cada Roformer) en
`~/Library/Application Support/StemForge/models`. Si tienes UVR instalado, sus pesos de Demucs se
enlazan automáticamente para no descargarlos otra vez.

## Línea de comandos

```bash
.venv/bin/stemforge cancion.mp3                         # 4 stems alta calidad
.venv/bin/stemforge cancion.mp3 -m instrumental -f flac
.venv/bin/stemforge carpeta/ -m stems6 --drumsep -q max
.venv/bin/stemforge cancion.mp3 -m stems6 -s voz,guitarra        # solo esos stems
.venv/bin/stemforge cancion.mp3 -m stems4 -s voz,bajo --mix         # + archivo «Mezcla (Voz + Bajo)»
.venv/bin/stemforge --list-modes
.venv/bin/stemforge --info                              # comprueba MPS / CoreML
```

## Rendimiento orientativo (M1 Pro, 16 GB, calidad Equilibrada)

Por cada minuto de audio: MelBand Kim ≈ 26 s · BS-Roformer SW ≈ 45 s · Big Beta 4 ≈ 65 s ·
Viperx 1297 ≈ 70 s · Gabox ≈ 70 s · Demucs FT ≈ 20 s · Demucs ≈ 11 s.
*Máxima* aproximadamente duplica los tiempos de los Roformer.

## Arquitectura

```
stemforge/
  presets.py   modos = cadenas de pasos (modelo, entrada, mapeo de stems)
  engine.py    ejecuta los pasos con audio-separator, suma residuos, exporta con ffmpeg
  jobs.py      cola con un hilo trabajador, progreso y cancelación
  server.py    API FastAPI solo en 127.0.0.1 (token por sesión + control de Host)
  app.py       ventana nativa WebKit (pywebview) o navegador
  cli.py       interfaz de línea de comandos
  web/         interfaz (HTML + Web Audio)
```

Agregar un modo nuevo = añadir un `Mode` en `presets.py` con sus `Step`. Cualquier modelo de la lista
de `audio-separator -l` sirve (MDX-Net, VR, Demucs, MDX23C, BS/MelBand-Roformer).

## Tests

```bash
.venv/bin/python -m pytest -q
```

## Créditos y licencias

- [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) (MIT) — motor de inferencia de modelos UVR.
- [Demucs](https://github.com/facebookresearch/demucs) (MIT) — Meta AI.
- [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) (MIT) — inspiración y modelos MDX/VR.
- Pesos de modelos: BS-Roformer (viperx), MelBand Roformer (Kimberley Jensen), MelBand Big Beta 4 (unwa),
  BS-Roformer (Gabox), BS-Roformer SW (jarredou), MDX23C DrumSep (aufr33 & jarredou).
  Cada modelo tiene su propia licencia; revísalas antes de cualquier uso que no sea personal.
