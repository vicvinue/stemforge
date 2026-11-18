"""Prueba de punta a punta del actualizador con una release falsa «9.9.9» servida desde archivos locales.

Arranca StemForge (--browser, puerto fijo) con STEMFORGE_HOME y STEMFORGE_UPDATE_URL temporales y,
por la API como lo haría la interfaz: buscar → descargar → aplicar. Luego comprueba el resultado.

  --mode app   actualización pequeña: la app debe volver a abrirse sola, ya con la versión 9.9.9
  --mode full  actualización completa (Windows, instalación con Setup): el instalador indicado en
               --setup se ejecuta en silencio y vuelve a abrir StemForge desde la carpeta instalada

Uso:  python tools/update_e2e.py --mode app [--port 8790] -- <comando que arranca StemForge>
      (al comando se le agregan «--browser --port N»)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_update_assets  # noqa: E402


def http(port: int, path: str, token: str | None = None, method: str = "GET", timeout: float = 30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 headers={"x-stemforge-token": token} if token else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body) if path.startswith("/api/") else body


def wait_server(port: int, seconds: float) -> str:
    """Espera a que responda la página y devuelve el token de la sesión."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            html = http(port, "/", timeout=3)
            return re.search(r'TOKEN = "([^"]+)"', html).group(1)
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"StemForge no respondió en el puerto {port} tras {seconds:.0f} s")


def wait_exit(proc: subprocess.Popen, seconds: float) -> None:
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise SystemExit("La app no se cerró para aplicar la actualización")


def kill_port(port: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
                        "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"], check=False)
    else:
        pids = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        for pid in pids.split():
            subprocess.run(["kill", pid], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["app", "full"], default="app")
    ap.add_argument("--setup", type=Path, help="Setup.exe a usar como actualización completa (--mode full)")
    ap.add_argument("--install-dir", type=Path, help="carpeta instalada que debe volver a abrirse (--mode full)")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("launch", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    launch = [a for a in args.launch if a != "--"]
    if not launch:
        ap.error("falta el comando que arranca StemForge")

    work = Path(tempfile.mkdtemp(prefix="stemforge-e2e-"))
    dist, home = work / "dist", work / "home"
    dist.mkdir()
    make_update_assets.main(["--dist", str(dist), "--base-url", dist.resolve().as_uri()])
    manifest = json.loads((dist / "latest.json").read_text(encoding="utf-8"))
    manifest["version"] = "9.9.9"
    if args.mode == "full":
        if not args.setup:
            ap.error("--mode full necesita --setup")
        target = dist / "StemForge-9.9.9-Setup.exe"
        shutil.copy2(args.setup, target)
        asset = make_update_assets.asset(target, dist.resolve().as_uri())
        manifest["runtime"] = 999                              # fuerza la actualización completa
        manifest["full"] = {"win-cpu": [asset], "win-cuda": [asset], "mac-arm64": [asset]}
    (dist / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")

    env = {**os.environ, "STEMFORGE_HOME": str(home), "STEMFORGE_UPDATE_URL": (dist / "latest.json").resolve().as_uri(),
           "BROWSER": "true" if sys.platform != "win32" else os.environ.get("BROWSER", "")}
    cmd = [*launch, "--browser", "--port", str(args.port)]
    print("==> Arrancando:", " ".join(cmd))
    proc = subprocess.Popen(cmd, env=env, cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        token = wait_server(args.port, 120)
        before = http(args.port, "/api/info", token)["version"]
        st = http(args.port, "/api/update/check?force=true", token, "POST")
        print(f"    instalada {before} · ofrece {st['latest']} · método {st['method']} · {st['size']} bytes")
        expected = "app" if args.mode == "app" else "full"
        assert st["state"] == "available" and st["method"] == expected, st
        http(args.port, "/api/update/download", token, "POST")
        for _ in range(600):
            st = http(args.port, "/api/update", token)
            if st["state"] != "downloading":
                break
            time.sleep(0.5)
        assert st["state"] == "ready", st
        print("==> Descargada; aplicando")
        st = http(args.port, "/api/update/apply", token, "POST")
        assert st["state"] == "applying", st
        wait_exit(proc, 30)
        print("    la app se cerró")

        if args.mode == "app":
            token = wait_server(args.port, 120)
            info = http(args.port, "/api/info", token)
            upd = http(args.port, "/api/update", token)
            print(f"    volvió a abrirse: versión {info['version']} (instalada {upd['installed']})")
            assert info["version"] == "9.9.9" and upd["installed"] == before, (info["version"], upd)
            cur = json.loads((home / "updates" / "current.json").read_text(encoding="utf-8"))
            assert cur["confirmed"] is True, cur
            kill_port(args.port)
        else:
            exe = str((args.install_dir / "python" / "pythonw.exe").resolve()).lower()
            deadline = time.time() + 300
            found = False
            while time.time() < deadline and not found:
                out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                      "Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                                     capture_output=True, text=True).stdout.lower()
                found = exe in out
                time.sleep(3)
            assert found, f"El instalador no volvió a abrir StemForge ({exe})"
            print("    el instalador terminó y volvió a abrir StemForge")
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force"], check=False)
    finally:
        if proc.poll() is None:
            proc.kill()
    shutil.rmtree(work, ignore_errors=True)
    print(f"✅ Actualización «{args.mode}» de punta a punta superada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
