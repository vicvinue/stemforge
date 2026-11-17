#!/bin/zsh
# Abre StemForge (ventana nativa). Usa --browser para abrir en el navegador.
cd "$(dirname "$0")"
exec .venv/bin/python -m stemforge.app "$@"
