# StemForge · Guía para desarrolladores

Compilar, probar y publicar StemForge. La guía de uso está en el [README](../README.md).

## Instalación para desarrollo

macOS (Apple Silicon):

```bash
./setup.sh          # instala ffmpeg/uv si faltan y crea .venv (Python 3.12)
./run.sh            # ventana nativa; ./run.sh --browser para usar el navegador
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1    # instala uv si falta, crea .venv; CUDA si hay NVIDIA
.\run.bat                                             # .\run.bat --browser para usar el navegador
```

Los modelos se descargan solos la primera vez que se usan (≈ 0,5–0,7 GB cada Roformer) en
`~/Library/Application Support/StemForge/models` (Mac) o `%LOCALAPPDATA%\StemForge\models` (Windows).

## Compilar la app

### macOS

```bash
./build_app.sh          # crea dist/StemForge.app y dist/StemForge-<versión>.dmg
```

La app incluye su propio Python, todas las dependencias y un ffmpeg estático: no necesita esta carpeta,
Homebrew ni un Python instalado. Pesa ≈ 1,4 GB (≈ 650 MB el DMG). Los modelos no van dentro.

- Firmada ad-hoc (no notarizada).
- Todo el bytecode se precompila validado por hash y los lanzadores usan `python3 -I -B`: la app nunca
  escribe dentro del bundle (rompería la firma). Comprobar tras abrirla: `codesign --verify --deep dist/StemForge.app`.
- Registro: `~/Library/Logs/StemForge.log`.

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File build_windows.ps1          # PyTorch CPU
powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Cuda    # PyTorch CUDA (GPU NVIDIA)
```

Crea `dist\StemForge\` (carpeta portable: `Abrir StemForge.cmd`) y, si está
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`),
`dist\StemForge-<versión>-Setup.exe` (o `-CUDA-Setup.exe` + archivos `.bin`). El instalador no pide
administrador: instala en `%LOCALAPPDATA%\Programs\StemForge`.

El workflow `.github/workflows/windows.yml` (manual, en la rama `windows` o al publicar un tag `v*`) compila
las dos variantes, separa audio real, prueba el instalador y el actualizador sobre la copia instalada, y deja
los instaladores como artefactos.

## Publicar una versión

1. Sube `__version__` en `stemforge/__init__.py` y `version` en `pyproject.toml`. Si cambiaste dependencias
   o la versión de Python, sube también `RUNTIME` (el test `test_runtime_bumped_when_dependencies_change`
   lo recuerda): así las instalaciones existentes reciben el instalador completo en vez del código solo.
2. `./build_app.sh` (DMG) y un tag `vX.Y.Z` en GitHub: el workflow de Windows compila los dos `Setup.exe`.
   Copia a `dist/` el DMG y los instaladores de Windows (`gh run download <id>`).
3. `.venv/bin/python tools/make_update_assets.py` crea `dist/stemforge-app-X.Y.Z.zip` y `dist/latest.json`.
4. `gh release create vX.Y.Z` con **todos** los archivos que lista el paso 3. La app consulta
   `releases/latest/download/latest.json`, así que la release debe quedar marcada como «Latest».

**Probar una actualización antes de publicarla:** genera los archivos en una carpeta local
(`tools/make_update_assets.py --dist <carpeta> --base-url file://<carpeta>`) y abre la app con
`STEMFORGE_UPDATE_URL=file://<carpeta>/latest.json` (en el Mac: `open -a StemForge --env STEMFORGE_UPDATE_URL=…`).

## Cómo funciona el actualizador

- **Pequeña** (mismo `RUNTIME`): se baja solo el paquete `stemforge` (≈ 0,3 MB) a
  `<datos>/updates/<versión>/` y `stemforge/__init__.py` lo carga desde ahí al reiniciar. La instalación no se
  modifica. Si la versión nueva no arranca, la siguiente vez se usa la instalada.
- **Completa** (cambió el `RUNTIME`): se baja el instalador de la plataforma (DMG, `Setup.exe` CPU o CUDA),
  se instala al cerrar la app y se vuelve a abrir.
- **git** (copia de desarrollo): `git pull` en `main` (+ dependencias con `uv` si cambiaron).
- **manual** (carpeta portable de Windows): el aviso enlaza a la release.

Todo lo descargado se verifica con SHA-256. Las versiones 0.2.x no traen el actualizador.

## Línea de comandos

```bash
.venv/bin/stemforge cancion.mp3                         # 4 stems alta calidad
.venv/bin/stemforge cancion.mp3 -m instrumental -f flac
.venv/bin/stemforge carpeta/ -m stems6 --drumsep -q max
.venv/bin/stemforge cancion.mp3 -m stems6 -s voz,guitarra        # solo esos stems
.venv/bin/stemforge cancion.mp3 -m stems4 -s voz,bajo --mix         # + archivo «Mezcla (Voz + Bajo)»
.venv/bin/stemforge --list-modes
.venv/bin/stemforge --info                              # comprueba MPS / CoreML / CUDA
```

