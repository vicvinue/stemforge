"""Genera stemforge/web/StemForge.icns siguiendo la plantilla de iconos de macOS.

Lienzo de 1024 px con el cuadrado redondeado de 824 px centrado (margen de 100 px),
fondo transparente y sombra suave, como el resto de apps del Dock.

Uso: .venv/bin/python tools/make_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stemforge" / "web" / "StemForge.icns"

SS = 4                      # supermuestreo para bordes suaves
SIZE = 1024
BOX = 824                   # plantilla de Apple: 824×824 dentro de 1024×1024
MARGIN = (SIZE - BOX) // 2
RADIUS = 185                # radio de esquina de la plantilla
TOP, BOTTOM = (139, 109, 255), (98, 64, 240)   # degradado violeta (marca)

# Barras de la forma de onda en la grilla 32×32 del logo: (x, y_inicio, y_fin)
BARS = [(7, 12, 20), (11, 9, 23), (15, 13, 19), (19, 7, 25), (23, 11, 21), (27, 15, 17)]
STROKE = 2.2


def _rounded_mask(size: int, box: int, margin: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, margin + box - 1, margin + box - 1), radius=radius, fill=255)
    return mask


def render(size: int = SIZE) -> Image.Image:
    s = size * SS / SIZE
    big = round(SIZE * SS)
    box, margin, radius = round(BOX * s), round(MARGIN * s), round(RADIUS * s)

    # Degradado vertical
    grad = Image.new("RGB", (1, big))
    for y in range(big):
        t = y / (big - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    grad = grad.resize((big, big))

    mask = _rounded_mask(big, box, margin, radius)
    body = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    body.paste(grad, (0, 0), mask)

    # Brillo sutil en la mitad superior
    gloss = Image.new("L", (big, big), 0)
    ImageDraw.Draw(gloss).rectangle((0, 0, big, margin + box // 2), fill=28)
    gloss = ImageChops.multiply(gloss, mask)
    white_layer = Image.new("RGBA", (big, big), (255, 255, 255, 0))
    white_layer.putalpha(gloss)
    body = Image.alpha_composite(body, white_layer)

    # Forma de onda blanca (grilla 32 escalada al cuadrado)
    unit = box / 32
    draw = ImageDraw.Draw(body)
    width = round(STROKE * unit)
    for x, y0, y1 in BARS:
        cx = margin + x * unit
        ya, yb = margin + y0 * unit, margin + y1 * unit
        draw.rounded_rectangle((cx - width / 2, ya - width / 2, cx + width / 2, yb + width / 2),
                               radius=width / 2, fill=(255, 255, 255, 255))

    # Sombra
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    shadow_mask = mask.filter(ImageFilter.GaussianBlur(round(14 * s)))
    shadow_mask = ImageChops.offset(shadow_mask, 0, round(10 * s)).point(lambda v: int(v * 0.32))
    shadow.putalpha(shadow_mask)

    canvas = Image.alpha_composite(shadow, body)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    master = render(SIZE)
    tmp = Path(tempfile.mkdtemp())
    iconset = tmp / "StemForge.iconset"
    iconset.mkdir()
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
            master.resize((px, px), Image.LANCZOS).save(iconset / name)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True)
    shutil.rmtree(tmp)
    print(f"Icono generado: {OUT}")


if __name__ == "__main__":
    main()
