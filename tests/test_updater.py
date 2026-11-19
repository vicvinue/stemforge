"""Tests del actualizador (sin red: los «servidores» son archivos locales file://)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

import stemforge
from stemforge import osutil, updater

ROOT = Path(__file__).resolve().parents[1]

# Huella de las dependencias de pyproject.toml. Si este test falla: cambiaste dependencias o la
# versión de Python → sube RUNTIME en stemforge/__init__.py y copia aquí la huella nueva.
RUNTIME_FINGERPRINT = {1: "d014d90736bd4689"}


def _deps_fingerprint() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    blob = json.dumps({"python": data["requires-python"], "deps": sorted(data["dependencies"])})
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def test_runtime_bumped_when_dependencies_change():
    fp = _deps_fingerprint()
    assert RUNTIME_FINGERPRINT.get(stemforge.RUNTIME) == fp, (
        f"Las dependencias cambiaron (huella {fp}): sube RUNTIME en stemforge/__init__.py "
        f"y registra {{{stemforge.RUNTIME + 1}: '{fp}'}} en RUNTIME_FINGERPRINT")


def test_support_dir_matches_osutil(monkeypatch, tmp_path):
    assert stemforge._support_dir() == osutil.support_dir()
    monkeypatch.setenv("STEMFORGE_HOME", str(tmp_path))
    assert stemforge._support_dir() == osutil.support_dir() == tmp_path


@pytest.mark.parametrize("a,b", [("0.10.0", "0.9.9"), ("1.0", "0.99.99"), ("0.3.1", "0.3.0"), ("2.0.0b1", "1.9")])
def test_vtuple_orders(a, b):
    assert updater.vtuple(a) > updater.vtuple(b)


# ------------------------------------------------------------------- plan
MANIFEST = {
    "version": "0.4.0", "runtime": 1,
    "app": {"name": "stemforge-app-0.4.0.zip", "url": "u", "size": 300_000, "sha256": "x"},
    "full": {"mac-arm64": [{"name": "StemForge-0.4.0.dmg", "url": "u", "size": 690_000_000, "sha256": "x"}],
             "win-cpu": [{"name": "StemForge-0.4.0-Setup.exe", "url": "u", "size": 280_000_000, "sha256": "x"}],
             "win-cuda": [{"name": "StemForge-0.4.0-CUDA-Setup.exe", "url": "u", "size": 5_000_000, "sha256": "x"},
                          {"name": "StemForge-0.4.0-CUDA-Setup-1.bin", "url": "u", "size": 2_000_000_000, "sha256": "x"}]},
}


def test_plan_up_to_date():
    p = updater.plan(MANIFEST, "0.4.0", 1, "mac-app", "mac-arm64")
    assert not p["available"] and p["method"] is None


def test_plan_small_update_when_runtime_matches():
    p = updater.plan(MANIFEST, "0.3.0", 1, "win-installer", "win-cuda")
    assert p["method"] == "app" and p["size"] == 300_000 and [f["name"] for f in p["files"]] == ["stemforge-app-0.4.0.zip"]


@pytest.mark.parametrize("pkey,names", [
    ("mac-arm64", ["StemForge-0.4.0.dmg"]),
    ("win-cpu", ["StemForge-0.4.0-Setup.exe"]),
    ("win-cuda", ["StemForge-0.4.0-CUDA-Setup.exe", "StemForge-0.4.0-CUDA-Setup-1.bin"]),
])
def test_plan_full_update_when_runtime_changes(pkey, names):
    kind = "mac-app" if pkey.startswith("mac") else "win-installer"
    p = updater.plan(MANIFEST, "0.3.0", 0, kind, pkey)
    assert p["method"] == "full" and [f["name"] for f in p["files"]] == names


def test_plan_failed_small_update_falls_back_to_full():
    p = updater.plan(MANIFEST, "0.3.0", 1, "mac-app", "mac-arm64", failed={"0.4.0"})
    assert p["method"] == "full"


def test_plan_git_and_manual():
    assert updater.plan(MANIFEST, "0.3.0", 1, "git", "mac-arm64")["method"] == "git"
    assert updater.plan(MANIFEST, "0.3.0", 0, "win-portable", "win-cpu")["method"] == "manual"
    assert updater.plan(MANIFEST, "0.3.0", 0, "python", None)["method"] == "manual"


# ---------------------------------------------------------- arranque con overlay
def _overlay(base: Path, version: str, runtime: int = 1, confirmed: bool = False) -> Path:
    pkg = base / version / "stemforge"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (base / "current.json").write_text(json.dumps({"version": version, "runtime": runtime, "confirmed": confirmed}))
    return pkg


def test_overlay_used_only_if_newer_and_same_runtime(tmp_path):
    assert stemforge._find_overlay(tmp_path, "0.3.0", 1) is None
    pkg = _overlay(tmp_path, "0.3.1", confirmed=True)
    assert stemforge._find_overlay(tmp_path, "0.3.0", 1) == ("0.3.1", pkg)
    assert stemforge._find_overlay(tmp_path, "0.3.1", 1) is None      # la instalada ya es igual
    assert stemforge._find_overlay(tmp_path, "0.3.0", 2) is None      # otro runtime


def test_overlay_that_failed_to_boot_is_skipped(tmp_path):
    _overlay(tmp_path, "0.3.1")
    assert stemforge._find_overlay(tmp_path, "0.3.0", 1) is not None  # primer intento: deja la marca
    assert (tmp_path / "trial-boot").exists()
    assert stemforge._find_overlay(tmp_path, "0.3.0", 1) is None      # no confirmó: vuelve a la instalada


def test_overlay_end_to_end_in_fresh_interpreter(tmp_path):
    """Instalación sin .git + actualización pequeña: el paquete se carga desde la actualización."""
    site = tmp_path / "site"
    shutil.copytree(ROOT / "stemforge", site / "stemforge", ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "home"
    pkg = _overlay(home / "updates", "9.9.9")
    shutil.copytree(ROOT / "stemforge", pkg, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (pkg / "presets.py").write_text((pkg / "presets.py").read_text() + "\nOVERLAY_MARK = True\n")
    env = {**os.environ, "STEMFORGE_HOME": str(home), "PYTHONPATH": str(site)}
    env.pop("STEMFORGE_NO_UPDATES", None)
    code = ("import stemforge, stemforge.presets as p; "
            "print(stemforge.__version__, stemforge.BUNDLED_VERSION, getattr(p, 'OVERLAY_MARK', False))")

    def run():
        return subprocess.run([sys.executable, "-B", "-c", code], env=env, capture_output=True, text=True,
                              cwd=tmp_path, check=True).stdout.split()

    assert run() == ["9.9.9", stemforge.BUNDLED_VERSION, "True"]           # 1.er arranque (de prueba)
    assert run() == [stemforge.BUNDLED_VERSION, stemforge.BUNDLED_VERSION, "False"]  # no confirmó → instalada
    data = json.loads((home / "updates" / "current.json").read_text())
    (home / "updates" / "current.json").write_text(json.dumps({**data, "confirmed": True}))
    assert run()[0] == "9.9.9"                                              # confirmada → siempre


# ------------------------------------------------------------- descargas
def _asset(path: Path, **kw) -> dict:
    return {"name": path.name, "url": path.resolve().as_uri(), "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **kw}


def test_download_verifies_sha256(tmp_path):
    src = tmp_path / "srv" / "f.bin"
    src.parent.mkdir()
    src.write_bytes(b"x" * 3000)
    seen = []
    out = updater.download(_asset(src), tmp_path / "dl", seen.append)
    assert out.read_bytes() == src.read_bytes() and sum(seen) == 3000
    with pytest.raises(ValueError, match="SHA-256"):
        updater.download(_asset(src, sha256="0" * 64), tmp_path / "dl2")
    assert not list((tmp_path / "dl2").iterdir())          # no deja archivos a medias


def test_extract_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMFORGE_HOME", str(tmp_path / "home"))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("stemforge/__init__.py", "")
        zf.writestr("../../escape.py", "x")
    with pytest.raises(ValueError, match="no permitida"):
        updater.extract_app(bad, "9.9.9")
    assert not (tmp_path / "escape.py").exists()


def test_make_update_assets_and_full_small_update_flow(tmp_path, monkeypatch):
    """Release simulada: tools/make_update_assets.py → latest.json → buscar → descargar → listo."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import make_update_assets
    finally:
        sys.path.pop(0)
    dist = tmp_path / "dist"
    dist.mkdir()
    ver = stemforge.BUNDLED_VERSION
    (dist / f"StemForge-{ver}-Setup.exe").write_bytes(b"setup")
    files = make_update_assets.main(["--dist", str(dist), "--base-url", dist.resolve().as_uri()])
    manifest = json.loads((dist / "latest.json").read_text())
    assert manifest["version"] == ver and manifest["runtime"] == stemforge.RUNTIME
    assert set(manifest["full"]) == {"win-cpu"} and len(files) == 3
    with zipfile.ZipFile(dist / f"stemforge-app-{ver}.zip") as zf:
        names = zf.namelist()
    assert "stemforge/__init__.py" in names and "stemforge/web/index.html" in names
    assert not any("__pycache__" in n for n in names)

    # Se anuncia como versión más nueva para que la instalación actual la ofrezca.
    manifest["version"] = "99.0.0"
    (dist / "latest.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("STEMFORGE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STEMFORGE_UPDATE_URL", (dist / "latest.json").resolve().as_uri())
    monkeypatch.setattr(updater, "install_kind", lambda: "python")
    up = updater.Updater()
    st = up.check(force=True)
    assert st["state"] == "available" and st["method"] == "app" and st["latest"] == "99.0.0"
    up.start_download()
    for _ in range(200):
        if up.snapshot()["state"] != "downloading":
            break
        import time
        time.sleep(0.02)
    assert up.snapshot()["state"] == "ready", up.snapshot()
    base = tmp_path / "home" / "updates"
    assert (base / "99.0.0" / "stemforge" / "updater.py").is_file()
    assert json.loads((base / "current.json").read_text()) == {"version": "99.0.0", "runtime": stemforge.RUNTIME,
                                                                "confirmed": False}
    assert stemforge._find_overlay(base, ver, stemforge.RUNTIME, mark_trial=False)[0] == "99.0.0"


def test_housekeeping_marks_failed_update(tmp_path, monkeypatch):
    monkeypatch.setenv("STEMFORGE_HOME", str(tmp_path))
    base = tmp_path / "updates"
    _overlay(base, "99.0.0")
    (base / "trial-boot").write_text("99.0.0")       # arrancó con ella y no confirmó
    (base / "0.0.1").mkdir()                           # versión vieja
    updater.housekeeping()
    assert "99.0.0" in json.loads((base / "state.json").read_text())["failed"]
    assert not (base / "current.json").exists() and not (base / "0.0.1").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="solo macOS")
