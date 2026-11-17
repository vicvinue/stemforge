#!/bin/zsh
# Instala StemForge (Apple Silicon). Requiere Homebrew.
set -e
cd "$(dirname "$0")"
[[ "$(uname -m)" == "arm64" ]] || { echo "StemForge requiere un Mac con Apple Silicon."; exit 1; }
command -v brew >/dev/null || { echo "Instala Homebrew: https://brew.sh"; exit 1; }
command -v ffmpeg >/dev/null || brew install ffmpeg
command -v uv >/dev/null || brew install uv
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
./make_app.sh
echo "✅ Listo. Abre StemForge.app o ejecuta ./run.sh"
