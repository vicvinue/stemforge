"""Lanzador de escritorio: servidor local + ventana nativa (WebKit) o navegador."""
from __future__ import annotations

import argparse
import socket
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
    """Texto del panel «Acerca de»: lo mismo que el footer (autor + GitHub) y algo de contexto."""
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

    def add(text, link=None, color=None):
        attrs = dict(base)
        if link:
            attrs[NSLinkAttributeName] = NSURL.URLWithString_(link)
        if color:
            attrs[NSForegroundColorAttributeName] = color
        out.appendAttributedString_(NSAttributedString.alloc().initWithString_attributes_(text, attrs))

    add("Separador de stems para macOS con Apple Silicon.\n")
    add("Por ")
    add("vicvinue", AUTHOR_URL)
    add(" · ")
    add("github.com/vicvinue/stemforge", REPO_URL)
    add("\n")
    add(
        "Inspirado en Ultimate Vocal Remover. Usa Demucs y BS/MelBand-Roformer "
        "(audio-separator) en la GPU (Metal).",
        color=NSColor.tertiaryLabelColor(),
    )
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
    import sys

    here = Path(__file__).resolve()
    candidates = [here.parent / "web" / "StemForge.icns"]
    # Dentro del .app: Contents/Resources/StemForge.icns
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            candidates.insert(0, parent / "Contents" / "Resources" / "StemForge.icns")
            break
    return next((c for c in candidates if c.is_file()), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stemforge-app")
    ap.add_argument("--browser", action="store_true", help="Abrir en el navegador en vez de ventana nativa")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)

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
            _macos_branding()
            window = webview.create_window("StemForge", url, width=1180, height=820, min_size=(860, 600))

            def _on_shown():
                try:
                    from PyObjCTools import AppHelper

                    AppHelper.callAfter(_install_about_panel)
                except Exception:
                    pass

            window.events.shown += _on_shown
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