def test_mac_full_update_swaps_bundle_from_dmg(tmp_path):
    """El script de actualización completa reemplaza StemForge.app por la del DMG y la abre."""
    old = tmp_path / "Apps" / "StemForge.app"
    (old / "Contents").mkdir(parents=True)
    (old / "Contents" / "version").write_text("vieja")
    src = tmp_path / "dmgsrc" / "StemForge.app" / "Contents"
    src.mkdir(parents=True)
    (src / "version").write_text("nueva")
    dmg = tmp_path / "dl" / "StemForge-9.9.9.dmg"
    dmg.parent.mkdir()
    subprocess.run(["hdiutil", "create", "-quiet", "-volname", "SF", "-srcfolder", str(tmp_path / "dmgsrc"),
                    "-format", "UDZO", str(dmg)], check=True)
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    log = tmp_path / "open.log"
    (fakebin / "open").write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    (fakebin / "open").chmod(0o755)
    env = {**os.environ, "PATH": f"{fakebin}:{os.environ['PATH']}"}
    subprocess.run(["/bin/sh", "-c", updater.mac_install_script(old, dmg)], env=env, check=True, timeout=120)
    assert (old / "Contents" / "version").read_text() == "nueva"
    assert not dmg.exists() and not old.with_name("StemForge.app.old").exists()
    assert log.read_text().strip() == str(old)


def test_concurrent_checks_do_not_clobber_download(tmp_path, monkeypatch):
    """Búsqueda automática lenta + búsqueda manual + descarga: una consulta tardía no pisa la descarga."""
    import threading

    monkeypatch.setenv("STEMFORGE_HOME", str(tmp_path))
    monkeypatch.setattr(updater, "install_kind", lambda: "python")
    release = threading.Event()
    calls = []

    def slow_fetch():
        calls.append(1)
        release.wait(5)
        return dict(MANIFEST, version="99.0.0")     # siempre más nueva que la versión del paquete

    monkeypatch.setattr(updater, "fetch_manifest", slow_fetch)
    up = updater.Updater()
    t = threading.Thread(target=up.check)
    t.start()
    for _ in range(100):
        if up.snapshot()["state"] == "checking":
            break
        threading.Event().wait(0.01)
    assert up.check(force=True)["state"] == "checking" and len(calls) == 1   # no lanza otra consulta
    release.set()
    t.join(5)
    assert up.snapshot()["state"] == "available"
    with up._lock:
        up.status["state"] = "downloading"          # descarga en curso
    assert up.check(force=True)["state"] == "downloading" and len(calls) == 1
