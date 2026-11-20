#!/bin/zsh
# Empaqueta StemForge como app autónoma para macOS Apple Silicon:
#   dist/StemForge.app            (Python + dependencias + ffmpeg incluidos)
#   dist/StemForge-<versión>.dmg  (para instalar arrastrando a Aplicaciones)
#
# La app no depende de esta carpeta, de Homebrew ni de un Python del sistema.
# Los modelos NO se incluyen: se descargan solos la primera vez en
# ~/Library/Application Support/StemForge/models.
#
# Uso: ./build_app.sh [--no-dmg]
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
[[ "$(uname -m)" == "arm64" ]] || { echo "Solo Apple Silicon."; exit 1; }
command -v uv >/dev/null || { echo "Falta uv: brew install uv"; exit 1; }

PYVER="3.12"
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | /usr/bin/head -1)
DIST="$ROOT/dist"
APP="$DIST/StemForge.app"
RES="$APP/Contents/Resources"
PY="$RES/python"

echo "==> StemForge $VERSION"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"

echo "==> Python $PYVER portable (python-build-standalone vía uv)"
uv python install "$PYVER" >/dev/null
SRC_PY="$(uv python find --managed-python "$PYVER")"
SRC_DIR="$(cd "$(dirname "$SRC_PY")/.." && pwd -P)"
cp -R "$SRC_DIR" "$PY"
rm -f "$PY/lib/python$PYVER/EXTERNALLY-MANAGED"
rm -rf "$PY/lib/python$PYVER/test" "$PY/lib/python$PYVER/idlelib" "$PY/lib/python$PYVER/tkinter" \
       "$PY/lib/python$PYVER/turtledemo" "$PY/share"

echo "==> Dependencias"
uv pip install --python "$PY/bin/python3" --no-cache --compile-bytecode "$ROOT" >/dev/null

echo "==> Limpieza"
SITE="$PY/lib/python$PYVER/site-packages"
rm -rf "$SITE/torch/include" "$SITE/torch/share/cmake"
find "$PY" -name "*.a" -delete
# Los scripts de bin/ tienen la ruta absoluta del build en el shebang: se reemplazan por wrappers.
find "$PY/bin" -type f ! -name "python*" -delete
find "$PY/bin" -type l ! -exec test -e {} \; -delete   # enlaces que apuntaban a esos scripts
rm -f "$SITE"/stemforge-*.dist-info/direct_url.json   # ruta del build: no se necesita

echo "==> Bytecode"
# Todo precompilado y validado por hash (no por fecha): la app nunca necesita escribir .pyc
# dentro del bundle, lo que rompería la firma («a sealed resource is missing or invalid»).
# -B: el propio compileall no debe dejar .pyc por fecha de los módulos que importa al arrancar.
# Los lanzadores usan -I -B (con -I se ignora PYTHONDONTWRITEBYTECODE).
find "$PY" -name "__pycache__" -type d -prune -exec rm -rf {} +
"$PY/bin/python3" -I -B -m compileall -q -f -j 0 --invalidation-mode unchecked-hash "$PY/lib" >/dev/null 2>&1 || true

echo "==> Lanzadores"
cat > "$APP/Contents/MacOS/StemForge" <<'SH'
#!/bin/bash
# Lanzador de StemForge.app: usa el Python incluido, aislado del entorno del usuario.
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONNOUSERSITE=1
mkdir -p "$HOME/Library/Logs"
exec "$APP_DIR/Resources/python/bin/python3" -I -B -m stemforge.app "$@" >> "$HOME/Library/Logs/StemForge.log" 2>&1
SH
cat > "$RES/stemforge" <<'SH'
#!/bin/bash
# CLI incluida: StemForge.app/Contents/Resources/stemforge cancion.mp3 -m stems4
RES_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONNOUSERSITE=1
exec "$RES_DIR/python/bin/python3" -I -B -m stemforge "$@"
SH
chmod +x "$APP/Contents/MacOS/StemForge" "$RES/stemforge"
cp "$ROOT/stemforge/web/StemForge.icns" "$RES/StemForge.icns"

cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>StemForge</string>
  <key>CFBundleDisplayName</key><string>StemForge</string>
  <key>CFBundleIdentifier</key><string>local.stemforge.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>StemForge</string>
  <key>CFBundleIconFile</key><string>StemForge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>LSRequiresNativeExecution</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>© 2026 vicvinue · Todos los derechos reservados</string>
  <key>NSAppleEventsUsageDescription</key><string>StemForge usa el selector de carpetas de macOS.</string>
</dict></plist>
PL

echo "==> Firma ad-hoc"
codesign --force --deep --sign - "$APP" 2>/dev/null || codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP" && echo "    firma OK"

echo "==> Tamaño: $(du -sh "$APP" | cut -f1)"

if [[ "${1:-}" != "--no-dmg" ]]; then
  echo "==> DMG"
  STAGE="$(mktemp -d)"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  DMG="$DIST/StemForge-$VERSION.dmg"
  rm -f "$DMG"
  hdiutil create -volname "StemForge" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  rm -rf "$STAGE"
  echo "    $DMG ($(du -sh "$DMG" | cut -f1))"
fi
echo "✅ Listo: $APP"
