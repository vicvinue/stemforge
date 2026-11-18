"""Lo que cambia entre sistemas: carpetas de datos, abrir carpetas y el selector de carpetas."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

APP_NAME = "StemForge"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Selector de carpetas de la ventana nativa (lo registra app.py en Windows/Linux).
FolderPicker = Callable[[str], "str | None"]
_folder_picker: FolderPicker | None = None


def set_folder_picker(picker: FolderPicker | None) -> None:
    global _folder_picker
    _folder_picker = picker


# ------------------------------------------------------------------------- rutas
def support_dir() -> Path:
    """Carpeta de datos (modelos, ajustes, temporales)."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


def log_file() -> Path:
    if IS_MAC:
        return Path.home() / "Library" / "Logs" / f"{APP_NAME}.log"
    return support_dir() / "logs" / f"{APP_NAME}.log"


def music_dir() -> Path:
    if IS_WINDOWS:
        found = _windows_music_dir()
        if found is not None:
            return found
    return Path.home() / "Music"


def _windows_music_dir() -> Path | None:
    """Carpeta «Música» real (puede estar redirigida, p. ej. a OneDrive)."""
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        folder_id = GUID.from_buffer_copy(uuid.UUID("4BD8D571-6D19-48D3-BE97-422220080E43").bytes_le)
        ptr = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(ptr)) != 0:
            return None
        try:
            return Path(ptr.value) if ptr.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(ptr)
    except Exception:
        return None


# ---------------------------------------------------------------------- acciones
def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def open_folder(path: str | Path) -> bool:
    """Abre la carpeta en el Finder / Explorador de archivos."""
    target = str(path)
    try:
        if IS_WINDOWS:
            os.startfile(target)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.run(["open", target], check=False)
        else:
            subprocess.run(["xdg-open", target], check=False)
        return True
    except OSError:
        return False


def choose_folder(prompt: str, initial: str | None = None) -> str | None:
    """Muestra el selector nativo de carpetas. Devuelve la ruta elegida o None si se cancela."""
    if _folder_picker is not None:
        try:
            return _folder_picker(initial or "") or None
        except Exception:
            pass  # sigue con el selector del sistema
    try:
        if IS_MAC:
            return _choose_folder_macos(prompt)
        if IS_WINDOWS:
            return _choose_folder_windows(prompt, initial)
        return _choose_folder_linux(prompt, initial)
    except (OSError, subprocess.SubprocessError):
        return None


def _choose_folder_macos(prompt: str) -> str | None:
    script = f'POSIX path of (choose folder with prompt "{prompt.replace(chr(34), "")}")'
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _choose_folder_windows(prompt: str, initial: str | None) -> str | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description = {_ps_quote(prompt)};"
        f"$d.SelectedPath = {_ps_quote(initial or '')};"
        "$o = New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
        "if ($d.ShowDialog($o) -eq [System.Windows.Forms.DialogResult]::OK) {"
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::Write($d.SelectedPath) }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, creationflags=_no_window(),
    )
    path = proc.stdout.decode("utf-8", errors="replace").strip()
    return path or None


def _choose_folder_linux(prompt: str, initial: str | None) -> str | None:
    args = ["zenity", "--file-selection", "--directory", f"--title={prompt}"]
    if initial:
        args.append(f"--filename={initial.rstrip('/')}/")
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.stdout.strip() or None if proc.returncode == 0 else None
