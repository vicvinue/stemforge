"""Lanzador de escritorio: servidor local + ventana nativa (WebKit / Edge WebView2) o navegador."""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.request
import webbrowser


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.15)
    raise RuntimeError("El servidor no arrancó a tiempo")


def _ensure_output_streams() -> None:
    """Sin consola (pythonw.exe en Windows) stdout/stderr son None: se mandan a un archivo de registro.

    Sin esto, tqdm y el logging de uvicorn fallan al escribir.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    from . import osutil

    try:
        log = osutil.log_file()
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = open(log, "a", encoding="utf-8", buffering=1)
    except OSError:
        import os

        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


WINDOWS_APP_ID = "vicvinue.StemForge"  # el mismo AppUserModelID que el acceso directo del instalador


def _windows_branding() -> None:
    """Agrupa la ventana en la barra de tareas como «StemForge» (con su icono) y no como Python."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:
        pass


def _macos_branding() -> None:
    """Nombre «StemForge» en la barra de menú e icono en el Dock (en vez de «Python»)."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
    except Exception:
        return
    from . import __version__

    try:
        info = NSBundle.mainBundle().localizedInfoDictionary() or NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "StemForge"
            info["CFBundleDisplayName"] = "StemForge"
            info["CFBundleShortVersionString"] = __version__
            info["CFBundleVersion"] = __version__
            info["NSHumanReadableCopyright"] = COPYRIGHT
    except Exception:
        pass
    icon = _find_icon()
    if icon:
        try:
            image = NSImage.alloc().initWithContentsOfFile_(str(icon))
            if image is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception:
            pass


AUTHOR_URL = "https://github.com/vicvinue"
REPO_URL = "https://github.com/vicvinue/stemforge"
COPYRIGHT = "© 2026 vicvinue · Licencia MIT"

_about_target = None  # referencia fuerte: el menú no retiene su target


def _credits():
    """Texto del panel «Acerca de»: lo mismo que el footer (autor + GitHub)."""
    from AppKit import (
        NSCenterTextAlignment,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSLinkAttributeName,
        NSMutableAttributedString,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
    )
    from Foundation import NSAttributedString, NSURL

    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSCenterTextAlignment)
    para.setParagraphSpacing_(4)
    base = {
        NSFontAttributeName: NSFont.systemFontOfSize_(11),
        NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
        NSParagraphStyleAttributeName: para,
    }
    out = NSMutableAttributedString.alloc().init()

    def add(text, link=None):
        attrs = dict(base)
        if link:
            attrs[NSLinkAttributeName] = NSURL.URLWithString_(link)
        out.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(text, attrs))

    add("Separador de stems para macOS con Apple Silicon.\n")
    add("Por ")
    add("vicvinue", AUTHOR_URL)
    add(" · ")
    add("github.com/vicvinue/stemforge", REPO_URL)
    return out


def _install_about_panel() -> None:
    """Reemplaza el «Acerca de StemForge» de pywebview por un panel con versión, autor y enlaces.

    Se llama en el hilo principal una vez que pywebview creó el menú.
    """
    global _about_target
    try:
        import objc
        from AppKit import NSApplication, NSImage
        from Foundation import NSObject

        from . import __version__
    except Exception:
        return

    class _AboutTarget(NSObject):
        @objc.typedSelector(b"v@:@")
        def showAbout_(self, sender):
            app = NSApplication.sharedApplication()
            opts = {
                "ApplicationName": "StemForge",
                "ApplicationVersion": __version__,
                "Version": "",  # vacío: sin «(0.1.0)» repetido
                "Copyright": COPYRIGHT,
                "Credits": _credits(),
            }
            icon = _find_icon()
            if icon:
                image = NSImage.alloc().initWithContentsOfFile_(str(icon))
                if image is not None:
                    opts["ApplicationIcon"] = image
            app.activateIgnoringOtherApps_(True)
            app.orderFrontStandardAboutPanelWithOptions_(opts)

    try:
        menu = NSApplication.sharedApplication().mainMenu()
        app_menu = menu.itemAtIndex_(0).submenu() if menu and menu.numberOfItems() else None
        if app_menu is None:
            return
        for i in range(app_menu.numberOfItems()):
            item = app_menu.itemAtIndex_(i)
            if item.action() == "orderFrontStandardAboutPanel:":
                _about_target = _AboutTarget.alloc().init()
                item.setTarget_(_about_target)
                item.setAction_("showAbout:")
                break
    except Exception as exc:
        print(f"No se pudo personalizar «Acerca de»: {exc}")


def _find_icon():
    from pathlib import Path

    here = Path(__file__).resolve()
    if sys.platform == "win32":
        ico = here.parent / "web" / "StemForge.ico"
        return ico if ico.is_file() else None
    candidates = [here.parent / "web" / "StemForge.icns"]
    # Dentro del .app: Contents/Resources/StemForge.icns
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            candidates.insert(0, parent / "Contents" / "Resources" / "StemForge.icns")
            break
    return next((c for c in candidates if c.is_file()), None)


def _register_folder_picker(webview, window) -> None:
    """El selector de carpetas usa el diálogo de la propia ventana (queda delante de ella)."""
    from . import osutil

    folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
    if folder is None:
        folder = getattr(webview, "FOLDER_DIALOG", None)
    if folder is None:
        return

    def pick(initial: str) -> str | None:
        result = window.create_file_dialog(folder, directory=initial)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]

    osutil.set_folder_picker(pick)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stemforge-app")
    ap.add_argument("--browser", action="store_true", help="Abrir en el navegador en vez de ventana nativa")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)
    _ensure_output_streams()

    import uvicorn

    from .server import app  # carga modelos de config, crea cola

    port = args.port or _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    _wait_ready(url)

    if not args.browser:
        try:
            import webview

            try:
                webview.settings["ALLOW_DOWNLOADS"] = True  # botón ZIP
                webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True  # enlaces target=_blank -> navegador
            except Exception:
                pass
            if sys.platform == "darwin":
                _macos_branding()
            elif sys.platform == "win32":
                _windows_branding()
            window = webview.create_window("StemForge", url, width=1180, height=820, min_size=(860, 600))
            if sys.platform != "darwin":  # en Mac se mantiene el selector de AppleScript
                _register_folder_picker(webview, window)

            def _on_shown():
                try:
                    from PyObjCTools import AppHelper

                    AppHelper.callAfter(_install_about_panel)
                except Exception:
                    pass

            if sys.platform == "darwin":
                window.events.shown += _on_shown
            icon = _find_icon() if sys.platform == "win32" else None
            if icon:
                webview.start(icon=str(icon))
            else:
                webview.start()
            server.should_exit = True
            return 0
        except Exception as exc:  # sin pywebview → navegador
            print(f"Ventana nativa no disponible ({exc}); abriendo navegador…")

    print(f"StemForge en {url}  (Ctrl+C para salir)")
    webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
