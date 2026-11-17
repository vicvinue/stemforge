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
            except Exception:
                pass
            webview.create_window("StemForge", url, width=1180, height=820, min_size=(860, 600))
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
