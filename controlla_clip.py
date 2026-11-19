#!/usr/bin/env python3
"""Foglio di controllo per trovare le parti sgranate / scritte residue nelle clip di una pagina.

Uso:  python controlla_clip.py pijamamania              (tutte le clip)
      python controlla_clip.py pijamamania st01 tar      (solo quelle che iniziano così)

Per ogni clip crea analisi/sgranature/<pagina>/<clip>.jpg: 8 fotogrammi distribuiti su tutta la durata
(col secondo scritto sopra) e una griglia orizzontale ogni 5% dell'altezza, con le percentuali a lato.
Guardando il foglio si leggono subito altezza (y) e spessore della parte sgranata, da scrivere in
clip_originali/<pagina>/sgranature.yaml (vedi monta.py). Funziona solo con Pillow + ffmpeg.
"""
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FW, FH, N = 216, 384, 8          # fotogramma nel foglio (stesso 9:16 del reel finale)


def durata(f):
    out = subprocess.run([FFMPEG, "-nostdin", "-i", str(f)], capture_output=True, text=True).stderr
    for riga in out.splitlines():
        if "Duration:" in riga:
            h, m, s = riga.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def fotogramma(f, t):
    raw = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", str(f), "-frames:v", "1",
                          "-vf", f"scale={FW}:{FH}:force_original_aspect_ratio=increase,crop={FW}:{FH}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    if len(raw) < FW * FH * 3:
        return Image.new("RGB", (FW, FH), "black")
    return Image.frombytes("RGB", (FW, FH), raw[:FW * FH * 3])


def foglio(f, dest):
    d = durata(f)
    tempi = [d * (i + 0.5) / N for i in range(N)]
    S = Image.new("RGB", (40 + N * (FW + 4), FH + 22), "white")
    dr = ImageDraw.Draw(S)
    for i, t in enumerate(tempi):
        x = 40 + i * (FW + 4)
        S.paste(fotogramma(f, t), (x, 22))
        dr.text((x + 4, 5), f"{t:.1f}s", fill="black")
    for p in range(5, 100, 5):
        y = 22 + int(FH * p / 100)
        forte = p % 10 == 0
        dr.text((4, y - 6), f"{p}%", fill="red" if forte else "gray")
        for x in range(40, S.width, 6 if forte else 12):
            dr.line([(x, y), (x + (3 if forte else 2), y)], fill=(255, 0, 0) if forte else (255, 160, 160))
    S.save(dest, quality=88)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pagina, filtri = sys.argv[1], sys.argv[2:]
    out = BASE / "analisi" / "sgranature" / pagina
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted((BASE / "clip_originali" / pagina).glob("*.mp4")):
        if filtri and not any(f.stem.startswith(x) for x in filtri):
            continue
        foglio(f, out / f"{f.stem}.jpg")
        print(f"✓ {out.relative_to(BASE)}/{f.stem}.jpg")


if __name__ == "__main__":
    main()
