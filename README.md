# StemForge

**Versión 0.3.0** · por [vicvinue](https://github.com/vicvinue) · Licencia MIT

Separador de stems para **macOS con Apple Silicon** (M1/M2/M3/M4) y **Windows 10/11 (x64)**.
En el Mac usa la GPU (PyTorch **MPS / Metal**). En Windows hay dos instaladores: uno para **GPU NVIDIA (CUDA)**
y otro, más liviano, que usa la CPU.

![StemForge: cola de trabajos con una canción separándose y otra lista](docs/screenshots/cola.png)

<p align="center"><em>Cola de trabajos: elige el modo a la izquierda y sigue el progreso de cada canción.</em></p>

![StemForge: mezclador con las pistas separadas](docs/screenshots/mezclador.png)

<p align="center"><em>Mezclador integrado: escucha los stems sincronizados con mute, solo y volumen por pista.</em></p>

<sub>Capturas hechas con una pista de demostración sintética (batería, bajo y acordes generados + voz de texto a voz de macOS).</sub>

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

Los archivos se guardan en `~/Music/StemForge/<Canción> [<Modo>]/<Canción> - <Stem>.wav` (en Windows,
`Música\StemForge\…`) junto a un `stemforge.json` con los modelos y ajustes usados.

## App autónoma para macOS (recomendado)

```bash
./build_app.sh          # crea dist/StemForge.app y dist/StemForge-<versión>.dmg
```

Abre el `.dmg` y arrastra **StemForge** a Aplicaciones. La app incluye su propio Python, todas las
dependencias y un ffmpeg estático: no necesita esta carpeta, Homebrew ni un Python instalado. Pesa ≈ 1,4 GB
(650 MB el DMG). Los modelos no van dentro: se descargan solos la primera vez que se usan.

- Registro: `~/Library/Logs/StemForge.log`
- CLI incluida: `/Applications/StemForge.app/Contents/Resources/stemforge cancion.mp3 -m stems4`
- Está firmada ad-hoc (no notarizada): en este Mac abre directamente. Si la copias a otro Mac, la primera vez
  ábrela con clic derecho → Abrir.

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File build_windows.ps1          # PyTorch CPU
powershell -ExecutionPolicy Bypass -File build_windows.ps1 -Cuda    # PyTorch CUDA (GPU NVIDIA)
```

Crea `dist\StemForge\` (carpeta portable: `Abrir StemForge.cmd`) y, si está
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`),
`dist\StemForge-<versión>-Setup.exe`. El instalador no pide administrador: instala en
`%LOCALAPPDATA%\Programs\StemForge`, crea el acceso en el menú Inicio y al desinstalar pregunta si
borrar también los modelos. Incluye su propio Python, las dependencias y ffmpeg.

- Requiere Windows 10 1809+ x64 con Microsoft Edge WebView2 (viene con Windows 11 y Windows 10 al día);
  sin WebView2 se abre en el navegador.