La app instalada también la trae: `/Applications/StemForge.app/Contents/Resources/stemforge` (Mac) o
`stemforge.cmd` en la carpeta de instalación (Windows).

## Detalles técnicos

- **Modos** (de menor a mayor calidad):

  | Modo | Modelos |
  |---|---|
  | 6 Stems · Demucs 6s | Demucs v4 6s |
  | 4 Stems · Rápido | Demucs v4 |
  | 6 Stems · Guitarra y Piano | BS-Roformer SW |
  | 4 Stems · Alta calidad | MelBand Roformer Kim → BS-Roformer SW sobre el instrumental |
  | Instrumental + Voz | Voz: MelBand Roformer Kim · Instrumental: BS-Roformer Gabox |
  | Ultra · Ensemble | Promedio de 3 modelos de voz y 4 de instrumental (Kim, unwa Big Beta 4, Viperx 1297, Gabox) → BS-Roformer SW |

  La valoración se basa en los SDR publicados (lista de modelos de audio-separator, README de Demucs y tabla
  de MVSEP). Si un modelo no se puede descargar, cada paso usa una alternativa y el trabajo lo avisa.
  Batería por piezas: MDX23C DrumSep.
- **Calidad**: *Equilibrada* = solapamiento ≤ 2 en Roformer, 1 shift en Demucs · *Máxima* = solapamiento ≥ 4
  y 2 shifts. Internamente todo se procesa en float32 a 44,1 kHz.
- **Tempo**: librosa (dependencia de audio-separator; no la agregues a `pyproject.toml` o cambia el `RUNTIME`).
  BPM afinado con regresión sobre los pulsos. La caché de numba va a la carpeta de datos (`NUMBA_CACHE_DIR`).
- **Tono**: ffmpeg `asetrate + aresample + atempo`, con compensación de la latencia de atempo (≈ 21 ms +
  1,15 ms por semitono) para que las pistas transpuestas sigan en sincronía con la batería y el metrónomo.
- **`stemforge.json`** (en cada carpeta de salida): modo, modelos, ajustes, pistas, BPM y pulsos. Las
  versiones transpuestas guardan además `transpose` y `transposed_from`.

### Rendimiento orientativo (M1 Pro, 16 GB, calidad Equilibrada)

Por cada minuto de audio: MelBand Kim ≈ 26 s · BS-Roformer SW ≈ 45 s · Big Beta 4 ≈ 65 s ·
Viperx 1297 ≈ 70 s · Gabox ≈ 70 s · Demucs FT ≈ 20 s · Demucs ≈ 11 s.
*Máxima* aproximadamente duplica los tiempos de los Roformer.

## Arquitectura

```
stemforge/
  presets.py   modos = cadenas de pasos (modelo, entrada, mapeo de stems)
  engine.py    ejecuta los pasos con audio-separator, suma residuos, exporta con ffmpeg
  jobs.py      cola con un hilo trabajador, progreso y cancelación
  sessions.py  sesiones del mezclador: pistas de un trabajo o de una carpeta, metrónomo, versiones transpuestas
  analysis.py  tempo (librosa: BPM + pulsos), metrónomo y transposición (ffmpeg)
  server.py    API FastAPI solo en 127.0.0.1 (token por sesión + control de Host)
  app.py       ventana nativa (pywebview: WebKit en Mac, WebView2 en Windows) o navegador
  osutil.py    diferencias entre sistemas: carpetas de datos, abrir carpeta, selector de carpetas
  updater.py   buscar, descargar y aplicar actualizaciones (latest.json de cada release)
  cli.py       interfaz de línea de comandos
  web/         interfaz (HTML + Web Audio)
```

Agregar un modo nuevo = añadir un `Mode` en `presets.py` con sus `Step`. Cualquier modelo de la lista
de `audio-separator -l` sirve (MDX-Net, VR, Demucs, MDX23C, BS/MelBand-Roformer).

## Tests

```bash
.venv/bin/python -m pytest -q
PYTHONPATH=<copia de stemforge fuera del repo> .venv/bin/python tools/update_e2e.py -- .venv/bin/python -B -m stemforge.app
```

`tools/update_e2e.py` prueba el actualizador de punta a punta con una release falsa servida desde archivos
locales; el workflow de Windows lo ejecuta sobre la copia instalada (actualización pequeña y completa).

La interfaz de la app en Mac es WebKit: los cambios visuales conviene revisarlos en una ventana de pywebview
(o Safari), no solo en Chrome.
