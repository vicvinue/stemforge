@echo off
rem Abre StemForge en Windows (ventana nativa). "run.bat --browser" lo abre en el navegador.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -X utf8 -m stemforge.app %*