- **GPU**: la versión normal usa la CPU (los Roformer van varias veces más lentos que en un Mac M1).
  Con `-Cuda` (PyTorch con CUDA 13) crea `StemForge-<versión>-CUDA-Setup.exe` + archivos `.bin`, que deben
  estar en la misma carpeta al instalar. Ver [GPU NVIDIA compatibles](#gpu-nvidia-compatibles-windows).
  AMD/Intel no se aceleran.
- Datos y modelos: `%LOCALAPPDATA%\StemForge` · registro: `%LOCALAPPDATA%\StemForge\logs\StemForge.log`
- CLI incluida: `stemforge.cmd cancion.mp3 -m stems4` en la carpeta de instalación.
- No está firmado: SmartScreen avisa la primera vez (Más información → Ejecutar de todas formas).
- El workflow `.github/workflows/windows.yml` (manual o al publicar un tag `v*`) compila, separa audio
  real en una máquina Windows, prueba el instalador y deja el `Setup.exe` como artefacto.

### GPU NVIDIA compatibles (Windows)

La variante CUDA (`StemForge-<versión>-CUDA-Setup.exe`) usa PyTorch con CUDA 13. Las librerías de CUDA
vienen incluidas: **solo hace falta el driver de NVIDIA** (serie 580 o posterior), sin instalar el CUDA Toolkit.

| GPU | ¿Se acelera? |
|---|---|
| GeForce RTX 50xx (Blackwell) | ✅ Sí |
| GeForce RTX 40xx (Ada Lovelace) | ✅ Sí |
| GeForce RTX 30xx (Ampere) | ✅ Sí |
| GeForce RTX 20xx y GTX 16xx (Turing, p. ej. GTX 1650/1660) | ✅ Sí |
| Profesionales: Quadro RTX, RTX A-series, RTX Ada, RTX PRO | ✅ Sí |
| GeForce GTX 10xx (Pascal), GTX 9xx (Maxwell) y anteriores, Titan V | ❌ No: CUDA 13 ya no las soporta; la app usa la CPU |
| AMD Radeon, Intel Arc / gráficos integrados | ❌ No: la app usa la CPU |

- Con varias NVIDIA usa la primera. Para elegir otra, define la variable de entorno `CUDA_VISIBLE_DEVICES`
  (p. ej. `1`) antes de abrir StemForge.
- La interfaz indica qué está pasando: «GPU NVIDIA (CUDA) ✓» si la usa; «CPU · versión sin CUDA» si hay una
  NVIDIA pero se instaló la variante CPU; «CPU · GPU NVIDIA no disponible» si el driver es antiguo o la GPU
  no es compatible (pasa el ratón por encima para ver el motivo).
- En una PC sin NVIDIA compatible conviene la variante normal (CPU): pesa ≈ 270 MB en vez de ≈ 3 GB.

## Actualizaciones automáticas

StemForge busca versiones nuevas en las releases de GitHub al abrirse (se puede desactivar con la casilla
«al abrir» del pie de la ventana) o con el botón **Buscar actualizaciones**. Si hay una, aparece un aviso
con **Actualizar**: descarga, verifica el SHA-256 y, con un clic en **Reiniciar ahora**, queda aplicada.

- **Actualización pequeña** (lo habitual, ≈ 0,3 MB): cuando la versión nueva solo cambia el código de
  StemForge, se descarga solo ese código a la carpeta de datos (`…/StemForge/updates/`) y se usa desde ahí.
  La instalación no se modifica (en el Mac la firma de la app sigue intacta). Si la versión nueva no llegara
  a arrancar, la siguiente vez se abre la instalada y se ofrece el instalador completo.
- **Actualización completa**: cuando cambian Python o las dependencias, se descarga el instalador de tu
  plataforma (DMG, `Setup.exe` normal o la variante CUDA, según lo que tengas instalado). La app se cierra,
  se instala sola y vuelve a abrirse. En el Mac reemplaza `StemForge.app` en su carpeta (si no tiene permiso
  de escritura, abre el DMG para arrastrarla).
- **Copia de desarrollo** (git): `git pull` en la rama `main` (y reinstala dependencias con `uv` si
  cambiaron). Si hay cambios sin guardar, avisa y no toca nada.
- La carpeta portable de Windows no se actualiza sola: el aviso enlaza a la release.
- No se instala nada mientras haya separaciones en curso.

Las versiones 0.2.x no traen el actualizador: hay que instalar la 0.3.0 a mano una vez.

### Publicar una versión

1. Sube `__version__` en `stemforge/__init__.py` y `version` en `pyproject.toml`. Si cambiaste dependencias
   o la versión de Python, sube también `RUNTIME` (el test `test_runtime_bumped_when_dependencies_change`
   lo recuerda): así las instalaciones existentes reciben el instalador completo en vez del código solo.
2. `./build_app.sh` (DMG) y un tag `vX.Y.Z` en GitHub: el workflow de Windows compila los dos `Setup.exe`.
   Copia a `dist/` el DMG y los instaladores de Windows (`gh run download <id>`).
3. `.venv/bin/python tools/make_update_assets.py` crea `dist/stemforge-app-X.Y.Z.zip` y `dist/latest.json`.
4. `gh release create vX.Y.Z` con **todos** los archivos que lista el paso 3. La app consulta
   `releases/latest/download/latest.json`, así que la release debe quedar marcada como «Latest».

## Instalación para desarrollo

macOS:

```bash
./setup.sh          # instala ffmpeg/uv si faltan y crea .venv (Python 3.12)
```

Luego ejecuta `./run.sh` (`./run.sh --browser` para usar el navegador).

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1    # instala uv si falta, crea .venv; CUDA si hay NVIDIA
.\run.bat                                             # .\run.bat --browser para usar el navegador
```

Los modelos se descargan solos la primera vez que se usan (≈ 0,5–0,7 GB cada Roformer) en
`~/Library/Application Support/StemForge/models` (Mac) o `%LOCALAPPDATA%\StemForge\models` (Windows).

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

## Créditos y licencias

El código de StemForge se publica bajo licencia [MIT](LICENSE).

- [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) (MIT) — motor de inferencia de modelos UVR.
- [Demucs](https://github.com/facebookresearch/demucs) (MIT) — Meta AI.
- [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) (MIT) — modelos MDX/VR.
- Pesos de modelos: BS-Roformer (viperx), MelBand Roformer (Kimberley Jensen), MelBand Big Beta 4 (unwa),
  BS-Roformer (Gabox), BS-Roformer SW (jarredou), MDX23C DrumSep (aufr33 & jarredou).
  Cada modelo tiene su propia licencia; revísalas antes de cualquier uso que no sea personal.
