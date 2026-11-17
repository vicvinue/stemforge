#!/bin/zsh
# Crea StemForge.app (lanzador que usa el entorno .venv de esta carpeta).
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
APP="$ROOT/StemForge.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/StemForge" <<SH
#!/bin/zsh
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m stemforge.app >> "\$HOME/Library/Logs/StemForge.log" 2>&1
SH
chmod +x "$APP/Contents/MacOS/StemForge"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>StemForge</string>
  <key>CFBundleDisplayName</key><string>StemForge</string>
  <key>CFBundleIdentifier</key><string>local.stemforge.app</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key><string>StemForge</string>
  <key>CFBundleIconFile</key><string>StemForge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PL
# Icono generado
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python - "$APP/Contents/Resources" <<'PY' || true
import sys, subprocess, tempfile, os
from pathlib import Path
res = Path(sys.argv[1])
svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#7c5cff"/><path d="M7 20v-8M11 23V9M15 19v-6M19 25V7M23 21v-10M27 17v-2" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>'''
d = Path(tempfile.mkdtemp())
(d / "i.svg").write_text(svg)
subprocess.run(["qlmanage", "-t", "-s", "1024", "-o", str(d), str(d / "i.svg")], capture_output=True)
png = d / "i.svg.png"
if png.exists():
    iconset = d / "StemForge.iconset"; iconset.mkdir()
    for s in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{s}x{s}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(["sips", "-z", str(s*scale), str(s*scale), str(png), "--out", str(iconset / name)], capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(res / "StemForge.icns")], capture_output=True)
PY
fi
touch "$APP"
echo "Creado $APP"
